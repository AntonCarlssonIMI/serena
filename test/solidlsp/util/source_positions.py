"""
Helpers for locating text in a language's test repository, such that tests need not hard-code line numbers.
"""

from dataclasses import dataclass

from solidlsp import ls_types
from solidlsp.ls_config import LanguageServerId
from test.conftest import get_repo_path


@dataclass(frozen=True)
class SourcePosition:
    """
    A zero-based position in a file of a test repository.
    """

    line: int
    column: int


@dataclass(frozen=True)
class SourceLine:
    """
    A line in a file of a test repository, used to compare locations independently of columns.
    """

    relative_path: str
    line: int

    @classmethod
    def from_location(cls, location: ls_types.Location) -> "SourceLine":
        """
        :param location: a location returned by the language server
        :return: the line at which the location starts
        """
        return cls(location["relativePath"], location["range"]["start"]["line"])


class TestRepoSources:
    """
    The source files of a language's test repository.
    """

    __test__ = False  # not a test class

    def __init__(self, language: LanguageServerId) -> None:
        """
        :param language: the language whose test repository to use
        """
        self._repo_path = get_repo_path(language)

    def position(self, relative_path: str, needle: str, occurrence: int = 0) -> SourcePosition:
        """
        :param relative_path: the path of the file relative to the test repository
        :param needle: the text to search for
        :param occurrence: the zero-based index of the occurrence of the needle to use
        :return: the position of the first character of the given occurrence of the needle
        """
        text = (self._repo_path / relative_path).read_text(encoding="utf-8")
        offset = -1
        for _ in range(occurrence + 1):
            offset = text.index(needle, offset + 1)
        line_start = text.rfind("\n", 0, offset) + 1
        return SourcePosition(line=text.count("\n", 0, offset), column=offset - line_start)

    def line(self, relative_path: str, needle: str, occurrence: int = 0) -> SourceLine:
        """
        :param relative_path: the path of the file relative to the test repository
        :param needle: the text to search for
        :param occurrence: the zero-based index of the occurrence of the needle to use
        :return: the line containing the given occurrence of the needle
        """
        return SourceLine(relative_path, self.position(relative_path, needle, occurrence).line)
