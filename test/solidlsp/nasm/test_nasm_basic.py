"""
Integration tests for the NASM assembly language server.
"""

import pytest

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import LanguageServerId
from solidlsp.ls_types import SymbolKind, UnifiedSymbolInformation
from test.solidlsp.util.source_positions import SourceLine, TestRepoSources

pytestmark = [pytest.mark.nasm]

_SOURCES = TestRepoSources(LanguageServerId.NASM)


def _roots(language_server: SolidLanguageServer, relative_path: str) -> list[UnifiedSymbolInformation]:
    _, roots = language_server.request_document_symbols(relative_path).get_all_symbols_and_roots()
    return roots


def _root(language_server: SolidLanguageServer, relative_path: str, name: str) -> UnifiedSymbolInformation:
    return next(root for root in _roots(language_server, relative_path) if root["name"] == name)


def _child_names(symbol: UnifiedSymbolInformation) -> list[str]:
    return [child["name"] for child in symbol["children"]]


def _line_span(symbol: UnifiedSymbolInformation) -> tuple[int, int]:
    return symbol["range"]["start"]["line"], symbol["range"]["end"]["line"]


@pytest.mark.parametrize("language_server", [LanguageServerId.NASM], indirect=True)
def test_ls_is_running(language_server: SolidLanguageServer) -> None:
    assert language_server.is_running()


@pytest.mark.parametrize("language_server", [LanguageServerId.NASM], indirect=True)
class TestDocumentSymbols:
    def test_routines_are_top_level_with_local_labels_as_children(self, language_server: SolidLanguageServer) -> None:
        roots = _roots(language_server, "strings.asm")

        assert [(root["name"], root["kind"]) for root in roots] == [
            ("string_length", SymbolKind.Function),
            ("print_string", SymbolKind.Function),
            ("count_char", SymbolKind.Function),
            ("clear_mark", SymbolKind.Function),
        ]
        assert _child_names(roots[0]) == [".next_char", ".done"]
        assert _child_names(roots[2]) == [".next_char", ".skip", ".done"]

    def test_routine_range_spans_header_comment_and_body_up_to_last_instruction(self, language_server: SolidLanguageServer) -> None:
        assert _line_span(_root(language_server, "strings.asm", "string_length")) == (
            _SOURCES.position("strings.asm", "; returns in rax the length").line,
            _SOURCES.position("strings.asm", "    ret\n", occurrence=0).line,
        )
        assert _line_span(_root(language_server, "strings.asm", "clear_mark")) == (
            _SOURCES.position("strings.asm", "; clears the mark flag").line,
            _SOURCES.position("strings.asm", "    ret\n", occurrence=3).line,
        )

    def test_routine_without_header_comment_starts_at_label(self, language_server: SolidLanguageServer) -> None:
        assert _line_span(_root(language_server, "main.asm", "_start"))[0] == _SOURCES.position("main.asm", "_start:").line

    def test_data_labels_are_variables(self, language_server: SolidLanguageServer) -> None:
        kinds = {root["name"]: root["kind"] for root in _roots(language_server, "main.asm")}

        assert kinds == {
            "greeting": SymbolKind.Variable,
            "farewell": SymbolKind.Variable,
            "origin": SymbolKind.Variable,
            "counter": SymbolKind.Variable,
            "_start": SymbolKind.Function,
            "say_goodbye": SymbolKind.Function,
        }
        assert _child_names(_root(language_server, "main.asm", "_start")) == [".repeat"]

    def test_macros_constants_and_structures(self, language_server: SolidLanguageServer) -> None:
        roots = _roots(language_server, "macros.inc")

        assert [(root["name"], root["kind"]) for root in roots] == [
            ("SYS_WRITE", SymbolKind.Constant),
            ("SYS_EXIT", SymbolKind.Constant),
            ("STDOUT", SymbolKind.Constant),
            ("FLAG_MARK", SymbolKind.Constant),
            ("write_stdout", SymbolKind.Function),
            ("exit_process", SymbolKind.Function),
            ("point", SymbolKind.Struct),
        ]
        assert [(child["name"], child["kind"]) for child in roots[6]["children"]] == [(".x", SymbolKind.Field), (".y", SymbolKind.Field)]
        assert _line_span(roots[4]) == (
            _SOURCES.position("macros.inc", "%macro write_stdout").line,
            _SOURCES.position("macros.inc", "%endmacro", occurrence=0).line,
        )

    def test_symbols_reflect_unsaved_edits(self, language_server: SolidLanguageServer) -> None:
        insert_line = _SOURCES.position("strings.asm", "; returns in rax the number").line

        with language_server.open_file("strings.asm"):
            end = language_server.insert_text_at_position("strings.asm", insert_line, 0, "do_nothing:\n    ret\n\n")
            try:
                assert "do_nothing" in [root["name"] for root in _roots(language_server, "strings.asm")]
            finally:
                language_server.delete_text_between_positions("strings.asm", {"line": insert_line, "character": 0}, end)


