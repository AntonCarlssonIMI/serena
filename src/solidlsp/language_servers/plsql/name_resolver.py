# SPDX-License-Identifier: MIT
"""
Resolution of PL/SQL name uses to declarations.
"""

from solidlsp.language_servers.plsql.syntax import Declaration, DeclarationKind, NameUse, SourceLocation, TextPosition
from solidlsp.language_servers.plsql.workspace_index import WorkspaceIndex


class NameResolver:
    """
    Resolves positions in PL/SQL documents to declarations, definitions and references, based on a workspace index.

    Unqualified names are looked up from the innermost enclosing scope outwards (enclosing subprograms, the package
    body, the package spec), then among the top-level units of the workspace. In a qualified name ``Pkg.Name``,
    ``Name`` is looked up among the members of all parts of package ``Pkg``. Overloads are filtered by the number of
    call arguments. Names that cannot be resolved are ignored.
    """

    def __init__(self, index: WorkspaceIndex) -> None:
        self._index = index

    def find_declarations(self, uri: str, position: TextPosition) -> list[Declaration]:
        """
        :param uri: the URI of an indexed document
        :param position: a position in the document
        :return: the declaration whose name is at the position, or the declarations that the name use at the
            position resolves to
        """
        unit = self._index.get_unit(uri)
        if unit is None:
            return []
        declaration = unit.find_declaration_at(position)
        if declaration is not None:
            return [declaration]
        occurrence = unit.find_name_occurrence_at(position)
        if occurrence is None:
            return []
        return self._resolve(occurrence.use, occurrence.segment_index)

    def find_definitions(self, uri: str, position: TextPosition) -> list[Declaration]:
        """
        :param uri: the URI of an indexed document
        :param position: a position in the document
        :return: the implementations of the logical entities found at the position or, for entities without an
            implementation, their declarations
        """
        definitions: list[Declaration] = []
        for declaration in self.find_declarations(uri, position):
            entity = self._index.get_logical_entity(declaration)
            implementations = [part for part in entity if part.is_implementation]
            for definition in implementations or entity:
                if definition not in definitions:
                    definitions.append(definition)
        return definitions

    def find_references(self, uri: str, position: TextPosition, include_declaration: bool) -> list[SourceLocation]:
        """
        :param uri: the URI of an indexed document
        :param position: a position in the document
        :param include_declaration: whether to include the names of the declarations of the logical entities
        :return: the locations of all uses that resolve to the logical entities found at the position
        """
        entity: set[Declaration] = set()
        for declaration in self.find_declarations(uri, position):
            entity.update(self._index.get_logical_entity(declaration))

        locations = [SourceLocation(declaration.uri, declaration.name_range) for declaration in entity] if include_declaration else []
        for key in {declaration.key for declaration in entity}:
            for use in self._index.iter_uses(key):
                for index, segment in enumerate(use.segments):
                    if segment.key == key and not entity.isdisjoint(self._resolve(use, index)):
                        locations.append(SourceLocation(use.uri, segment.range))
        return locations

    def _resolve(self, use: NameUse, segment_index: int) -> list[Declaration]:
        """
        :param use: a name use
        :param segment_index: the index of the segment to resolve
        :return: the declarations that the segment refers to
        """
        candidates = self._lookup_unqualified(use.scope, use.segments[0].key)
        for segment in use.segments[1 : segment_index + 1]:
            if not candidates:
                return []
            candidates = self._lookup_members(candidates, segment.key)
        if segment_index == len(use.segments) - 1:
            candidates = self._filter_overloads(candidates, use.argument_count)
        return candidates

    def _lookup_unqualified(self, scope: Declaration | None, key: str) -> list[Declaration]:
        declaration = scope
        while declaration is not None:
            matches = list(declaration.children_named(key))
            if declaration.kind == DeclarationKind.PACKAGE_BODY:
                for part in self._index.find_packages(declaration.key):
                    if part.kind == DeclarationKind.PACKAGE_SPEC:
                        matches.extend(part.children_named(key))
            if matches:
                return matches
            declaration = declaration.parent
        return self._index.find_top_level(key)

    def _lookup_members(self, candidates: list[Declaration], key: str) -> list[Declaration]:
        members: list[Declaration] = []
        visited_package_keys: set[str] = set()
        for candidate in candidates:
            if candidate.kind.is_package() and candidate.key not in visited_package_keys:
                visited_package_keys.add(candidate.key)
                for part in self._index.find_packages(candidate.key):
                    members.extend(part.children_named(key))
        return members

    @staticmethod
    def _filter_overloads(candidates: list[Declaration], argument_count: int) -> list[Declaration]:
        if len(candidates) <= 1:
            return candidates
        fitting = [c for c in candidates if c.parameters is None or c.parameters.accepts(argument_count)]
        return fitting or candidates
