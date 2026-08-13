"""Which projects are being asked for.

The counterpart to ItemFilter: one value rather than a flag, so asking
for projects does not grow an argument every time there is a new way to
narrow them.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProjectFilter:
    """Current projects only, unless the ended are asked for.

    Ended means cancelled or done — the two states that stop a project
    being something you are working on. Which states those are is the
    project's own answer (ProjectStatus.ended), not this filter's.
    """

    include_ended: bool = False
