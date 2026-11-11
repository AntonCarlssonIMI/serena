"""
Integration tests for renaming with the NASM assembly language server.
"""

import pytest

from solidlsp import SolidLanguageServer
from solidlsp.ls_config import LanguageServerId
from solidlsp.ls_exceptions import SolidLSPException
from test.conftest import get_repo_path
from test.solidlsp.util.source_positions import TestRepoSources

pytestmark = [pytest.mark.nasm]

_SOURCES = TestRepoSources(LanguageServerId.NASM)


def _renamed_lines(
    language_server: SolidLanguageServer, relative_path: str, needle: str, new_name: str, occurrence: int = 0
) -> dict[str, list[str]]:
    """
    Requests a rename and applies the returned edits to copies of the affected files.

    :return: for each affected file, its changed lines (in line order, stripped) with the edits applied
    """
    position = _SOURCES.position(relative_path, needle, occurrence)
    workspace_edit = language_server.request_rename_symbol_edit(relative_path, position.line, position.column, new_name)
    assert workspace_edit is not None

    renamed: dict[str, list[str]] = {}
    for uri, edits in workspace_edit["changes"].items():
        file_name = uri.rsplit("/", 1)[1]
        lines = (get_repo_path(LanguageServerId.NASM) / file_name).read_text(encoding="utf-8").split("\n")
        changed_line_numbers = sorted({edit["range"]["start"]["line"] for edit in edits})
        for edit in sorted(edits, key=lambda e: (e["range"]["start"]["line"], e["range"]["start"]["character"]), reverse=True):
            start, end = edit["range"]["start"], edit["range"]["end"]
            line = lines[start["line"]]
            lines[start["line"]] = line[: start["character"]] + edit["newText"] + line[end["character"] :]
        renamed[file_name] = [lines[number].strip() for number in changed_line_numbers]
    return renamed


@pytest.mark.parametrize("language_server", [LanguageServerId.NASM], indirect=True)
class TestRename:
    def test_rename_routine_updates_code_across_files_but_not_comments(self, language_server: SolidLanguageServer) -> None:
        assert _renamed_lines(language_server, "strings.asm", "print_string:", "write_string") == {
            "strings.asm": ["global write_string", "write_string:"],
            "main.asm": ["extern write_string", "call write_string", "call write_string"],
        }

    def test_rename_local_label_stays_within_routine(self, language_server: SolidLanguageServer) -> None:
        assert _renamed_lines(language_server, "strings.asm", ".done", ".finished", occurrence=2) == {
            "strings.asm": ["jz .finished", ".finished:"],
        }

    def test_rename_structure_updates_qualified_field_uses(self, language_server: SolidLanguageServer) -> None:
        assert _renamed_lines(language_server, "macros.inc", "point\n", "vec2", occurrence=1) == {
            "macros.inc": ["struc vec2"],
            "main.asm": ["istruc vec2", "at vec2.x, dq 0", "at vec2.y, dq 0", "mov rax, [origin + vec2.y]"],
        }

    def test_rename_includes_bitwise_not_operands(self, language_server: SolidLanguageServer) -> None:
        assert _renamed_lines(language_server, "macros.inc", "FLAG_MARK", "MARK_BIT") == {
            "macros.inc": ["MARK_BIT equ 0x80"],
            "strings.asm": ["and byte [rdi], ~MARK_BIT"],
        }

    def test_rename_rejects_local_name_for_non_local_label(self, language_server: SolidLanguageServer) -> None:
        position = _SOURCES.position("strings.asm", "print_string:")

        with pytest.raises(SolidLSPException, match="must not start with a single dot"):
            language_server.request_rename_symbol_edit("strings.asm", position.line, position.column, ".print")
