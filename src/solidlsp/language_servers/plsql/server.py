# SPDX-License-Identifier: MIT
"""
PL/SQL language server communicating via stdio.

Run with ``python -m solidlsp.language_servers.plsql.server``.
"""

import logging
import os
import pathlib
import sys
from typing import Any

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from solidlsp.language_servers.plsql.name_resolver import NameResolver
from solidlsp.language_servers.plsql.parser import PlsqlParser
from solidlsp.language_servers.plsql.syntax import Declaration, DeclarationKind, SourceLocation, SourceUnit, TextPosition, TextRange
from solidlsp.language_servers.plsql.workspace_index import WorkspaceIndex

log = logging.getLogger(__name__)


class PlsqlServer(LanguageServer):
    """
    Language server for Oracle PL/SQL, answering document symbol, definition, references, hover and workspace symbol
    requests from an in-memory index of all PL/SQL sources in the workspace folders.

    Initialization options:

      * ``fileExtensions``: the file extensions of PL/SQL sources (default: ``.pks``, ``.pkb``, ``.pck``)
      * ``encoding``: the encoding of the source files (default: ``utf-8``)
    """

    INDEX_READY_MESSAGE = "PL/SQL workspace index ready"
    """the prefix of the log message that is sent to the client once the workspace has been indexed"""

    _DEFAULT_FILE_EXTENSIONS = (".pks", ".pkb", ".pck")
    _IGNORED_DIRECTORY_NAMES = frozenset({"node_modules", "__pycache__"})
    _SYMBOL_KINDS = {
        DeclarationKind.PACKAGE_SPEC: lsp.SymbolKind.Module,
        DeclarationKind.PACKAGE_BODY: lsp.SymbolKind.Module,
        DeclarationKind.PROCEDURE: lsp.SymbolKind.Function,
        DeclarationKind.FUNCTION: lsp.SymbolKind.Function,
        DeclarationKind.TRIGGER: lsp.SymbolKind.Event,
        DeclarationKind.TYPE: lsp.SymbolKind.Struct,
        DeclarationKind.CURSOR: lsp.SymbolKind.Variable,
        DeclarationKind.VARIABLE: lsp.SymbolKind.Variable,
        DeclarationKind.EXCEPTION: lsp.SymbolKind.Variable,
        DeclarationKind.CONSTANT: lsp.SymbolKind.Constant,
        DeclarationKind.PARAMETER: lsp.SymbolKind.Variable,
        DeclarationKind.ANONYMOUS_BLOCK: lsp.SymbolKind.Namespace,
    }

    def __init__(self) -> None:
        super().__init__("plsql-lsp", "0.1.0")
        self._file_extensions: tuple[str, ...] = self._DEFAULT_FILE_EXTENSIONS
        self._encoding = "utf-8"
        self._index = WorkspaceIndex(PlsqlParser())
        self._resolver = NameResolver(self._index)
        self._register_features()

    def _register_features(self) -> None:
        @self.feature(lsp.INITIALIZE)
        def initialize(params: lsp.InitializeParams) -> None:
            self._configure(params.initialization_options)

        @self.feature(lsp.INITIALIZED)
        def initialized(params: lsp.InitializedParams) -> None:
            file_count = self._index_workspace()
            self.window_log_message(
                lsp.LogMessageParams(type=lsp.MessageType.Info, message=f"{self.INDEX_READY_MESSAGE}: {file_count} files")
            )

        @self.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
        def did_open(params: lsp.DidOpenTextDocumentParams) -> None:
            self._index.update(self._canonical_uri(params.text_document.uri), params.text_document.text)

        @self.feature(lsp.TEXT_DOCUMENT_DID_CHANGE)
        def did_change(params: lsp.DidChangeTextDocumentParams) -> None:
            document = self.workspace.get_text_document(params.text_document.uri)
            self._index.update(self._canonical_uri(params.text_document.uri), document.source)

        @self.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
        def did_close(params: lsp.DidCloseTextDocumentParams) -> None:
            path = to_fs_path(params.text_document.uri)
            if path is not None:
                self._index_file(path)

        @self.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
        def document_symbol(params: lsp.DocumentSymbolParams) -> list[lsp.DocumentSymbol]:
            unit = self._get_unit(params.text_document.uri)
            return [self._to_document_symbol(declaration) for declaration in unit.declarations if declaration.is_symbol]

        @self.feature(lsp.TEXT_DOCUMENT_DEFINITION)
        def definition(params: lsp.DefinitionParams) -> list[lsp.Location]:
            uri = self._prepare(params.text_document.uri)
            definitions = self._resolver.find_definitions(uri, self._to_text_position(params.position))
            return [self._to_location(SourceLocation(d.uri, d.name_range)) for d in definitions]

        @self.feature(lsp.TEXT_DOCUMENT_REFERENCES)
        def references(params: lsp.ReferenceParams) -> list[lsp.Location]:
            uri = self._prepare(params.text_document.uri)
            locations = self._resolver.find_references(
                uri, self._to_text_position(params.position), include_declaration=params.context.include_declaration
            )
            return [self._to_location(location) for location in locations]

        @self.feature(lsp.TEXT_DOCUMENT_HOVER)
        def hover(params: lsp.HoverParams) -> lsp.Hover | None:
            uri = self._prepare(params.text_document.uri)
            declarations = self._resolver.find_declarations(uri, self._to_text_position(params.position))
            if not declarations:
                return None
            return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=f"```plsql\n{declarations[0].header}\n```"))

        @self.feature(lsp.WORKSPACE_SYMBOL)
        def workspace_symbol(params: lsp.WorkspaceSymbolParams) -> list[lsp.SymbolInformation]:
            query = params.query.lower()
            return [
                lsp.SymbolInformation(
                    name=declaration.name,
                    kind=self._SYMBOL_KINDS[declaration.kind],
                    location=self._to_location(SourceLocation(declaration.uri, declaration.name_range)),
                    container_name=declaration.parent.name if declaration.parent is not None else None,
                )
                for unit in self._index.iter_units()
                for declaration in unit.iter_declarations()
                if declaration.is_symbol and query in declaration.name.lower()
            ]

    def _configure(self, options: Any) -> None:
        if not isinstance(options, dict):
            return
        file_extensions = options.get("fileExtensions")
        if isinstance(file_extensions, list) and file_extensions:
            self._file_extensions = tuple(str(extension).lower() for extension in file_extensions)
        encoding = options.get("encoding")
        if isinstance(encoding, str) and encoding:
            self._encoding = encoding

    # indexing

    def _index_workspace(self) -> int:
        """
        Indexes all PL/SQL sources below the workspace folders.

        :return: the number of indexed files
        """
        file_count = 0
        for root in self._get_workspace_roots():
            for directory, subdirectory_names, file_names in os.walk(root):
                subdirectory_names[:] = [
                    name for name in subdirectory_names if not name.startswith(".") and name not in self._IGNORED_DIRECTORY_NAMES
                ]
                for file_name in file_names:
                    if file_name.lower().endswith(self._file_extensions):
                        self._index_file(os.path.join(directory, file_name))
                        file_count += 1
        return file_count

    def _get_workspace_roots(self) -> list[str]:
        roots = [to_fs_path(folder.uri) for folder in self.workspace.folders.values()]
        if not roots:
            roots = [self.workspace.root_path]
        return [root for root in roots if root is not None]

    def _index_file(self, path: str) -> None:
        uri = self._uri_for_path(path)
        try:
            with open(path, encoding=self._encoding, errors="replace", newline="") as file:
                text = file.read()
        except OSError as e:
            log.warning("Cannot read %s: %s", path, e)
            self._index.remove(uri)
            return
        try:
            self._index.update(uri, text)
        except Exception:
            # a single unparseable file must not disable the server
            log.exception("Failed to index %s", path)

    def _get_unit(self, uri: str) -> SourceUnit:
        """
        :param uri: a document URI as sent by the client
        :return: the indexed parse result of the document, indexing it first if necessary
        """
        unit = self._index.get_unit(self._canonical_uri(uri))
        if unit is None:
            path = to_fs_path(uri)
            if path is not None:
                self._index_file(path)
            unit = self._index.get_unit(self._canonical_uri(uri))
        return unit if unit is not None else SourceUnit(uri, [], [])

    def _prepare(self, uri: str) -> str:
        """
        Ensures that the given document is indexed.

        :param uri: a document URI as sent by the client
        :return: the canonical URI under which the document is indexed
        """
        self._get_unit(uri)
        return self._canonical_uri(uri)

    # URIs

    @staticmethod
    def _uri_for_path(path: str) -> str:
        """:return: the canonical URI of the given file path (absolute, with an upper-case drive letter)"""
        drive, rest = os.path.splitdrive(os.path.abspath(path))
        return pathlib.Path(drive.upper() + rest).as_uri()

    def _canonical_uri(self, uri: str) -> str:
        path = to_fs_path(uri)
        return uri if path is None else self._uri_for_path(path)

    # conversion to LSP types

    @staticmethod
    def _to_lsp_range(text_range: TextRange) -> lsp.Range:
        return lsp.Range(
            start=lsp.Position(line=text_range.start.line, character=text_range.start.character),
            end=lsp.Position(line=text_range.end.line, character=text_range.end.character),
        )

    @staticmethod
    def _to_text_position(position: lsp.Position) -> TextPosition:
        return TextPosition(position.line, position.character)

    def _to_location(self, location: SourceLocation) -> lsp.Location:
        return lsp.Location(uri=location.uri, range=self._to_lsp_range(location.range))

    def _to_document_symbol(self, declaration: Declaration) -> lsp.DocumentSymbol:
        return lsp.DocumentSymbol(
            name=declaration.name,
            kind=self._SYMBOL_KINDS[declaration.kind],
            detail=declaration.kind.value,
            range=self._to_lsp_range(declaration.range),
            selection_range=self._to_lsp_range(declaration.name_range),
            children=[self._to_document_symbol(child) for child in declaration.children if child.is_symbol],
        )


def main() -> None:
    """
    Runs the PL/SQL language server on stdin/stdout.
    """
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    PlsqlServer().start_io()


if __name__ == "__main__":
    main()
