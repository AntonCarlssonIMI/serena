# SPDX-License-Identifier: MIT
"""
Positions and ranges in source texts.
"""

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class TextPosition:
    """
    A zero-based position (line and character) in a source text.
    """

    line: int
    character: int


@dataclass(frozen=True)
class TextRange:
    """
    A range in a source text.
    """

    start: TextPosition
    end: TextPosition

    def contains(self, position: TextPosition) -> bool:
        """
        :param position: the position to test
        :return: whether the position lies within the range; both ends are inclusive, such that a position directly
            after an identifier still refers to it
        """
        return self.start <= position <= self.end


@dataclass(frozen=True)
class SourceLocation:
    """
    A range in a document.
    """

    uri: str
    range: TextRange
