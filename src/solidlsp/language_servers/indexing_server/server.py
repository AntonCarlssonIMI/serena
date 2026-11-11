# SPDX-License-Identifier: MIT
"""
Base class of pygls language servers that keep all sources of the workspace parsed in an in-memory index.
"""

import logging
import os
import pathlib
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Generic, TypeVar

from lsprotocol import types as lsp
from pygls.lsp.server import LanguageServer
from pygls.uris import to_fs_path

from solidlsp.language_servers.indexing_server.text import SourceLocation, TextPosition, TextRange

log = logging.getLogger(__name__)

TUnit = TypeVar("TUnit")


class SourceIndex(ABC, Generic[TUnit]):
    """
    The parse results of the sources of a workspace, keyed by document URI.
    """

    @abstractmethod
    def update(self, uri: str, text: str) -> TUnit:
        """
        Parses the given text and replaces the document's previous entry (if any).

        :param uri: the document's URI
        :param text: the document's text
        :return: the parse result
        """

    @abstractmethod
    def remove(self, uri: str) -> None:
        """
        :param uri: the URI of a document to remove from the index (no-op if it is not indexed)
        """

    @abstractmethod
    def get_unit(self, uri: str) -> TUnit | None:
        """
        :param uri: the URI of a document
        :return: the parse result of the document, if it is indexed
        """


class IndexingLanguageServer(LanguageServer, ABC, Generic[TUnit]):
    """
    Language server which indexes all sources below the workspace folders once the client is initialised and keeps the
    index in sync with the documents opened, changed and closed by the client.

    Initialization options:

      * ``fileExtensions``: the file extensions of the sources to index (case-insensitive)
      * ``encoding``: the encoding of the source files (default: ``utf-8``)
    """

    INDEX_READY_MESSAGE: ClassVar[str]
    """the prefix of the log message that is sent to the client once the workspace has been indexed"""

    _IGNORED_DIRECTORY_NAMES = frozenset({"node_modules", "__pycache__"})

    def __init__(self, name: str, version: str, index: SourceIndex[TUnit], default_file_extensions: tuple[str, ...]) -> None:
        """
        :param name: the server name reported to the client
        :param version: the server version reported to the client
        :param index: the index holding the parse results of the sources
        :param default_file_extensions: the file extensions of the sources to index unless configured otherwise
        """
        super().__init__(name, version)
        self._index = index
        self._file_extensions = default_file_extensions
        self._encoding = "utf-8"
        self._register_document_synchronisation()
        self._register_language_features()

    @abstractmethod
    def _register_language_features(self) -> None:
        """
        Registers the handlers of the language feature requests (document symbols, definitions, etc.).
        """

    def _register_document_synchronisation(self) -> None:
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
        Indexes all sources below the workspace folders.

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
            # a single unparsable file must not disable the server
            log.exception("Failed to index %s", path)

    def _get_unit(self, uri: str) -> TUnit | None:
        """
        :param uri: a document URI as sent by the client
        :return: the indexed parse result of the document, indexing it first if necessary; None if the document
            cannot be read
        """
        unit = self._index.get_unit(self._canonical_uri(uri))
        if unit is None:
            path = to_fs_path(uri)
            if path is not None:
                self._index_file(path)
            unit = self._index.get_unit(self._canonical_uri(uri))
        return unit

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
