# SPDX-License-Identifier: MIT
"""
PL/SQL language server communicating via stdio.

Run with ``python -m solidlsp.language_servers.plsql.server``.
"""

import logging
import sys

from lsprotocol import types as lsp

from solidlsp.language_servers.indexing_server.server import IndexingLanguageServer
from solidlsp.language_servers.indexing_server.text import SourceLocation
from solidlsp.language_servers.plsql.name_resolver import NameResolver
from solidlsp.language_servers.plsql.parser import PlsqlParser
from solidlsp.language_servers.plsql.syntax import Declaration, DeclarationKind, SourceUnit
from solidlsp.language_servers.plsql.workspace_index import WorkspaceIndex


class PlsqlServer(IndexingLanguageServer[SourceUnit]):
    """
    Language server for Oracle PL/SQL, answering document symbol, definition, references, hover and workspace symbol
    requests from an in-memory index of all PL/SQL sources in the workspace folders
    (by default, files with the extensions ``.pks``, ``.pkb`` and ``.pck``).
    """

    INDEX_READY_MESSAGE = "PL/SQL workspace index ready"
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
        self._workspace_index = WorkspaceIndex(PlsqlParser())
        self._resolver = NameResolver(self._workspace_index)
        super().__init__("plsql-lsp", "0.1.0", self._workspace_index, (".pks", ".pkb", ".pck"))

    def _register_language_features(self) -> None:
        @self.feature(lsp.TEXT_DOCUMENT_DOCUMENT_SYMBOL)
        def document_symbol(params: lsp.DocumentSymbolParams) -> list[lsp.DocumentSymbol]:
            unit = self._get_unit(params.text_document.uri)
            if unit is None:
                return []
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
                for unit in self._workspace_index.iter_units()
                for declaration in unit.iter_declarations()
                if declaration.is_symbol and query in declaration.name.lower()
            ]

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
