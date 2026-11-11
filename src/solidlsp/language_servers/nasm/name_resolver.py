# SPDX-License-Identifier: MIT
"""
Resolution of NASM names to their declarations.
"""

from solidlsp.language_servers.indexing_server.text import SourceLocation, TextPosition
from solidlsp.language_servers.nasm.syntax import Declaration
from solidlsp.language_servers.nasm.workspace_index import WorkspaceIndex


class NameResolver:
    """
    Resolves names in NASM sources to their declarations, preferring declarations in the document containing the
    name (as non-global labels are private to their file) and falling back to declarations in other documents.
    """

    def __init__(self, index: WorkspaceIndex) -> None:
        self._index = index

    def find_declarations(self, uri: str, position: TextPosition) -> list[Declaration]:
        """
        :param uri: the URI of an indexed document
        :param position: a position in the document
        :return: the declarations of the name (or declaration) at the given position
        """
        unit = self._index.get_unit(uri)
        key = unit.find_key_at(position) if unit is not None else None
        if key is None:
            return []
        return self._resolve(key, uri)

    def find_references(self, uri: str, position: TextPosition, include_declaration: bool) -> list[SourceLocation]:
        """
        :param uri: the URI of an indexed document
        :param position: a position in the document
        :param include_declaration: whether to include the locations of the declarations themselves
        :return: the locations of the uses of the name (or declaration) at the given position that resolve to the same
            declarations
        """
        declarations = self.find_declarations(uri, position)
        if not declarations:
            return []
        targets = set(declarations)
        locations = [
            SourceLocation(use.uri, use.range)
            for use in self._index.iter_uses(declarations[0].key)
            if targets.intersection(self._resolve(use.key, use.uri))
        ]
        if include_declaration:
            locations.extend(SourceLocation(declaration.uri, declaration.name_range) for declaration in declarations)
        return locations

    def _resolve(self, key: str, uri: str) -> list[Declaration]:
        declarations_by_uri = self._index.find_declarations(key)
        local_declarations = declarations_by_uri.get(uri)
        if local_declarations:
            return list(local_declarations)
        return [declaration for declarations in declarations_by_uri.values() for declaration in declarations]