@pytest.mark.parametrize("language_server", [LanguageServerId.NASM], indirect=True)
class TestNavigation:
    @staticmethod
    def _definitions(language_server: SolidLanguageServer, relative_path: str, needle: str, occurrence: int = 0) -> set[SourceLine]:
        position = _SOURCES.position(relative_path, needle, occurrence)
        return {
            SourceLine.from_location(location)
            for location in language_server.request_definition(relative_path, position.line, position.column)
        }

    @staticmethod
    def _references(language_server: SolidLanguageServer, relative_path: str, needle: str, occurrence: int = 0) -> set[SourceLine]:
        position = _SOURCES.position(relative_path, needle, occurrence)
        return {
            SourceLine.from_location(location)
            for location in language_server.request_references(relative_path, position.line, position.column)
        }

    def test_definition_of_routine_in_other_file(self, language_server: SolidLanguageServer) -> None:
        assert self._definitions(language_server, "main.asm", "print_string", occurrence=1) == {
            _SOURCES.line("strings.asm", "print_string:")
        }

    def test_definition_of_local_label_is_in_enclosing_routine(self, language_server: SolidLanguageServer) -> None:
        assert self._definitions(language_server, "strings.asm", ".done", occurrence=2) == {
            _SOURCES.line("strings.asm", ".done:", occurrence=1)
        }

    def test_definition_of_macro_invocation(self, language_server: SolidLanguageServer) -> None:
        assert self._definitions(language_server, "main.asm", "exit_process 0") == {_SOURCES.line("macros.inc", "%macro exit_process")}

    def test_definition_of_structure_field(self, language_server: SolidLanguageServer) -> None:
        assert self._definitions(language_server, "main.asm", "point.y]") == {_SOURCES.line("macros.inc", ".y: resq")}

    def test_references_across_files(self, language_server: SolidLanguageServer) -> None:
        assert self._references(language_server, "strings.asm", "print_string:") == {
            _SOURCES.line("strings.asm", "global print_string"),
            _SOURCES.line("main.asm", "extern print_string"),
            _SOURCES.line("main.asm", "call print_string", occurrence=0),
            _SOURCES.line("main.asm", "call print_string", occurrence=1),
        }

    def test_references_of_local_label_stay_within_routine(self, language_server: SolidLanguageServer) -> None:
        assert self._references(language_server, "strings.asm", ".next_char:", occurrence=0) == {
            _SOURCES.line("strings.asm", "jmp .next_char", occurrence=0)
        }

    def test_references_include_bitwise_not_operands(self, language_server: SolidLanguageServer) -> None:
        assert self._references(language_server, "macros.inc", "FLAG_MARK equ") == {_SOURCES.line("strings.asm", "~FLAG_MARK")}

    def test_referencing_symbols_are_enclosing_routines(self, language_server: SolidLanguageServer) -> None:
        position = _SOURCES.position("strings.asm", "string_length:")
        referencing = language_server.request_referencing_symbols("strings.asm", position.line, position.column)

        assert [reference.symbol["name"] for reference in referencing] == ["print_string"]

    def test_hover_shows_label_with_leading_comment(self, language_server: SolidLanguageServer) -> None:
        position = _SOURCES.position("main.asm", "call print_string")
        hover = language_server.request_hover("main.asm", position.line, position.column + len("call "))

        assert hover is not None
        assert "writes the zero-terminated string at rdi to stdout" in str(hover["contents"])

    def test_workspace_symbol_search(self, language_server: SolidLanguageServer) -> None:
        symbols = language_server.request_workspace_symbol("print_") or []

        assert {symbol["name"] for symbol in symbols} == {"print_string"}
