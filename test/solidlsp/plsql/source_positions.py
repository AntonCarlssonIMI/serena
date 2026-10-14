"""
Helpers for locating text in the PL/SQL test repository, such that tests need not hard-code line numbers.
"""

from dataclasses import dataclass

from solidlsp import ls_types
from solidlsp.ls_config import LanguageServerId
from test.conftest import get_repo_path


@dataclass(frozen=True)
class SourcePosition:
    """
    A zero-based position in a file of the test repository.
    """

    line: int
    column: int


def find_position(relative_path: str, needle: str, occurrence: int = 0) -> SourcePosition:
    """
    :param relative_path: the path of the file relative to the test repository
    :param needle: the text to search for
    :param occurrence: the zero-based index of the occurrence of the needle to use
    :return: the position of the first character of the given occurrence of the needle
    """
    text = (get_repo_path(LanguageServerId.PLSQL) / relative_path).read_text(encoding="utf-8")
    offset = -1
    for _ in range(occurrence + 1):
        offset = text.index(needle, offset + 1)
    line_start = text.rfind("\n", 0, offset) + 1
    return SourcePosition(line=text.count("\n", 0, offset), column=offset - line_start)


@dataclass(frozen=True)
class SourceLine:
    """
    A line in a file of the test repository, used to compare locations independently of columns.
    """

    relative_path: str
    line: int

    @classmethod
    def of(cls, relative_path: str, needle: str, occurrence: int = 0) -> "SourceLine":
        """
        :param relative_path: the path of the file relative to the test repository
        :param needle: the text to search for
        :param occurrence: the zero-based index of the occurrence of the needle to use
        :return: the line containing the given occurrence of the needle
        """
        return cls(relative_path, find_position(relative_path, needle, occurrence).line)

    @classmethod
    def from_location(cls, location: ls_types.Location) -> "SourceLine":
        """
        :param location: a location returned by the language server
        :return: the line at which the location starts
        """
        return cls(location["relativePath"], location["range"]["start"]["line"])
