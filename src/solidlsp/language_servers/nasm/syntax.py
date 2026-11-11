# SPDX-License-Identifier: MIT
"""
Syntax model of NASM sources: declarations, name uses and their positions.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum

from solidlsp.language_servers.indexing_server.text import TextPosition, TextRange


class DeclarationKind(Enum):
    """
    The kind of a :class:`Declaration`.
    """

    ROUTINE = "routine"
    """a non-local label in a code section"""
    DATA = "data"
    """a non-local label in a data section or a label followed by a data definition"""
    LOCAL_LABEL = "local label"
    """a label starting with a single dot, which is scoped to the preceding non-local label"""
    MACRO = "macro"
    CONSTANT = "constant"
    """a single-line macro (``%define`` and its variants), an ``%assign`` variable or an ``equ`` constant"""
    STRUCTURE = "structure"
    FIELD = "field"


@dataclass(eq=False)
class Declaration:
    """
    A named declaration in a NASM source, e.g. a label, a macro or a constant.

    Declarations are compared by identity.
    """

    kind: DeclarationKind
    name: str
    """the name as written in the source"""
    key: str
    """the fully qualified name used for lookups (for local labels and fields, prefixed with the enclosing label)"""
    uri: str
    """the URI of the document containing the declaration"""
    name_range: TextRange
    range: TextRange
    """the full extent of the declaration, e.g. for a routine, from its label to its last instruction"""
    header: str
    """the declaration's line, preceded by the comment lines directly above it"""
    parent: "Declaration | None" = field(default=None, repr=False)
    children: list["Declaration"] = field(default_factory=list, repr=False)

    def add_child(self, child: "Declaration") -> None:
        child.parent = self
        self.children.append(child)

    def iter_tree(self) -> Iterator["Declaration"]:
        """
        :return: an iterator over this declaration and all its descendants (depth-first, in source order)
        """
        yield self
        for child in self.children:
            yield from child.iter_tree()


@dataclass(frozen=True)
class NameUse:
    """
    A use of a name, e.g. a jump target, a memory operand or a macro invocation.
    """

    key: str
    """the fully qualified name (for local labels, prefixed with the enclosing label)"""
    uri: str
    """the URI of the document containing the use"""
    range: TextRange


@dataclass
class SourceUnit:
    """
    The parse result of a document: its top-level declarations and all name uses.
    """

    uri: str
    declarations: list[Declaration]
    name_uses: list[NameUse]

    def iter_declarations(self) -> Iterator[Declaration]:
        """
        :return: an iterator over all declarations (depth-first, in source order)
        """
        for declaration in self.declarations:
            yield from declaration.iter_tree()

    def find_key_at(self, position: TextPosition) -> str | None:
        """
        :param position: a position in the document
        :return: the fully qualified name of the declaration or name use at the given position, if any
        """
        for declaration in self.iter_declarations():
            if declaration.name_range.contains(position):
                return declaration.key
        for use in self.name_uses:
            if use.range.contains(position):
                return use.key
        return None
