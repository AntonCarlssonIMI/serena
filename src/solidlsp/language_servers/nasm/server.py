# SPDX-License-Identifier: MIT
"""
NASM language server communicating via stdio.

Run with ``python -m solidlsp.language_servers.nasm.server``.
"""

import logging
import sys

from lsprotocol import types as lsp
from pygls.exceptions import JsonRpcInvalidParams

from solidlsp.language_servers.indexing_server.server import IndexingLanguageServer
from solidlsp.language_servers.indexing_server.text import SourceLocation
from solidlsp.language_servers.nasm.name_resolver import NameResolver
from solidlsp.language_servers.nasm.parser import NasmParser
from solidlsp.language_servers.nasm.syntax import Declaration, DeclarationKind, SourceUnit
from solidlsp.language_servers.nasm.workspace_index import WorkspaceIndex


class NasmServer(IndexingLanguageServer[SourceUnit]):
    """
    Language server for NASM assembly, answering document symbol, definition, references, rename, hover and workspace
    symbol requests from an in-memory index of all NASM sources in the workspace folders
    (by default, files with the extensions ``.asm``, ``.nasm``, ``.inc`` and ``.mac``).
    """

    INDEX_READY_MESSAGE = "NASM workspace index ready"

    _SYMBOL_KINDS = {
        DeclarationKind.ROUTINE: lsp.SymbolKind.Function,
        DeclarationKind.DATA: lsp.SymbolKind.Variable,
        DeclarationKind.LOCAL_LABEL: lsp.SymbolKind.Key,
        DeclarationKind.MACRO: lsp.SymbolKind.Function,
        DeclarationKind.CONSTANT: lsp.SymbolKind.Constant,
        DeclarationKind.STRUCTURE: lsp.SymbolKind.Struct,
        DeclarationKind.FIELD: lsp.SymbolKind.Field,
    }

    def __init__(self) -> None:
        self._workspace_index = WorkspaceIndex(NasmParser())
        self._resolver = NameResolver(self._workspace_index)
        super().__init__("nasm-lsp", "0.1.0", self._workspace_index, (".asm", ".nasm", ".inc", ".mac"))

    def _register_language_features(self) -> None:
        @self.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
        def document_symbol(params: lsp.DocumentSymbolParams) -> list[lsp.DocumentSymbol]:
            unit = self._get_unit(params.text_document.uri)
            if unit is None:
                return []
            return [self._to_document_symbol(declaration) for declaration in unit.declarations]

        @self.feature(lsp.TEXT_DOCUMENT_DEFINITION)
        def definition(params: lsp.DefinitionParams) -> list[lsp.Location]:
            uri = self._prepare(params.text_document.uri)
            declarations = self._resolver.find_declarations(uri, self._to_text_position(params.position))
            return [self._to_location(SourceLocation(d.uri, d.name_range)) for d in declarations]

        @self.feature(lsp.TEXT_DOCUMENT_REFERENCES)
        def references(params: lsp.ReferenceParams) -> list[lsp.Location]:
            uri = self._prepare(params.text_document.uri)
            locations = self._resolver.find_references(
                uri, self._to_text_position(params.position), include_declaration=params.context.include_declaration
            )
            return [self._to_location(location) for location in locations]

        @self.feature(lsp.TEXT_DOCUMENT_RENAME)
        def rename(params: lsp.RenameParams) -> lsp.WorkspaceEdit:
            uri = self._prepare(params.text_document.uri)
            try:
                replacements = self._resolver.plan_rename(uri, self._to_text_position(params.position), params.new_name)
            except ValueError as e:
                raise JsonRpcInvalidParams(str(e)) from e
            changes: dict[str, list[lsp.TextEdit]] = {}
            for replacement in replacements:
                location = replacement.location
                changes.setdefault(location.uri, []).append(
                    lsp.TextEdit(range=self._to_lsp_range(location.range), new_text=replacement.new_text)
                )
            return lsp.WorkspaceEdit(changes=changes)

        @self.feature(lsp.TEXT_DOCUMENT_HOVER)
        def hover(params: lsp.HoverParams) -> lsp.Hover | None:
            uri = self._prepare(params.text_document.uri)
            declarations = self._resolver.find_declarations(uri, self._to_text_position(params.position))
            if not declarations:
                return None
            return lsp.Hover(contents=lsp.MarkupContent(kind=lsp.MarkupKind.Markdown, value=f"```nasm\n{declarations[0].header}\n```"))

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
                for unit in self._workspace_index.iter_units()
                for declaration in unit.iter_declarations()
                if declaration.kind != DeclarationKind.LOCAL_LABEL and query in declaration.name.lower()
            ]

    def _to_document_symbol(self, declaration: Declaration) -> lsp.DocumentSymbol:
        return lsp.DocumentSymbol(
            name=declaration.name,
            kind=self._SYMBOL_KINDS[declaration.kind],
            detail=declaration.kind.value,
            range=self._to_lsp_range(declaration.range),
            selection_range=self._to_lsp_range(declaration.name_range),
            children=[self._to_document_symbol(child) for child in declaration.children],
        )


def main() -> None:
    """
    Runs the NASM language server on stdin/stdout.
    """
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    NasmServer().start_io()


if __name__ == "__main__":
    main()
