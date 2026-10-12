"""
Integration tests for the PL/SQL language server with additional file extensions configured.
"""

from collections.abc import Iterator

import pytest

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import LanguageServerId
from solidlsp.ls_types import SymbolKind
from test.conftest import start_ls_context
from test.solidlsp.plsql.source_positions import SourceLine, find_position

pytestmark = [pytest.mark.plsql]


@pytest.fixture(scope="module")
def language_server() -> Iterator[SolidLanguageServer]:
    with start_ls_context(LanguageServerId.PLSQL, ls_specific_settings={LanguageServerId.PLSQL: {"file_extensions": [".trigger"]}}) as ls:
        yield ls


def test_configured_extension_is_a_source_file_extension(language_server: SolidLanguageServer) -> None:
    assert language_server.get_source_fn_matcher().is_relevant_filename("triggers.trigger")


def test_triggers_are_reported_as_symbols(language_server: SolidLanguageServer) -> None:
    _, roots = language_server.request_document_symbols("triggers.trigger").get_all_symbols_and_roots()

    assert [(root["name"], root["kind"]) for root in roots] == [
        ("Orders_Audit_Trg", SymbolKind.Event),
        ("Order_Lines_Check_Trg", SymbolKind.Event),
    ]


def test_references_include_files_with_configured_extension(language_server: SolidLanguageServer) -> None:
    position = find_position("order_mgmt.pks", "Read_Order(p_order_id in number")
    locations = language_server.request_references("order_mgmt.pks", position.line, position.column)

    assert {SourceLine.from_location(location) for location in locations} == {
        SourceLine.of("order_mgmt.pkb", "Read_Order(p_order_id, l_order)"),
        SourceLine.of("shipment.pkb", "Read_Order(p_order_id, l_order)"),
        SourceLine.of("triggers.trigger", "Read_Order(:new.order_id"),
    }
