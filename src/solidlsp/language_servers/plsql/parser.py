# SPDX-License-Identifier: MIT
"""
Structural parsing of PL/SQL source text into declarations and name uses.
"""

from solidlsp.language_servers.plsql.lexer import PlsqlLexer, Token, TokenKind
from solidlsp.language_servers.plsql.syntax import (
    Declaration,
    DeclarationKind,
    NameSegment,
    NameUse,
    ParameterSignature,
    SourceUnit,
    TextRange,
)


class PlsqlParser:
    """
    Parses PL/SQL source text into a :class:`SourceUnit`.

    The parser recognises the declarative structure of compilation units (packages, standalone subprograms,
    triggers and the declarations within them) and records every name use together with its enclosing scope.
    Statements are not parsed; the extent of a block is determined by balancing its delimiters.
    Malformed input never causes an exception: the parser resynchronises at the next subprogram keyword or
    unit separator.
    """

    def __init__(self) -> None:
        self._lexer = PlsqlLexer()

    def parse(self, uri: str, text: str) -> SourceUnit:
        """
        :param uri: the URI of the document containing the text
        :param text: PL/SQL source text
        :return: the parse result
        """
        return self._Run(uri, text, self._lexer.tokenize(text)).run()

    class _Run:
        """
        The parsing of a single source text.
        """

        _SQLPLUS_COMMANDS = frozenset(
            {
                "ACCEPT", "BREAK", "BTITLE", "CLEAR", "COLUMN", "COMPUTE", "CONNECT", "DEFINE", "DISCONNECT", "EXIT",
                "HOST", "PAUSE", "PRINT", "PROMPT", "QUIT", "REM", "REMARK", "SET", "SHOW", "SPOOL", "TTITLE",
                "UNDEFINE", "VARIABLE", "WHENEVER",
            }
        )  # fmt: skip
        _NON_REFERENCE_WORDS = frozenset(
            {
                # reserved words and keywords
                "ALL", "ALTER", "AND", "ANY", "AS", "ASC", "AT", "BEGIN", "BETWEEN", "BODY", "BULK", "BY", "CASE",
                "CHECK", "CLOSE", "COLLECT", "COMMIT", "CONSTANT", "CONTINUE", "CREATE", "CURSOR", "DECLARE",
                "DEFAULT", "DELETE", "DESC", "DISTINCT", "DROP", "EACH", "ELSE", "ELSIF", "END", "EXCEPTION",
                "EXECUTE", "EXISTS", "EXIT", "FALSE", "FETCH", "FOR", "FORALL", "FROM", "FUNCTION", "GOTO", "GRANT",
                "GROUP", "HAVING", "IF", "IMMEDIATE", "IN", "INDEX", "INSERT", "INTERSECT", "INTO", "IS", "LIKE",
                "LOCK", "LOOP", "MERGE", "MINUS", "NOCOPY", "NOT", "NOWAIT", "NULL", "OF", "ON", "OPEN", "OR",
                "ORDER", "OTHERS", "OUT", "PACKAGE", "PRAGMA", "PRIOR", "PROCEDURE", "RAISE", "RECORD", "REF",
                "REPLACE", "RETURN", "RETURNING", "REVERSE", "ROLLBACK", "ROWTYPE", "SAVEPOINT", "SELECT", "SET",
                "SQL", "SUBTYPE", "TABLE", "THEN", "TO", "TRIGGER", "TRUE", "TYPE", "UNION", "UNIQUE", "UPDATE",
                "USING", "VALUES", "VIEW", "WHEN", "WHERE", "WHILE", "WITH",
                # frequent built-in types, functions and exceptions
                "ABS", "AVG", "BINARY_INTEGER", "BLOB", "BOOLEAN", "CHAR", "CLOB", "COALESCE", "COUNT", "DATE",
                "DECODE", "DUP_VAL_ON_INDEX", "GREATEST", "INSTR", "INTEGER", "LEAST", "LENGTH", "LOWER", "LPAD",
                "LTRIM", "MAX", "MIN", "MOD", "NO_DATA_FOUND", "NUMBER", "NVARCHAR2", "NVL", "NVL2", "PLS_INTEGER",
                "RAISE_APPLICATION_ERROR", "ROUND", "ROWID", "ROWNUM", "RPAD", "RTRIM", "SQLCODE", "SQLERRM",
                "SUBSTR", "SUM", "SYSDATE", "SYSTIMESTAMP", "TIMESTAMP", "TO_CHAR", "TO_DATE", "TO_NUMBER",
                "TOO_MANY_ROWS", "TRIM", "TRUNC", "UPPER", "VARCHAR2",
            }
        )  # fmt: skip
        _BLOCK_OPENERS = ("BEGIN", "IF", "LOOP", "CASE")
        _MAX_ARGUMENT_LOOKAHEAD = 5000

        def __init__(self, uri: str, text: str, tokens: list[Token]) -> None:
            self._uri = uri
            self._text = text
            self._tokens = tokens
            self._pos = 0
            self._declarations: list[Declaration] = []
            self._name_uses: list[NameUse] = []

        def run(self) -> SourceUnit:
            while not self._at_end():
                position = self._pos
                token = self._tokens[self._pos]
                if token.kind == TokenKind.UNIT_SEPARATOR:
                    self._advance()
                elif token.is_word("CREATE"):
                    self._parse_create()
                elif token.is_word("BEGIN", "DECLARE"):
                    self._parse_anonymous_block()
                elif token.is_word("EXEC", "EXECUTE"):
                    self._skip_line(collect_uses=True)
                elif token.is_word(*self._SQLPLUS_COMMANDS) or token.is_symbol("@", "@@"):
                    self._skip_line(collect_uses=False)
                else:
                    self._skip_to_semicolon(scope=None, stop_at_subprogram=False)
                if self._pos == position:
                    self._advance()
            return SourceUnit(self._uri, self._declarations, self._name_uses)

        # token navigation

        def _at_end(self) -> bool:
            return self._pos >= len(self._tokens)

        def _peek(self, offset: int = 0) -> Token | None:
            index = self._pos + offset
            return self._tokens[index] if index < len(self._tokens) else None

        def _peek_is_word(self, *words: str) -> bool:
            token = self._peek()
            return token is not None and token.is_word(*words)

        def _peek_is_symbol(self, *symbols: str) -> bool:
            token = self._peek()
            return token is not None and token.is_symbol(*symbols)

        def _previous_is_symbol(self, *symbols: str) -> bool:
            return self._pos > 0 and self._tokens[self._pos - 1].is_symbol(*symbols)

        def _advance(self) -> Token:
            token = self._tokens[self._pos]
            self._pos += 1
            return token

        def _accept_word(self, *words: str) -> Token | None:
            return self._advance() if self._peek_is_word(*words) else None

        def _accept_symbol(self, symbol: str) -> Token | None:
            return self._advance() if self._peek_is_symbol(symbol) else None

        def _accept_identifier(self) -> Token | None:
            token = self._peek()
            return self._advance() if token is not None and token.is_identifier() else None

        def _last_consumed(self) -> Token:
            return self._tokens[self._pos - 1]

        # declarations

        def _declare(self, kind: DeclarationKind, name: Token, start: Token, container: Declaration | None, is_symbol: bool) -> Declaration:
            declaration = Declaration(
                kind=kind,
                name=name.key if name.kind == TokenKind.QUOTED_IDENTIFIER else name.text,
                key=name.key,
                uri=self._uri,
                name_range=name.range,
                range=TextRange(start.range.start, name.range.end),
                header="",
                is_symbol=is_symbol,
            )
            if container is None:
                self._declarations.append(declaration)
            else:
                container.add_child(declaration)
            return declaration

        def _declare_anonymous_block(self, start: Token, container: Declaration | None) -> Declaration:
            """Creates the scope of an anonymous block, which is not part of the declaration tree"""
            return Declaration(
                kind=DeclarationKind.ANONYMOUS_BLOCK,
                name="",
                key="",
                uri=self._uri,
                name_range=start.range,
                range=start.range,
                header="",
                is_symbol=False,
                parent=container,
            )

        def _complete(self, declaration: Declaration, start: Token, header_end: Token | None) -> None:
            """
            Sets the range of the declaration (ending at the last consumed token) and its header (ending before
            ``header_end`` or, if it is None, at the last consumed token).
            """
            last = self._last_consumed()
            declaration.range = TextRange(start.range.start, last.range.end)
            header_end_offset = header_end.start_offset if header_end is not None else last.end_offset
            declaration.header = " ".join(self._text[start.start_offset : header_end_offset].split())

        # compilation units

        def _parse_create(self) -> None:
            start = self._advance()
            if self._accept_word("OR"):
                self._accept_word("REPLACE")
            self._accept_word("EDITIONABLE", "NONEDITIONABLE")
            if self._accept_word("PACKAGE"):
                self._parse_package(start, is_body=self._accept_word("BODY") is not None)
            elif self._peek_is_word("PROCEDURE", "FUNCTION"):
                self._parse_subprogram(container=None, start=start)
            elif self._accept_word("TRIGGER"):
                self._parse_trigger(start)
            else:
                self._skip_to_semicolon(scope=None, stop_at_subprogram=False)

        def _parse_object_name(self) -> Token | None:
            """Consumes a possibly schema-qualified object name, returning the token of the name proper"""
            name = self._accept_identifier()
            if name is not None and self._peek_is_symbol("."):
                following = self._peek(1)
                if following is not None and following.is_identifier():
                    self._advance()
                    return self._advance()
            return name

        def _parse_package(self, start: Token, is_body: bool) -> None:
            name = self._parse_object_name()
            if name is None:
                self._skip_to_semicolon(scope=None, stop_at_subprogram=False)
                return
            kind = DeclarationKind.PACKAGE_BODY if is_body else DeclarationKind.PACKAGE_SPEC
            package = self._declare(kind, name, start, container=None, is_symbol=True)
            package.is_implementation = is_body

            header_end = self._skip_to_header_end()
            if header_end is not None:
                self._parse_declarative_section(package, local=False)
                if self._accept_word("BEGIN"):
                    self._scan_block(package)
                elif self._accept_word("END"):
                    self._finish_end()
            self._complete(package, start, header_end)

        def _parse_subprogram(self, container: Declaration | None, start: Token) -> None:
            keyword = self._advance()
            name = self._parse_object_name()
            if name is None:
                self._skip_to_semicolon(container)
                return
            kind = DeclarationKind.PROCEDURE if keyword.is_word("PROCEDURE") else DeclarationKind.FUNCTION
            subprogram = self._declare(kind, name, start, container, is_symbol=True)
            subprogram.parameters = self._parse_parameters(subprogram) if self._peek_is_symbol("(") else ParameterSignature((), 0)

            header_end = self._scan_subprogram_header(subprogram)
            if header_end is not None and header_end.is_word("IS", "AS"):
                subprogram.is_implementation = True
                self._parse_subprogram_body(subprogram)
            self._complete(subprogram, start, header_end)

        def _parse_subprogram_body(self, subprogram: Declaration) -> None:
            if self._peek_is_word("LANGUAGE", "EXTERNAL"):
                self._skip_to_semicolon(subprogram)
                return
            self._parse_declarative_section(subprogram, local=True)
            if self._accept_word("BEGIN"):
                self._scan_block(subprogram)

        def _parse_trigger(self, start: Token) -> None:
            name = self._parse_object_name()
            if name is None:
                self._skip_to_semicolon(scope=None, stop_at_subprogram=False)
                return
            trigger = self._declare(DeclarationKind.TRIGGER, name, start, container=None, is_symbol=True)
            trigger.is_implementation = True

            header_end: Token | None = None
            while not self._at_end():
                token = self._tokens[self._pos]
                if token.kind == TokenKind.UNIT_SEPARATOR:
                    break
                if token.is_word("DECLARE"):
                    header_end = self._advance()
                    self._parse_declarative_section(trigger, local=True)
                    if self._accept_word("BEGIN"):
                        self._scan_block(trigger)
                    break
                if token.is_word("BEGIN"):
                    header_end = self._advance()
                    self._scan_block(trigger)
                    break
                if token.is_word("COMPOUND"):
                    header_end = self._advance()
                    self._accept_word("TRIGGER")
                    self._scan_block(trigger)
                    break
                if token.is_word("CALL"):
                    header_end = token
                    self._skip_to_semicolon(trigger)
                    break
                if not self._collect_name_use(trigger):
                    self._advance()
            self._complete(trigger, start, header_end)

        def _parse_anonymous_block(self) -> None:
            start = self._advance()
            block = self._declare_anonymous_block(start, container=None)
            if start.is_word("DECLARE"):
                self._parse_declarative_section(block, local=True)
                if not self._accept_word("BEGIN"):
                    return
            self._scan_block(block)

        # declarative sections

        def _parse_declarative_section(self, container: Declaration, local: bool) -> None:
            """
            Parses declarations up to (excluding) the ``BEGIN`` or ``END`` keyword that ends the section.

            :param container: the declaration owning the section
            :param local: whether the section belongs to a subprogram or block, whose items (except nested
                subprograms) are not reported as symbols
            """
            while not self._at_end():
                position = self._pos
                token = self._tokens[self._pos]
                if token.kind == TokenKind.UNIT_SEPARATOR or token.is_word("BEGIN", "END", "CREATE"):
                    return
                if token.is_word("PROCEDURE", "FUNCTION"):
                    self._parse_subprogram(container, start=token)
                elif token.is_word("TYPE", "SUBTYPE"):
                    self._parse_type(container, local)
                elif token.is_word("CURSOR"):
                    self._parse_cursor(container, local)
                elif token.is_word("PRAGMA"):
                    self._skip_to_semicolon(container)
                elif token.is_identifier():
                    self._parse_variable(container, local)
                if self._pos == position:
                    self._advance()

        def _parse_type(self, container: Declaration, local: bool) -> None:
            start = self._advance()
            name = self._accept_identifier()
            if name is None:
                self._skip_to_semicolon(container)
                return
            declaration = self._declare(DeclarationKind.TYPE, name, start, container, is_symbol=not local)
            following = self._peek(1)
            is_record = self._peek_is_word("IS") and following is not None and following.is_word("RECORD")
            self._skip_to_semicolon(container, skip_field_names=is_record)
            self._complete(declaration, start, header_end=None)

        def _parse_cursor(self, container: Declaration, local: bool) -> None:
            start = self._advance()
            name = self._accept_identifier()
            if name is None:
                self._skip_to_semicolon(container)
                return
            cursor = self._declare(DeclarationKind.CURSOR, name, start, container, is_symbol=not local)
            if self._peek_is_symbol("("):
                cursor.parameters = self._parse_parameters(cursor)
            self._skip_to_semicolon(cursor)
            self._complete(cursor, start, header_end=None)

        def _parse_variable(self, container: Declaration, local: bool) -> None:
            name = self._advance()
            if name.kind == TokenKind.WORD and name.key in self._NON_REFERENCE_WORDS:
                # a keyword cannot start a declaration: the section is malformed
                self._skip_to_semicolon(container)
                return
            if self._peek_is_word("EXCEPTION"):
                kind = DeclarationKind.EXCEPTION
            elif self._peek_is_word("CONSTANT"):
                kind = DeclarationKind.CONSTANT
            else:
                kind = DeclarationKind.VARIABLE
            declaration = self._declare(kind, name, name, container, is_symbol=not local)
            self._skip_to_semicolon(container)
            self._complete(declaration, name, header_end=None)

        def _parse_parameters(self, owner: Declaration) -> ParameterSignature:
            """Parses a parenthesised parameter list (the current token being the opening parenthesis)"""
            self._advance()
            names: list[str] = []
            optional_count = 0
            while not self._at_end():
                token = self._tokens[self._pos]
                if token.kind == TokenKind.UNIT_SEPARATOR:
                    break
                if token.is_symbol(")"):
                    self._advance()
                    break
                if not token.is_identifier():
                    self._advance()
                    continue
                name = self._advance()
                parameter = self._declare(DeclarationKind.PARAMETER, name, name, owner, is_symbol=False)
                names.append(name.key)
                if self._skip_parameter_remainder(owner):
                    optional_count += 1
                self._complete(parameter, name, header_end=None)
            return ParameterSignature(tuple(names), optional_count)

        def _skip_parameter_remainder(self, owner: Declaration) -> bool:
            """
            Consumes the mode, type and default of a parameter, up to (excluding) the ``,`` or ``)`` that ends it.

            :return: whether the parameter has a default value
            """
            depth = 0
            has_default = False
            while not self._at_end():
                token = self._tokens[self._pos]
                if token.kind == TokenKind.UNIT_SEPARATOR or (depth == 0 and token.is_symbol(",", ")")):
                    break
                if token.is_symbol("("):
                    depth += 1
                elif token.is_symbol(")"):
                    depth -= 1
                elif depth == 0 and (token.is_word("DEFAULT") or token.is_symbol(":=")):
                    has_default = True
                if not self._collect_name_use(owner):
                    self._advance()
            return has_default

        def _scan_subprogram_header(self, subprogram: Declaration) -> Token | None:
            """
            Consumes the remainder of a subprogram header (return type and modifiers) including the terminating
            token, which is returned: ``;`` for a declaration, ``IS``/``AS`` for an implementation.
            Returns None (without consuming the offending token) if the header is malformed.
            """
            depth = 0
            while not self._at_end():
                token = self._tokens[self._pos]
                if token.kind == TokenKind.UNIT_SEPARATOR:
                    return None
                if depth == 0:
                    if token.is_symbol(";") or token.is_word("IS", "AS"):
                        return self._advance()
                    if token.is_word("PROCEDURE", "FUNCTION", "BEGIN", "END", "CREATE"):
                        return None
                if token.is_symbol("("):
                    depth += 1
                elif token.is_symbol(")"):
                    depth = max(0, depth - 1)
                if not self._collect_name_use(subprogram):
                    self._advance()
            return None

        def _skip_to_header_end(self) -> Token | None:
            """Consumes a unit header up to and including the ``IS``/``AS`` keyword ending it, which is returned"""
            depth = 0
            while not self._at_end():
                token = self._tokens[self._pos]
                if token.kind == TokenKind.UNIT_SEPARATOR or (depth == 0 and token.is_symbol(";")):
                    return None
                self._advance()
                if token.is_symbol("("):
                    depth += 1
                elif token.is_symbol(")"):
                    depth = max(0, depth - 1)
                elif depth == 0 and token.is_word("IS", "AS"):
                    return token
            return None

        # statements and skipping

        def _skip_to_semicolon(self, scope: Declaration | None, stop_at_subprogram: bool = True, skip_field_names: bool = False) -> None:
            """
            Consumes tokens up to and including the next ``;`` at parenthesis depth 0, collecting name uses.

            :param scope: the scope of the name uses
            :param stop_at_subprogram: whether to stop (without consuming) at a ``procedure``/``function`` keyword,
                which indicates a missing semicolon
            :param skip_field_names: whether the identifiers starting the elements of the parenthesised list are
                field names (of a record type) rather than name uses
            """
            depth = 0
            while not self._at_end():
                token = self._tokens[self._pos]
                if token.kind == TokenKind.UNIT_SEPARATOR:
                    return
                if depth == 0:
                    if token.is_symbol(";"):
                        self._advance()
                        return
                    if stop_at_subprogram and self._at_subprogram_start():
                        return
                if token.is_symbol("("):
                    depth += 1
                elif token.is_symbol(")"):
                    depth = max(0, depth - 1)
                elif skip_field_names and depth == 1 and token.is_identifier() and self._previous_is_symbol("(", ","):
                    self._advance()
                    continue
                if not self._collect_name_use(scope):
                    self._advance()

        def _at_subprogram_start(self) -> bool:
            """
            :return: whether the current token is a ``procedure``/``function`` keyword introducing a subprogram rather
                than a name (e.g. a column named ``procedure`` in a select list)
            """
            if not self._tokens[self._pos].is_word("PROCEDURE", "FUNCTION") or self._previous_is_symbol(".", ",", "("):
                return False
            name = self._peek(1)
            return name is not None and name.is_identifier() and not (name.kind == TokenKind.WORD and name.key in self._NON_REFERENCE_WORDS)

        def _skip_line(self, collect_uses: bool) -> None:
            line = self._advance().line
            while not self._at_end() and self._tokens[self._pos].line == line:
                if not (collect_uses and self._collect_name_use(None)):
                    self._advance()

        def _scan_block(self, scope: Declaration) -> None:
            """
            Consumes the statements of a block whose opening keyword has been consumed, up to and including the
            matching ``END`` with its optional label and semicolon, collecting name uses.
            Stops early (without consuming) at a unit separator or at a ``procedure``/``function``/``create`` keyword
            starting a statement, which indicates a missing ``END``. Elsewhere, these words are names (e.g. columns).
            """
            depth = 1
            while not self._at_end():
                token = self._tokens[self._pos]
                if token.kind == TokenKind.UNIT_SEPARATOR:
                    return
                if token.is_word("PROCEDURE", "FUNCTION", "CREATE") and self._previous_is_symbol(";"):
                    return
                if token.is_word("END"):
                    self._advance()
                    self._accept_word("IF", "LOOP", "CASE")
                    depth -= 1
                    if depth == 0:
                        self._finish_end()
                        return
                    continue
                if token.is_word(*self._BLOCK_OPENERS):
                    self._advance()
                    depth += 1
                    continue
                if token.is_word("DECLARE"):
                    block = self._declare_anonymous_block(self._advance(), container=scope)
                    self._parse_declarative_section(block, local=True)
                    if self._accept_word("BEGIN"):
                        self._scan_block(block)
                    continue
                if self._at_for_loop():
                    self._scan_for_loop(scope)
                    continue
                if not self._collect_name_use(scope):
                    self._advance()

        def _at_for_loop(self) -> bool:
            """:return: whether the current token starts a ``for <index> in ... loop`` statement"""
            index = self._peek(1)
            keyword = self._peek(2)
            return (
                self._peek_is_word("FOR") and index is not None and index.is_identifier() and keyword is not None and keyword.is_word("IN")
            )

        def _scan_for_loop(self, scope: Declaration) -> None:
            """
            Consumes a ``for`` loop up to and including its ``end loop``, scanning the loop's statements in a scope
            that declares the loop index, which shadows equally named outer declarations.
            Stops after the loop header if it is not followed by ``loop``.
            """
            block = self._declare_anonymous_block(self._advance(), container=scope)
            index = self._advance()
            self._complete(self._declare(DeclarationKind.VARIABLE, index, index, block, is_symbol=False), index, header_end=None)

            # the loop bounds or cursor belong to the enclosing scope
            depth = 0
            while not self._at_end():
                token = self._tokens[self._pos]
                if token.kind == TokenKind.UNIT_SEPARATOR or (depth == 0 and token.is_symbol(";")):
                    return
                if depth == 0 and token.is_word("LOOP"):
                    self._advance()
                    self._scan_block(block)
                    return
                if token.is_symbol("("):
                    depth += 1
                elif token.is_symbol(")"):
                    depth = max(0, depth - 1)
                if not self._collect_name_use(scope):
                    self._advance()

        def _finish_end(self) -> None:
            """Consumes the optional label and the semicolon following the ``END`` keyword of a unit or subprogram"""
            token = self._peek()
            if token is not None and token.is_identifier():
                self._advance()
            self._accept_symbol(";")

        # name uses

        def _collect_name_use(self, scope: Declaration | None) -> bool:
            """
            Consumes and records a name use starting at the current token, if the token starts one.

            :param scope: the scope of the name use
            :return: whether tokens were consumed
            """
            token = self._peek()
            if token is None or not token.is_identifier():
                return False

            # member access on an expression, attribute (e.g. %type) or bind variable (e.g. :new)
            if self._previous_is_symbol(".", "%", ":"):
                return False
            following = self._peek(1)
            continues_chain = following is not None and following.is_symbol(".")
            if token.kind == TokenKind.WORD and token.key in self._NON_REFERENCE_WORDS and not continues_chain:
                return False

            # consume the chain of qualified identifiers
            segments = [self._advance()]
            while self._peek_is_symbol("."):
                following = self._peek(1)
                if following is None or not following.is_identifier():
                    break
                self._advance()
                segments.append(self._advance())

            # the formal parameter name of a named argument (``name => value``) is not a use in this scope
            if self._peek_is_symbol("=>"):
                return True

            self._name_uses.append(
                NameUse(
                    uri=self._uri,
                    segments=tuple(NameSegment(s.key, s.line, s.column, s.column + len(s.text)) for s in segments),
                    scope=scope,
                    argument_count=self._count_call_arguments(),
                )
            )
            return True

        def _count_call_arguments(self) -> int:
            """:return: the number of arguments in the argument list at the current token (0 if there is none)"""
            if not self._peek_is_symbol("("):
                return 0
            depth = 0
            commas = 0
            has_argument = False
            end = min(len(self._tokens), self._pos + self._MAX_ARGUMENT_LOOKAHEAD)
            for token in self._tokens[self._pos : end]:
                if token.kind == TokenKind.UNIT_SEPARATOR:
                    break
                if token.is_symbol("("):
                    depth += 1
                    has_argument = has_argument or depth > 1
                elif token.is_symbol(")"):
                    depth -= 1
                    if depth == 0:
                        break
                else:
                    has_argument = True
                    if depth == 1 and token.is_symbol(","):
                        commas += 1
            return commas + 1 if has_argument else 0
