"""What a project is called."""

from __future__ import annotations


class ProjectName(str):
    """A single-line, non-empty project name.

    Plain output is one row per project, so a name that wraps breaks the
    format. Whitespace is collapsed rather than refused, for the same
    reason a pasted title is.
    """

    __slots__ = ()

    def __new__(cls, value: str) -> ProjectName:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("Project name cannot be empty.")
        return super().__new__(cls, normalized)
