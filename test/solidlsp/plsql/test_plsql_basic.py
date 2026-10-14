"""
Integration tests for the PL/SQL language server, using the default file extensions.
"""

import pytest

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import LanguageServerId
from solidlsp.ls_types import SymbolKind, UnifiedSymbolInformation
from test.solidlsp.plsql.source_positions import SourceLine, find_position

pytestmark = [pytest.mark.plsql]


def _roots(language_server: SolidLanguageServer, relative_path: str) -> list[UnifiedSymbolInformation]:
    _, roots = language_server.request_document_symbols(relative_path).get_all_symbols_and_roots()
    return roots


def _child_names(symbol: UnifiedSymbolInformation) -> list[str]:
    return [child["name"] for child in symbol["children"]]


def _child(symbol: UnifiedSymbolInformation, name: str) -> UnifiedSymbolInformation:
    return next(child for child in symbol["children"] if child["name"] == name)


@pytest.mark.parametrize("language_server", [LanguageServerId.PLSQL], indirect=True)
def test_ls_is_running(language_server: SolidLanguageServer) -> None:
    assert language_server.is_running()


@pytest.mark.parametrize("language_server", [LanguageServerId.PLSQL], indirect=True)
class TestDocumentSymbols:
    def test_package_spec_declares_members(self, language_server: SolidLanguageServer) -> None:
        roots = _roots(language_server, "order_mgmt.pks")

        assert [(root["name"], root["kind"]) for root in roots] == [("Order_Mgmt", SymbolKind.Module)]
        assert sorted((child["name"], child["kind"]) for child in roots[0]["children"]) == sorted(
            [
                ("c_max_lines", SymbolKind.Constant),
                ("e_order_locked", SymbolKind.Variable),
                ("t_order_rec", SymbolKind.Struct),
                ("t_order_tab", SymbolKind.Struct),
                ("Read_Order", SymbolKind.Function),
                ("Add_Line", SymbolKind.Function),
                ("Add_Line", SymbolKind.Function),
                ("Close_Order", SymbolKind.Function),
            ]
        )

    def test_package_body_declares_implementations_and_nested_subprograms(self, language_server: SolidLanguageServer) -> None:
        roots = _roots(language_server, "order_mgmt.pkb")

        assert [root["name"] for root in roots] == ["Order_Mgmt"]
        assert sorted(_child_names(roots[0])) == sorted(["g_last_order", "c_lines", "Read_Order", "Add_Line", "Add_Line", "Close_Order"])
        assert _child_names(_child(roots[0], "Close_Order")) == ["Mark_Closed"]

    def test_subprogram_range_spans_whole_implementation(self, language_server: SolidLanguageServer) -> None:
        close_order = _child(_roots(language_server, "order_mgmt.pkb")[0], "Close_Order")

        assert close_order["range"]["start"]["line"] == find_position("order_mgmt.pkb", "procedure Close_Order").line
        assert close_order["range"]["end"]["line"] == find_position("order_mgmt.pkb", "end Close_Order;").line

    def test_file_with_several_units_reports_each_unit(self, language_server: SolidLanguageServer) -> None:
        roots = _roots(language_server, "audit_log.pck")

        assert [(root["name"], root["kind"]) for root in roots] == [("Audit_Log", SymbolKind.Module), ("Audit_Log", SymbolKind.Module)]
        assert sorted(_child_names(roots[1])) == sorted(["g_count", "Write_Entry", "Entry_Count", "Reset"])
        entry_count = _child(roots[1], "Entry_Count")
        assert entry_count["range"]["end"]["line"] == find_position("audit_log.pck", "end Entry_Count;").line

    def test_malformed_unit_does_not_hide_following_units(self, language_server: SolidLanguageServer) -> None:
        roots = _roots(language_server, "legacy_broken.pck")

        assert [root["name"] for root in roots] == ["Legacy_Broken", "Recovered_Pkg"]
        assert _child_names(roots[1]) == ["Still_Found"]

    def test_symbols_reflect_unsaved_edits(self, language_server: SolidLanguageServer) -> None:
        insert_line = find_position("audit_log.pck", "end Audit_Log;", occurrence=1).line

        with language_server.open_file("audit_log.pck"):
            end = language_server.insert_text_at_position(
                "audit_log.pck", insert_line, 0, "  procedure Purge is begin null; end Purge;\n\n"
            )
            try:
                assert "Purge" in _child_names(_roots(language_server, "audit_log.pck")[1])
            finally:
                language_server.delete_text_between_positions("audit_log.pck", {"line": insert_line, "character": 0}, end)


