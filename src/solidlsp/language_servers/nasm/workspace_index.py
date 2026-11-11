# SPDX-License-Identifier: MIT
"""
In-memory index of the parsed NASM sources of a workspace.
"""

from collections.abc import Iterator

from solidlsp.language_servers.indexing_server.server import SourceIndex
from solidlsp.language_servers.nasm.parser import NasmParser
from solidlsp.language_servers.nasm.syntax import Declaration, NameUse, SourceUnit


class WorkspaceIndex(SourceIndex[SourceUnit]):
    """
    The parsed NASM sources of a workspace, with lookups by fully qualified name across all sources.
    """

    def __init__(self, parser: NasmParser) -> None:
        self._parser = parser
        self._units: dict[str, SourceUnit] = {}
        self._declarations_by_key: dict[str, dict[str, list[Declaration]]] = {}
        """maps a fully qualified name to the declarations with that name, grouped by URI"""
        self._uses_by_key: dict[str, dict[str, list[NameUse]]] = {}
        """maps a fully qualified name to its uses, grouped by URI"""

    def update(self, uri: str, text: str) -> SourceUnit:
        self.remove(uri)
        unit = self._parser.parse(uri, text)
        self._units[uri] = unit
        for declaration in unit.iter_declarations():
            self._declarations_by_key.setdefault(declaration.key, {}).setdefault(uri, []).append(declaration)
        for use in unit.name_uses:
            self._uses_by_key.setdefault(use.key, {}).setdefault(uri, []).append(use)
        return unit

    def remove(self, uri: str) -> None:
        unit = self._units.pop(uri, None)
        if unit is None:
            return
        for declaration in unit.iter_declarations():
            self._discard(self._declarations_by_key, declaration.key, uri)
        for use in unit.name_uses:
            self._discard(self._uses_by_key, use.key, uri)

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

    def find_declarations(self, key: str) -> dict[str, list[Declaration]]:
        """
        :param key: a fully qualified name
        :return: the declarations with the given name, grouped by the URI of their document
        """
        return self._declarations_by_key.get(key, {})

    def iter_uses(self, key: str) -> Iterator[NameUse]:
        """
        :param key: a fully qualified name
        :return: an iterator over the uses of the given name
        """
        for uses in list(self._uses_by_key.get(key, {}).values()):
            yield from uses
