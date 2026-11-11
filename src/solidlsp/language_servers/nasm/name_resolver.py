# SPDX-License-Identifier: MIT
"""
Resolution of NASM names to their declarations.
"""

from collections.abc import Iterator

from solidlsp.language_servers.indexing_server.text import SourceLocation, TextPosition, TextRange, TextReplacement
from solidlsp.language_servers.nasm.syntax import Declaration, Identifier, NameUse
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
        locations = [SourceLocation(use.uri, use.range) for use in self._iter_uses_resolving_to(declarations[0].key, declarations)]
        if include_declaration:
            locations.extend(SourceLocation(declaration.uri, declaration.name_range) for declaration in declarations)
        return locations

    def plan_rename(self, uri: str, position: TextPosition, new_name: str) -> list[TextReplacement]:
        """
        Determines the replacements that rename the name (or declaration) at the given position: its declarations,
        its uses (whether written as the name itself or fully qualified) and, for a non-local label or structure, the
        fully qualified uses of its local labels and fields, which are qualified by the renamed name.
        Comments are not changed.

        :param uri: the URI of an indexed document
        :param position: a position in the document
        :param new_name: the new name
        :return: the replacements (empty if there is no name at the given position)
        :raises ValueError: if the new name is not a valid identifier or differs in locality from the current name
        """
        declarations = self.find_declarations(uri, position)
        if not declarations:
            return []
        name = declarations[0].name
        if not Identifier.is_valid(new_name):
            raise ValueError(f"'{new_name}' is not a valid NASM identifier")
        if Identifier.is_local(new_name) != Identifier.is_local(name):
            raise ValueError(f"'{new_name}' must {'' if Identifier.is_local(name) else 'not '}start with a single dot like '{name}'")

        # declarations and uses of the name; a fully qualified use of a local name ends with the name
        replacements = {TextReplacement(SourceLocation(d.uri, d.name_range), new_name) for d in declarations}
        for use in self._iter_uses_resolving_to(declarations[0].key, declarations):
            replacements.add(TextReplacement(SourceLocation(use.uri, self._suffix_range(use.range, len(name))), new_name))

        # fully qualified uses of local labels and fields, which start with the renamed name
        if not Identifier.is_local(name):
            for child in (child for declaration in declarations for child in declaration.children):
                for use in self._iter_uses_resolving_to(child.key, [child]):
                    if self._length(use.range) == len(child.key):
                        replacements.add(TextReplacement(SourceLocation(use.uri, self._prefix_range(use.range, len(name))), new_name))
        return list(replacements)

    def _iter_uses_resolving_to(self, key: str, declarations: list[Declaration]) -> Iterator[NameUse]:
        targets = set(declarations)
        for use in self._index.iter_uses(key):
            if targets.intersection(self._resolve(use.key, use.uri)):
                yield use

    def _resolve(self, key: str, uri: str) -> list[Declaration]:
        declarations_by_uri = self._index.find_declarations(key)
        local_declarations = declarations_by_uri.get(uri)
        if local_declarations:
            return list(local_declarations)
        return [declaration for declarations in declarations_by_uri.values() for declaration in declarations]

    @staticmethod
    def _length(text_range: TextRange) -> int:
        """:return: the length of a range within a single line"""
        return text_range.end.character - text_range.start.character

    @staticmethod
    def _prefix_range(text_range: TextRange, length: int) -> TextRange:
        return TextRange(text_range.start, TextPosition(text_range.start.line, text_range.start.character + length))

    @staticmethod
    def _suffix_range(text_range: TextRange, length: int) -> TextRange:
        return TextRange(TextPosition(text_range.end.line, text_range.end.character - length), text_range.end)