@pytest.mark.parametrize("language_server", [LanguageServerId.PLSQL], indirect=True)
class TestNavigation:
    @staticmethod
    def _definitions(language_server: SolidLanguageServer, relative_path: str, needle: str) -> set[SourceLine]:
        position = find_position(relative_path, needle)
        return {
            SourceLine.from_location(location)
            for location in language_server.request_definition(relative_path, position.line, position.column)
        }

    @staticmethod
    def _references(language_server: SolidLanguageServer, relative_path: str, needle: str) -> set[SourceLine]:
        position = find_position(relative_path, needle)
        return {
            SourceLine.from_location(location)
            for location in language_server.request_references(relative_path, position.line, position.column)
        }

    def test_definition_of_qualified_call_is_body_implementation(self, language_server: SolidLanguageServer) -> None:
        assert self._definitions(language_server, "shipment.pkb", "Read_Order(p_order_id, l_order)") == {
            SourceLine.of("order_mgmt.pkb", "function Read_Order")
        }

    def test_definition_of_overloaded_call_matches_argument_count(self, language_server: SolidLanguageServer) -> None:
        assert self._definitions(language_server, "order_mgmt.pkb", "Add_Line(p_order_id, p_item, 1)") == {
            SourceLine.of("order_mgmt.pkb", "procedure Add_Line", occurrence=1)
        }
        assert self._definitions(language_server, "shipment.pkb", "Add_Line(p_order_id, 'SHIPPING')") == {
            SourceLine.of("order_mgmt.pkb", "procedure Add_Line", occurrence=0)
        }

    def test_definition_of_unqualified_spec_member_used_in_body(self, language_server: SolidLanguageServer) -> None:
        assert self._definitions(language_server, "order_mgmt.pkb", "c_max_lines then") == {
            SourceLine.of("order_mgmt.pks", "c_max_lines constant")
        }

    def test_definition_of_nested_subprogram_call(self, language_server: SolidLanguageServer) -> None:
        assert self._definitions(language_server, "order_mgmt.pkb", "Mark_Closed(p_order_id)") == {
            SourceLine.of("order_mgmt.pkb", "procedure Mark_Closed")
        }

    def test_references_across_files_are_shared_by_spec_and_body(self, language_server: SolidLanguageServer) -> None:
        expected = {
            SourceLine.of("order_mgmt.pkb", "Read_Order(p_order_id, l_order)"),
            SourceLine.of("shipment.pkb", "Read_Order(p_order_id, l_order)"),
        }
        assert self._references(language_server, "order_mgmt.pks", "Read_Order(p_order_id in number") == expected
        assert self._references(language_server, "order_mgmt.pkb", "Read_Order(p_order_id in number") == expected

    def test_references_distinguish_overloads(self, language_server: SolidLanguageServer) -> None:
        assert self._references(language_server, "order_mgmt.pkb", "Add_Line(p_order_id in number, p_item in varchar2, p_qty") == {
            SourceLine.of("order_mgmt.pkb", "Add_Line(p_order_id, p_item, 1)")
        }
        assert self._references(language_server, "order_mgmt.pks", "Add_Line(p_order_id in number, p_item in varchar2);") == {
            SourceLine.of("shipment.pkb", "Add_Line(p_order_id, 'SHIPPING')")
        }

    def test_references_within_file(self, language_server: SolidLanguageServer) -> None:
        assert self._references(language_server, "order_mgmt.pkb", "Mark_Closed(p_id in number)") == {
            SourceLine.of("order_mgmt.pkb", "Mark_Closed(p_order_id)")
        }

    def test_references_skip_shadowing_local_declarations(self, language_server: SolidLanguageServer) -> None:
        assert self._references(language_server, "audit_log.pck", "Entry_Count return number;") == {
            SourceLine.of("shipment.pkb", "Entry_Count > 100")
        }

    def test_referencing_symbols_are_enclosing_subprograms(self, language_server: SolidLanguageServer) -> None:
        position = find_position("audit_log.pck", "Write_Entry(p_action in varchar2, p_ref_id in number);")
        referencing = language_server.request_referencing_symbols("audit_log.pck", position.line, position.column)

        assert sorted(reference.symbol["name"] for reference in referencing) == ["Add_Line", "Close_Order"]

    def test_hover_shows_declaration_header(self, language_server: SolidLanguageServer) -> None:
        position = find_position("shipment.pkb", "Close_Order(p_order_id =>")
        hover = language_server.request_hover("shipment.pkb", position.line, position.column)

        assert hover is not None
        assert "procedure Close_Order(p_order_id in number, p_force in boolean default false)" in str(hover["contents"])

    def test_workspace_symbol_search(self, language_server: SolidLanguageServer) -> None:
        symbols = language_server.request_workspace_symbol("Close_Ord") or []

        assert {symbol["name"] for symbol in symbols} == {"Close_Order"}
