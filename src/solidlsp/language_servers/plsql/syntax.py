# SPDX-License-Identifier: MIT
"""
Syntax model of PL/SQL sources: declarations, name uses and their positions.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True, order=True)
class TextPosition:
    """
    A zero-based position (line and character) in a source text.
    """

    line: int
    character: int


@dataclass(frozen=True)
class TextRange:
    """
    A range in a source text.
    """

    start: TextPosition
    end: TextPosition

    def contains(self, position: TextPosition) -> bool:
        """
        :param position: the position to test
        :return: whether the position lies within the range; both ends are inclusive, such that a position directly
            after an identifier still refers to it
        """
        return self.start <= position <= self.end


class DeclarationKind(Enum):
    """
    The kind of a :class:`Declaration`.
    """

    PACKAGE_SPEC = "package"
    PACKAGE_BODY = "package body"
    PROCEDURE = "procedure"
    FUNCTION = "function"
    TRIGGER = "trigger"
    TYPE = "type"
    CURSOR = "cursor"
    VARIABLE = "variable"
    CONSTANT = "constant"
    EXCEPTION = "exception"
    PARAMETER = "parameter"
    ANONYMOUS_BLOCK = "anonymous block"

    def is_package(self) -> bool:
        return self in (DeclarationKind.PACKAGE_SPEC, DeclarationKind.PACKAGE_BODY)

    def is_subprogram(self) -> bool:
        return self in (DeclarationKind.PROCEDURE, DeclarationKind.FUNCTION)


@dataclass(frozen=True)
class ParameterSignature:
    """
    The parameter list of a subprogram or cursor.
    """

    names: tuple[str, ...]
    """the normalised parameter names in declaration order"""
    optional_count: int
    """the number of parameters that have a default value"""

    def accepts(self, argument_count: int) -> bool:
        """
        :param argument_count: the number of arguments of a call
        :return: whether a call with the given number of arguments can bind to this parameter list
        """
        return len(self.names) - self.optional_count <= argument_count <= len(self.names)


@dataclass(eq=False)
class Declaration:
    """
    A named declaration in a PL/SQL source, e.g. a package, subprogram, type or variable.

    Declarations are compared by identity.
    """

    kind: DeclarationKind
    name: str
    """the name as written in the source (without quotes for quoted identifiers)"""
    key: str
    """the normalised name used for lookups (upper case for unquoted identifiers)"""
    uri: str
    """the URI of the document containing the declaration"""
    name_range: TextRange
    range: TextRange
    """the full extent of the declaration, from its first keyword to its terminating semicolon"""
    header: str
    """the declaration text with normalised whitespace; for packages, subprograms and triggers, only up to ``is``/``as``/``;``"""
    is_symbol: bool
    """whether the declaration is reported as a document symbol (parameters and subprogram-local items are not)"""
    is_implementation: bool = False
    """whether the declaration carries an implementation (a package body, a subprogram body or a trigger)"""
    parameters: ParameterSignature | None = None
    """the parameter list (for subprograms and cursors)"""
    parent: "Declaration | None" = field(default=None, repr=False)
    """the enclosing declaration, which is also the enclosing scope"""
    children: list["Declaration"] = field(default_factory=list, repr=False)
    _children_by_key: dict[str, list["Declaration"]] | None = field(default=None, init=False, repr=False)

    def add_child(self, child: "Declaration") -> None:
        child.parent = self
        self.children.append(child)
        self._children_by_key = None

    def iter_tree(self) -> Iterator["Declaration"]:
        """
        :return: an iterator over this declaration and all its descendants (depth-first, in source order)
        """
        yield self
        for child in self.children:
            yield from child.iter_tree()

    def children_named(self, key: str) -> list["Declaration"]:
        """
        :param key: a normalised name
        :return: the direct children with the given normalised name
        """
        if self._children_by_key is None:
            children_by_key: dict[str, list[Declaration]] = {}
            for child in self.children:
                children_by_key.setdefault(child.key, []).append(child)
            self._children_by_key = children_by_key
        return self._children_by_key.get(key, [])


@dataclass(slots=True)
class NameSegment:
    """
    An identifier within a (possibly qualified) name use, e.g. ``Read_Order`` in ``Order_Mgmt.Read_Order``.
    """

    key: str
    """the normalised name"""
    line: int
    column: int
    end_column: int

    @property
    def range(self) -> TextRange:
        return TextRange(TextPosition(self.line, self.column), TextPosition(self.line, self.end_column))


@dataclass(slots=True)
class NameUse:
    """
    A use of a (possibly qualified) name, e.g. a call, a type reference or a variable access.
    """

    uri: str
    """the URI of the document containing the use"""
    segments: tuple[NameSegment, ...]
    scope: Declaration | None
    """the innermost declaration enclosing the use, from which name lookup starts (None at unit level)"""
    argument_count: int
    """the number of arguments if the name is followed by an argument list, 0 otherwise"""


@dataclass(frozen=True)
class NameOccurrence:
    """
    A segment of a name use, identified by its index.
    """

    use: NameUse
    segment_index: int


@dataclass(frozen=True)
class SourceLocation:
    """
    A range in a document.
    """

    uri: str
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

    def find_declaration_at(self, position: TextPosition) -> Declaration | None:
        """
        :param position: a position in the document
        :return: the declaration whose name is at the given position, if any
        """
        for declaration in self.iter_declarations():
            if declaration.name_range.contains(position):
                return declaration
        return None

    def find_name_occurrence_at(self, position: TextPosition) -> NameOccurrence | None:
        """
        :param position: a position in the document
        :return: the name use segment at the given position, if any
        """
        for use in self.name_uses:
            for index, segment in enumerate(use.segments):
                if segment.line == position.line and segment.column <= position.character <= segment.end_column:
                    return NameOccurrence(use, index)
        return None
