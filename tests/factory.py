"""Seeding, for tests.

The app builds a domain object, takes an identity for it and hands it to
a workflow. A test that only wants three items on the table should not
have to write that out thirty times, so it is written out once here.
Nothing in this file is production code: it is the terse way to say
"suppose these items existed".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone

from todo.adapters.sqlite_counter_store import SqliteCounterStore
from todo.application.contracts.dependency_store import DependencyStore
from todo.application.contracts.item_store import ItemStore
from todo.application.contracts.project_log_store import ProjectLogStore
from todo.application.contracts.project_store import ProjectStore
from todo.application.queries.find_project import FindProject
from todo.application.queries.list_tags import ListTags
from todo.application.queries.list_todos import ListTodos
from todo.application.queries.show_project import ProjectDetail, ShowProject
from todo.application.toast import Toast
from todo.application.workflows.add_blocker import AddBlocker
from todo.application.workflows.create_project import CreateProject
from todo.application.workflows.create_project_update import CreateProjectUpdate
from todo.application.workflows.create_todo import CreateTodo
from todo.application.workflows.delete_project import DeleteProject
from todo.application.workflows.delete_todo import DeleteTodo
from todo.application.workflows.edit_project import EditProject
from todo.application.workflows.edit_todo import EditTodo
from todo.application.workflows.remove_blocker import RemoveBlocker
from todo.application.workflows.set_status import SetStatus
from todo.application.workflows.take_item_id import TakeItemId
from todo.application.workflows.take_project_id import TakeProjectId
from todo.application.workflows.take_update_id import TakeUpdateId
from todo.config import get_db_path
from todo.domain.body import Body
from todo.domain.deadline import Deadline
from todo.domain.description import Description
from todo.domain.item_filter import ItemFilter
from todo.domain.item_id import ItemId
from todo.domain.priority import Priority
from todo.domain.project import Project
from todo.domain.project_id import ProjectId
from todo.domain.project_name import ProjectName
from todo.domain.project_ref import ProjectRef
from todo.domain.project_update import ProjectUpdate
from todo.domain.status import Status
from todo.domain.tag import Tag
from todo.domain.title import Title
from todo.domain.todo_item import TodoItem
from todo.domain.update_body import UpdateBody


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _item_ids() -> SqliteCounterStore:
    return SqliteCounterStore(get_db_path(), "items")


def _project_ids() -> SqliteCounterStore:
    return SqliteCounterStore(get_db_path(), "projects")


def _update_ids() -> SqliteCounterStore:
    return SqliteCounterStore(get_db_path(), "project_updates")


@dataclass(frozen=True)
class NewItem:
    """What a test wants an item to look like."""

    title: str
    body: str = ""
    priority: Priority = Priority.MEDIUM
    status: Status = Status.TODO
    deadline: date | None = None
    tags: frozenset[str] = field(default_factory=frozenset)
    project_id: ProjectId | None = None


def add_todo(items: ItemStore, spec: NewItem) -> TodoItem:
    stamp = _now()
    item = TodoItem(
        id=TakeItemId(_item_ids()).execute(),
        title=Title(spec.title),
        body=Body(spec.body),
        priority=spec.priority,
        status=Status.TODO,
        created_at=stamp,
        updated_at=stamp,
        deadline=Deadline.from_date(spec.deadline) if spec.deadline else None,
        tags=frozenset(Tag(t) for t in spec.tags),
        project_id=spec.project_id,
    )
    if spec.status is not Status.TODO:
        item.set_status(spec.status)
    CreateTodo(items).execute(item)
    return item


def edit_todo(
    items: ItemStore,
    item_id: int,
    *,
    title: str | None = None,
    body: str | None = None,
    priority: Priority | None = None,
    deadline: date | None = None,
    tags: frozenset[str] | None = None,
    project_id: ProjectId | None = None,
) -> TodoItem:
    item = items.get(ItemId(item_id))
    if title is not None:
        item.set_title(Title(title))
    if body is not None:
        item.set_body(Body(body))
    if priority is not None:
        item.set_priority(priority)
    if deadline is not None:
        item.set_deadline(Deadline.from_date(deadline))
    if tags is not None:
        wanted = frozenset(Tag(t) for t in tags)
        for gone in item.tags - wanted:
            item.remove_tag(gone)
        for added in wanted - item.tags:
            item.add_tag(added)
    if project_id is not None:
        item.set_project_id(project_id)
    EditTodo(items).execute(item)
    return item


def set_status(
    items: ItemStore,
    dependencies: DependencyStore,
    item_id: int,
    status: Status,
) -> list[Toast]:
    return SetStatus(items, dependencies).execute(ItemId(item_id), status)


def delete_todo(
    items: ItemStore, dependencies: DependencyStore, item_id: int
) -> list[Toast]:
    return DeleteTodo(items, dependencies).execute(ItemId(item_id))


def add_blocker(
    items: ItemStore,
    dependencies: DependencyStore,
    blocked_id: int,
    blocker_ids: list[int],
) -> None:
    AddBlocker(items, dependencies).execute(
        ItemId(blocked_id), [ItemId(b) for b in blocker_ids]
    )


def remove_blocker(
    items: ItemStore,
    dependencies: DependencyStore,
    blocked_id: int,
    blocker_ids: list[int],
) -> list[Toast]:
    return RemoveBlocker(items, dependencies).execute(
        ItemId(blocked_id), [ItemId(b) for b in blocker_ids]
    )


def list_todos(items: ItemStore, **narrowing: object) -> list[TodoItem]:
    tags = narrowing.pop("tags", frozenset())
    assert isinstance(tags, frozenset)
    return ListTodos(items).execute(
        ItemFilter(tags=frozenset(Tag(t) for t in tags), **narrowing)  # type: ignore[arg-type]
    )


def list_tags(items: ItemStore) -> list[tuple[Tag, int]]:
    return ListTags(items).execute()


def add_project(projects: ProjectStore, name: str, *, description: str = "") -> Project:
    stamp = _now()
    project = Project(
        id=TakeProjectId(_project_ids()).execute(),
        name=ProjectName(name),
        description=Description(description),
        created_at=stamp,
        updated_at=stamp,
    )
    CreateProject(projects).execute(project)
    return project


def edit_project(
    projects: ProjectStore,
    project_id: ProjectId,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Project:
    project = projects.get(project_id)
    if name is not None:
        project.set_name(ProjectName(name))
    if description is not None:
        project.set_description(Description(description))
    EditProject(projects).execute(project)
    return projects.get(project_id)


def delete_project(
    projects: ProjectStore,
    items: ItemStore,
    log: ProjectLogStore,
    project_id: ProjectId,
) -> None:
    DeleteProject(projects, items, log).execute(project_id)


def log_project_update(
    projects: ProjectStore,
    log: ProjectLogStore,
    project_id: ProjectId,
    body: str,
) -> ProjectUpdate:
    update = ProjectUpdate(
        id=TakeUpdateId(_update_ids()).execute(),
        project_id=project_id,
        body=UpdateBody(body),
        created_at=_now(),
    )
    CreateProjectUpdate(projects, log).execute(update)
    return update


def find_project(projects: ProjectStore, ref: str) -> Project:
    return FindProject(projects).execute(ProjectRef(ref))


def show_project(
    projects: ProjectStore,
    items: ItemStore,
    log: ProjectLogStore,
    ref: str,
) -> ProjectDetail:
    return ShowProject(projects, items, log).execute(
        FindProject(projects).execute(ProjectRef(ref)).id
    )
