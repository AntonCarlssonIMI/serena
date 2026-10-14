# SPDX-License-Identifier: MIT
"""
In-memory index of the parsed PL/SQL sources of a workspace.
"""

from collections.abc import Iterator

from solidlsp.language_servers.plsql.parser import PlsqlParser
from solidlsp.language_servers.plsql.syntax import Declaration, NameUse, SourceUnit


class WorkspaceIndex:
    """
    The parsed PL/SQL sources of a workspace, with lookups by name across all sources.
    """

    def __init__(self, parser: PlsqlParser) -> None:
        self._parser = parser
        self._units: dict[str, SourceUnit] = {}
        self._top_level_by_key: dict[str, dict[str, list[Declaration]]] = {}
        """maps a normalised name to the top-level declarations with that name, grouped by URI"""
        self._uses_by_key: dict[str, dict[str, list[NameUse]]] = {}
        """maps a normalised name to the name uses containing a segment with that name, grouped by URI"""

    def update(self, uri: str, text: str) -> SourceUnit:
        """
        Parses the given text and replaces the document's previous entry (if any).

        :param uri: the document's URI
        :param text: the document's text
        :return: the parse result
        """
        self.remove(uri)
        unit = self._parser.parse(uri, text)
        self._units[uri] = unit
        for declaration in unit.declarations:
            self._top_level_by_key.setdefault(declaration.key, {}).setdefault(uri, []).append(declaration)
        for use in unit.name_uses:
            for key in {segment.key for segment in use.segments}:
                self._uses_by_key.setdefault(key, {}).setdefault(uri, []).append(use)
        return unit

    def remove(self, uri: str) -> None:
        """
        :param uri: the URI of a document to remove from the index (no-op if it is not indexed)
        """
        unit = self._units.pop(uri, None)
        if unit is None:
            return
        for declaration in unit.declarations:
            self._discard(self._top_level_by_key, declaration.key, uri)
        for use in unit.name_uses:
            for segment in use.segments:
                self._discard(self._uses_by_key, segment.key, uri)

    @staticmethod
    def _discard(mapping: dict[str, dict[str, list]], key: str, uri: str) -> None:
        entries_by_uri = mapping.get(key)
        if entries_by_uri is not None:
            entries_by_uri.pop(uri, None)
            if not entries_by_uri:
                del mapping[key]

    def get_unit(self, uri: str) -> SourceUnit | None:
        return self._units.get(uri)

    def iter_units(self) -> Iterator[SourceUnit]:
        return iter(list(self._units.values()))

    def find_top_level(self, key: str) -> list[Declaration]:
        """
        :param key: a normalised name
        :return: the top-level declarations (packages, standalone subprograms, triggers) with the given name
        """
        return [declaration for declarations in self._top_level_by_key.get(key, {}).values() for declaration in declarations]

    def find_packages(self, key: str) -> list[Declaration]:
        """
        :param key: a normalised name
        :return: the package specs and bodies with the given name
        """
        return [declaration for declaration in self.find_top_level(key) if declaration.kind.is_package()]

    def iter_uses(self, key: str) -> Iterator[NameUse]:
        """
        :param key: a normalised name
        :return: an iterator over the name uses that contain a segment with the given name
        """
        for uses in list(self._uses_by_key.get(key, {}).values()):
            yield from uses

    def get_logical_entity(self, declaration: Declaration) -> list[Declaration]:
        """
        Determines the declarations that constitute the same logical entity as the given one: all parts (spec and
        bodies) of a package, or the declaration in a package spec together with the implementation in the package
        body of a subprogram (matched by kind, name and parameter names).

        :param declaration: a declaration
        :return: the declarations of the logical entity, including the given declaration
        """
        if declaration.kind.is_package():
            return self.find_packages(declaration.key)
        package = declaration.parent
        if declaration.kind.is_subprogram() and package is not None and package.kind.is_package():
            parameter_names = declaration.parameters.names if declaration.parameters is not None else ()
            counterparts = [
                candidate
                for part in self.find_packages(package.key)
                for candidate in part.children_named(declaration.key)
                if candidate.kind == declaration.kind
                and (candidate.parameters.names if candidate.parameters is not None else ()) == parameter_names
            ]
            if counterparts:
                return counterparts
        return [declaration]
