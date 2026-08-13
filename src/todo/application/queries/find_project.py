"""The project a reference names.

`todo project show 42` and `--project 42` take one reference that may be
an id or a name, and something has to decide which.
"""

from __future__ import annotations

from todo.application.contracts.project_store import ProjectStore
from todo.domain.project import Project
from todo.domain.project_ref import ProjectRef
from todo.exceptions import ProjectNotFoundError


class FindProject:
    def __init__(self, projects: ProjectStore) -> None:
        self._projects = projects

    def execute(self, ref: ProjectRef) -> Project:
        """A ref that looks like an id means the id shown in `project
        list`, falling back to a project literally named so; anything
        else is a name.

        Id has to win for a numeric ref: name-first resolution let a
        project whose name happens to be a number shadow another
        project's id in every command that takes one, deletion included.
        """
        name = ref.as_name
        if name is None:
            # It names nothing and it is not id-shaped either, so there
            # is nothing it could designate.
            raise ProjectNotFoundError(ref)
        project_id = ref.as_id
        if project_id is not None:
            try:
                return self._projects.get(project_id)
            except ProjectNotFoundError:
                return self._projects.get_by_name(name)
        return self._projects.get_by_name(name)
