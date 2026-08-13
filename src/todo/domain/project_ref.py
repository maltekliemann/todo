"""How a person names a project when they are asked which one."""

from __future__ import annotations

from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName


class ProjectRef(str):
    """What was typed to designate a project: an id or a name.

    Not a property of a project — a project has an id and a name, and
    never a "ref". This is the thing said at the boundary, and it is a
    domain type because what counts as id-shaped is a domain question,
    not a rule the CLI and the TUI should each answer for themselves.

    It accepts anything typable, including what designates nothing:
    refusing here would turn "no such project" into a different failure
    depending on how the ref was misspelled.
    """

    __slots__ = ()

    def __new__(cls, value: str) -> ProjectRef:
        # Collapsed like every other single-line value, so a padded ref
        # designates what the unpadded one does.
        return super().__new__(cls, " ".join(value.split()))

    @property
    def as_id(self) -> ProjectId | None:
        """The id this designates, if it designates one at all.

        isdecimal, not isdigit: '²'.isdigit() is True but int('²')
        raises. The length cap is what a store can hold — a 64-bit
        integer — so an oversized ref is a ref to nothing rather than an
        overflow halfway down.
        """
        if not self.isdecimal() or len(self) > 18:
            return None
        return ProjectId(int(self))

    @property
    def as_name(self) -> ProjectName | None:
        """The name this designates, or None if it names nothing."""
        try:
            return ProjectName(self)
        except ValueError:
            return None
