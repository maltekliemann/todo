"""Every project's name, by id.

An item names its project by identity, so whatever draws an item has to
look the name up — once for a page, not once per item.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType

from todo.application.contracts.project_store import ProjectStore
from todo.domain.project_filter import ProjectFilter
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName


@dataclass(frozen=True)
class ProjectNames:
    """The names, and the one question anyone asks of them.

    A type rather than a bare mapping, because what a presenter wants is
    the name of the project an item names — and an item may name none,
    which a mapping answers with a KeyError.
    """

    names: MappingProxyType[ProjectId, ProjectName]

    def of(self, project_id: ProjectId | None) -> ProjectName | None:
        """That project's name, or None — for an item filed under
        nothing, or under a project that is gone."""
        if project_id is None:
            return None
        return self.names.get(project_id)


class LoadProjectNames:
    def __init__(self, projects: ProjectStore) -> None:
        self._projects = projects

    def execute(self) -> ProjectNames:
        # Ended ones included: an item filed under a finished project
        # still shows the name it was filed under.
        return ProjectNames(
            MappingProxyType(
                {
                    p.id: p.name
                    for p in self._projects.find(ProjectFilter(include_ended=True))
                }
            )
        )
