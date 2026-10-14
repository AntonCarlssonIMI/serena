# SPDX-License-Identifier: MIT
"""
Tokenisation of PL/SQL source text.
"""

import re
from dataclasses import dataclass
from enum import Enum

from solidlsp.language_servers.plsql.syntax import TextPosition, TextRange


class TokenKind(Enum):
    """
    The lexical category of a :class:`Token`.
    """

    WORD = "word"
    """an unquoted identifier or keyword (PL/SQL keywords depend on context, so they are not distinguished here)"""
    QUOTED_IDENTIFIER = "quoted_identifier"
    NUMBER = "number"
    SYMBOL = "symbol"
    UNIT_SEPARATOR = "unit_separator"
    """a line consisting solely of ``/``, which terminates a compilation unit in SQL*Plus scripts"""


@dataclass(slots=True)
class Token:
    """
    A lexical token of PL/SQL source text. Tokens never span several lines.
    """

    kind: TokenKind
    text: str
    key: str
    """the normalised text: upper case for words, the unquoted text for quoted identifiers, the text otherwise"""
    line: int
    column: int
    start_offset: int
    """the offset of the token's first character in the source text"""

    @property
    def range(self) -> TextRange:
        return TextRange(TextPosition(self.line, self.column), TextPosition(self.line, self.column + len(self.text)))

    @property
    def end_offset(self) -> int:
        return self.start_offset + len(self.text)

    def is_word(self, *words: str) -> bool:
        """
        :param words: upper-case words
        :return: whether the token is an unquoted word that equals one of the given words (case-insensitively)
        """
        return self.kind == TokenKind.WORD and self.key in words

    def is_symbol(self, *symbols: str) -> bool:
        return self.kind == TokenKind.SYMBOL and self.text in symbols

    def is_identifier(self) -> bool:
        return self.kind in (TokenKind.WORD, TokenKind.QUOTED_IDENTIFIER)


class PlsqlLexer:
    """
    Splits PL/SQL source text into tokens, dropping whitespace, comments and string literals.
    At unit level (before a unit's ``create``/``begin``/``declare`` keyword), SQL*Plus remark and prompt lines are
    dropped as comments, since their free text may contain apostrophes that would otherwise start a string literal.
    """

    _PATTERN = re.compile(
        r"""
        (?P<space>\s+)
        | (?P<line_comment>--[^\n]*)
        | (?P<block_comment>/\*.*?(?:\*/|\Z))
        | (?P<quoted_string>[nN]?[qQ]'(?:\[.*?\]|\{.*?\}|\(.*?\)|<.*?>|(?P<delimiter>\S).*?(?P=delimiter))')
        | (?P<string>[nN]?'(?:[^']|'')*')
        | (?P<quoted_identifier>"[^"\n]*")
        | (?P<word>[^\W\d][\w$\#]*)
        | (?P<number>\d+(?:\.(?!\.)\d*)?(?:[eE][+-]?\d+)?)
        | (?P<symbol>:=|=>|\.\.|\|\||<=|>=|<>|!=|.)
        """,
        re.VERBOSE | re.DOTALL,
    )
    _SKIPPED_GROUPS = frozenset({"space", "line_comment", "block_comment", "quoted_string", "string"})
    _SQLPLUS_COMMENT_COMMANDS = frozenset({"REM", "REMARK", "PRO", "PROMPT"})
    _UNIT_START_WORDS = frozenset({"CREATE", "BEGIN", "DECLARE"})

    def tokenize(self, text: str) -> list[Token]:
        """
        :param text: PL/SQL source text
        :return: the tokens of the text, in source order
        """
        line_starts = [0] + [match.end() for match in re.finditer("\n", text)]
        tokens: list[Token] = []
        line = 0
        at_unit_level = True
        position = 0
        while position < len(text):
            match = self._PATTERN.match(text, position)
            assert match is not None, "the symbol alternative matches any character"
            position = match.end()
            group = match.lastgroup
            if group in self._SKIPPED_GROUPS:
                continue

            # determine the line of the token (tokens are produced in source order)
            start = match.start()
            while line + 1 < len(line_starts) and line_starts[line + 1] <= start:
                line += 1

            # skip SQL*Plus comment lines between units
            if at_unit_level and group == "word":
                word = match.group().upper()
                if word in self._SQLPLUS_COMMENT_COMMANDS and not text[line_starts[line] : start].strip():
                    position = line_starts[line + 1] if line + 1 < len(line_starts) else len(text)
                    continue
                if word in self._UNIT_START_WORDS:
                    at_unit_level = False

            # classify the token
            token_text = match.group()
            if group == "word":
                kind, key = TokenKind.WORD, token_text.upper()
            elif group == "quoted_identifier":
                kind, key = TokenKind.QUOTED_IDENTIFIER, token_text[1:-1]
            elif group == "number":
                kind, key = TokenKind.NUMBER, token_text
            elif token_text == "/" and self._is_alone_on_line(text, line_starts, line):
                kind, key = TokenKind.UNIT_SEPARATOR, token_text
                at_unit_level = True
            else:
                kind, key = TokenKind.SYMBOL, token_text
            tokens.append(Token(kind, token_text, key, line, start - line_starts[line], start))
        return tokens

    @staticmethod
    def _is_alone_on_line(text: str, line_starts: list[int], line: int) -> bool:
        line_end = line_starts[line + 1] if line + 1 < len(line_starts) else len(text)
        return text[line_starts[line] : line_end].strip() == "/"
