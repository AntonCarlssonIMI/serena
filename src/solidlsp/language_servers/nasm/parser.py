# SPDX-License-Identifier: MIT
"""
Line-based parsing of NASM source text into declarations and name uses.
"""

import re
from dataclasses import dataclass

from solidlsp.language_servers.indexing_server.text import TextPosition, TextRange
from solidlsp.language_servers.nasm.syntax import Declaration, DeclarationKind, Identifier, NameUse, SourceUnit


class NasmParser:
    """
    Parses NASM source text into a :class:`SourceUnit`.

    The parser recognises labels (non-local labels with the local labels scoped to them), multi-line macros,
    single-line macros and ``equ`` constants as well as structures with their fields, and records every other
    identifier as a name use. Instructions are not interpreted: the extent of a label is the span of lines up to
    its last instruction or data definition before the next top-level declaration or section directive, and it
    starts with the comment lines directly above the declaration.
    Lines within multi-line macro bodies only contribute name uses, as their labels are instantiated per invocation.
    """

    def parse(self, uri: str, text: str) -> SourceUnit:
        """
        :param uri: the URI of the document
        :param text: the document's text
        :return: the parse result
        """
        return self._Run(uri, text.splitlines()).build()

    @dataclass(frozen=True)
    class _Token:
        """
        An identifier in a source line.
        """

        text: str
        start: int
        end: int

    class _Line:
        """
        A source line with its comment and the contents of its string literals removed.
        """

        # identifiers can neither continue a number nor follow a preprocessor sigil; the escape prefix $ and operators
        # such as ~ are not part of the identifier
        _IDENTIFIER = re.compile(r"(?<![\w.?#@%])" + Identifier.PATTERN.pattern)

        def __init__(self, number: int, text: str) -> None:
            self.number = number
            self.text = text
            self.code = self._strip_comment_and_strings(text)
            self.tokens = [
                NasmParser._Token(m.group(), m.start(), m.end()) for m in self._IDENTIFIER.finditer(self.code) if m.group() != "."
            ]
            words = self.code.replace("[", " ").split()
            self.first_word = words[0].lower() if words else ""

        @staticmethod
        def _strip_comment_and_strings(text: str) -> str:
            """
            :return: the text up to its comment, with every string literal (including its quotes) replaced by spaces,
                such that columns are preserved
            """
            characters = []
            quote: str | None = None
            for character in text:
                if quote is not None:
                    characters.append(" ")
                    if character == quote:
                        quote = None
                elif character in "'\"`":
                    quote = character
                    characters.append(" ")
                elif character == ";":
                    break
                else:
                    characters.append(character)
            return "".join(characters)

        @property
        def is_blank(self) -> bool:
            return not self.code.strip()

        @property
        def is_comment(self) -> bool:
            return self.text.lstrip().startswith(";")

        def word_after(self, token: "NasmParser._Token") -> str:
            """
            :return: the lower-case word following the given token (skipping a label colon), or an empty string
            """
            words = self.code[token.end :].lstrip().removeprefix(":").split()
            return words[0].lower() if words else ""

        def find_label(self) -> "NasmParser._Token | None":
            """
            :return: the label defined at the beginning of the line (followed by a colon, or without colon when
                followed by a data definition or ``equ``), if any
            """
            if not self.tokens:
                return None
            first = self.tokens[0]
            if self.code[: first.start].strip():
                return None
            if self.code[first.end :].lstrip().startswith(":"):
                return first
            next_word = self.code[first.end :].split()
            if next_word and next_word[0].lower() in NasmParser._Run.DATA_DIRECTIVES | {"equ"}:
                return first
            return None

    class _Run:
        """
        The state of parsing a single document.
        """

        DATA_DIRECTIVES = frozenset(
            {
                *("db", "dw", "dd", "dq", "dt", "do", "dy", "dz"),
                *("resb", "resw", "resd", "resq", "rest", "reso", "resy", "resz"),
                *("incbin", "times", "istruc"),
            }
        )
        _SECTION_DIRECTIVES = frozenset({"section", "segment", "absolute"})
        _FILE_DIRECTIVES = frozenset(
            {
                "global",
                "extern",
                "common",
                "static",
                "required",
                "bits",
                "default",
                "cpu",
                "org",
                "use16",
                "use32",
                "use64",
                "align",
                "alignb",
            }
        )
        _MACRO_START_DIRECTIVES = frozenset({"%macro", "%imacro"})
        _MACRO_END_DIRECTIVES = frozenset({"%endmacro", "%endm"})
        _CONSTANT_DIRECTIVES = frozenset(
            {"%define", "%xdefine", "%idefine", "%xidefine", "%assign", "%iassign", "%defstr", "%idefstr", "%deftok", "%ideftok"}
        )

        def __init__(self, uri: str, lines: list[str]) -> None:
            self._uri = uri
            self._lines = [NasmParser._Line(number, text) for number, text in enumerate(lines)]
            self._declarations: list[Declaration] = []
            self._uses: list[NameUse] = []
            self._comment_block: list[str] = []
            self._in_code_section = True
            self._last_content_line = 0
            self._open_label: Declaration | None = None
            """the non-local label whose extent is still being determined"""
            self._open_local_label: Declaration | None = None
            """the local label whose extent is still being determined"""
            self._scope_label: Declaration | None = None
            """the non-local label that qualifies local labels"""
            self._macro: Declaration | None = None
            self._macro_depth = 0
            self._structure: Declaration | None = None

        def build(self) -> SourceUnit:
            for line in self._lines:
                self._process(line)
            last_line = len(self._lines) - 1
            self._close_open_label()
            for declaration in (self._macro, self._structure):
                if declaration is not None:
                    self._close(declaration, last_line)
            return SourceUnit(self._uri, self._declarations, self._uses)

        def _process(self, line: "NasmParser._Line") -> None:
            # blank and comment lines: collect leading comments of the next declaration
            if line.is_blank:
                if line.is_comment:
                    self._comment_block.append(line.text.strip())
                else:
                    self._comment_block = []
                return
            leading_comments, self._comment_block = self._comment_block, []

            # multi-line macro bodies
            if self._macro is not None:
                self._process_macro_body_line(line)
                return

            # section switches and multi-line macro, constant and structure definitions
            word = line.first_word
            if word in self._SECTION_DIRECTIVES:
                self._close_open_label()
                section_name = line.code.replace("[", " ").replace("]", " ").split()[1:2]
                self._in_code_section = word != "absolute" and bool(section_name) and self._is_code_section(section_name[0])
            elif word in self._MACRO_START_DIRECTIVES and line.tokens:
                self._close_open_label()
                self._macro = self._declare(DeclarationKind.MACRO, line, line.tokens[0], line.tokens[0].text, leading_comments)
                self._macro_depth = 1
                self._add_uses(line, line.tokens[1:])
            elif word in self._CONSTANT_DIRECTIVES and line.tokens:
                self._close_open_label()
                constant = self._declare(DeclarationKind.CONSTANT, line, line.tokens[0], line.tokens[0].text, leading_comments)
                self._close(constant, line.number)
                self._add_uses(line, line.tokens[1:])
            elif word == "struc" and len(line.tokens) > 1:
                self._close_open_label()
                self._structure = self._declare(DeclarationKind.STRUCTURE, line, line.tokens[1], line.tokens[1].text, leading_comments)
                self._add_uses(line, line.tokens[2:])
            elif word == "endstruc" and self._structure is not None:
                self._close(self._structure, line.number)
                self._structure = None
                self._scope_label = None
            elif self._structure is not None:
                self._process_structure_line(line, leading_comments)
            else:
                self._process_statement(line, leading_comments)

        def _process_macro_body_line(self, line: "NasmParser._Line") -> None:
            assert self._macro is not None
            if line.first_word in self._MACRO_START_DIRECTIVES:
                self._macro_depth += 1
            elif line.first_word in self._MACRO_END_DIRECTIVES:
                self._macro_depth -= 1
                if self._macro_depth == 0:
                    self._close(self._macro, line.number)
                    self._macro = None
                    return
            self._add_uses(line, line.tokens, qualify_local=False)

        def _process_structure_line(self, line: "NasmParser._Line", leading_comments: list[str]) -> None:
            assert self._structure is not None
            label = line.find_label()
            if label is not None and Identifier.is_local(label.text):
                field_declaration = Declaration(
                    kind=DeclarationKind.FIELD,
                    name=label.text,
                    key=self._structure.key + label.text,
                    uri=self._uri,
                    name_range=self._token_range(line, label),
                    range=self._line_range(line.number, line.number),
                    header=self._header(line, leading_comments),
                )
                self._structure.add_child(field_declaration)
                self._add_uses(line, [token for token in line.tokens if token is not label])
            else:
                self._add_uses(line, line.tokens)

        def _process_statement(self, line: "NasmParser._Line", leading_comments: list[str]) -> None:
            label = line.find_label()
            if label is None:
                self._add_uses(line, line.tokens)
                if line.first_word not in self._FILE_DIRECTIVES and not line.first_word.startswith("%"):
                    self._last_content_line = line.number
                return

            # label definitions
            next_word = line.word_after(label)
            if next_word == "equ":
                if not Identifier.is_local(label.text):
                    self._close_open_label()
                constant = self._declare(DeclarationKind.CONSTANT, line, label, self._qualify(label.text), leading_comments)
                self._close(constant, line.number)
            elif Identifier.is_local(label.text):
                self._close_open_local_label()
                self._open_local_label = self._declare(
                    DeclarationKind.LOCAL_LABEL, line, label, self._qualify(label.text), leading_comments, parent=self._scope_label
                )
                self._last_content_line = line.number
            else:
                self._close_open_label()
                is_data = not self._in_code_section or next_word in self.DATA_DIRECTIVES
                kind = DeclarationKind.DATA if is_data else DeclarationKind.ROUTINE
                self._open_label = self._declare(kind, line, label, label.text, leading_comments)
                if not label.text.startswith("..@"):
                    self._scope_label = self._open_label
                self._last_content_line = line.number
            self._add_uses(line, [token for token in line.tokens if token is not label and token.text.lower() != "equ"])

        # declarations

        def _declare(
            self,
            kind: DeclarationKind,
            line: "NasmParser._Line",
            name: "NasmParser._Token",
            key: str,
            leading_comments: list[str],
            parent: Declaration | None = None,
        ) -> Declaration:
            """
            Creates a declaration whose extent provisionally covers its leading comments and its own line.

            :param parent: the declaration to add the new declaration to as a child; None to add it at top level
            """
            declaration = Declaration(
                kind=kind,
                name=name.text,
                key=key,
                uri=self._uri,
                name_range=self._token_range(line, name),
                range=self._line_range(line.number - len(leading_comments), line.number),
                header=self._header(line, leading_comments),
            )
            if parent is not None:
                parent.add_child(declaration)
            else:
                self._declarations.append(declaration)
            return declaration

        def _close(self, declaration: Declaration, end_line: int) -> None:
            self._set_extent(declaration, max(declaration.name_range.start.line, end_line))

        def _close_open_local_label(self) -> None:
            if self._open_local_label is not None:
                self._close(self._open_local_label, self._last_content_line)
                self._open_local_label = None

        def _close_open_label(self) -> None:
            self._close_open_local_label()
            if self._open_label is not None:
                self._close(self._open_label, self._last_content_line)
                self._open_label = None

        def _set_extent(self, declaration: Declaration, end_line: int) -> None:
            declaration.range = self._line_range(declaration.range.start.line, end_line)

        # name uses

        def _add_uses(self, line: "NasmParser._Line", tokens: list["NasmParser._Token"], qualify_local: bool = True) -> None:
            for token in tokens:
                key = self._qualify(token.text) if qualify_local else token.text
                self._uses.append(NameUse(key=key, uri=self._uri, range=self._token_range(line, token)))

        def _qualify(self, name: str) -> str:
            """
            :return: the fully qualified name of the given name, prefixing local names with the current scope label
            """
            if Identifier.is_local(name) and self._scope_label is not None:
                return self._scope_label.key + name
            return name

        @staticmethod
        def _is_code_section(section_name: str) -> bool:
            name = section_name.lower()
            return name.startswith((".text", ".init", ".fini")) or name in ("text", "code", ".code")

        # positions

        @staticmethod
        def _token_range(line: "NasmParser._Line", token: "NasmParser._Token") -> TextRange:
            return TextRange(TextPosition(line.number, token.start), TextPosition(line.number, token.end))

        def _line_range(self, start_line: int, end_line: int) -> TextRange:
            start_text = self._lines[start_line].text
            start_character = len(start_text) - len(start_text.lstrip())
            return TextRange(TextPosition(start_line, start_character), TextPosition(end_line, len(self._lines[end_line].text.rstrip())))

        @staticmethod
        def _header(line: "NasmParser._Line", leading_comments: list[str]) -> str:
            return "\n".join([*leading_comments, line.text.strip()])
