from __future__ import annotations

import json
import sys
from datetime import datetime
from typing import Protocol, runtime_checkable

from todo.domain.enums import Priority, Status
from todo.domain.models import TodoItem


def _relative_age(dt: datetime) -> str:
    now = datetime.now(tz=dt.tzinfo)
    delta = now - dt
    seconds = int(delta.total_seconds())
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    days = hours // 24
    if days < 7:
        return f"{days}d"
    weeks = days // 7
    if weeks < 4:
        return f"{weeks}w"
    months = days // 30
    return f"{months}mo"


def _priority_label(p: Priority) -> str:
    if p == Priority.URGENT:
        return "!! URG"
    if p == Priority.HIGH:
        return "!  HIGH"
    if p == Priority.MEDIUM:
        return "   MED"
    return "   LOW"


def _status_label(s: Status) -> str:
    return s.value


def _deadline_str(item: TodoItem) -> str:
    if item.deadline is None:
        return ""
    days = item.days_until_deadline
    assert days is not None
    if item.is_overdue:
        return f"\U0001f534 {item.deadline.strftime('%b %d')} ({abs(days)}d overdue)"
    if item.deadline_urgent:
        return f"\u26a0 {item.deadline.strftime('%b %d')} ({days}d)"
    return item.deadline.strftime("%b %d")


@runtime_checkable
class OutputProtocol(Protocol):
    def print_list(self, items: list[TodoItem]) -> None: ...
    def print_item(self, item: TodoItem) -> None: ...
    def print_summary(
        self, since: datetime, items: list[TodoItem]
    ) -> None: ...
    def print_deleted(self, item_id: int) -> None: ...
    def print_json_list(self, items: list[TodoItem]) -> None: ...
    def print_json_item(self, item: TodoItem) -> None: ...
    def print_json_summary(
        self, since: datetime, items: list[TodoItem]
    ) -> None: ...


def _item_to_dict(item: TodoItem) -> dict[str, object]:
    return {
        "id": item.id,
        "title": item.title,
        "body": item.body,
        "priority": item.priority.value,
        "status": item.status.value,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "done_at": item.done_at.isoformat() if item.done_at else None,
        "deadline": item.deadline.isoformat() if item.deadline else None,
        "tags": item.tags,
        "is_overdue": item.is_overdue,
        "blocked_by": item.blocked_by,
        "blocking": item.blocking,
        "is_blocked": item.is_blocked,
    }


class RichOutput:
    def __init__(self) -> None:
        from rich.console import Console

        self._console = Console()

    def print_list(self, items: list[TodoItem]) -> None:
        if not items:
            self._console.print("[dim]No items.[/dim]")
            return

        from rich.table import Table

        table = Table(show_header=True, show_edge=False, pad_edge=False, box=None)
        table.add_column("#", style="dim", width=5, justify="right")
        table.add_column("Pri", width=7)
        table.add_column("Status", width=13)
        table.add_column("Title", min_width=20)
        table.add_column("Deadline", width=22)
        table.add_column("Age", width=5, justify="right")

        for item in items:
            pri_style = _pri_style(item.priority)
            dl = _deadline_str(item)
            dl_style = _deadline_style(item)
            status_icon = _status_icon(item.status)
            title = f"\U0001f6a7 {item.title}" if item.is_blocked else item.title
            table.add_row(
                str(item.id),
                f"[{pri_style}]{_priority_label(item.priority)}[/{pri_style}]",
                f"{status_icon} {_status_label(item.status)}",
                title,
                f"[{dl_style}]{dl}[/{dl_style}]" if dl else "",
                _relative_age(item.created_at),
            )

        self._console.print(table)
        self._console.print(
            f"\n[dim]{len(items)} item{'s' if len(items) != 1 else ''}[/dim]"
        )

    def print_item(self, item: TodoItem) -> None:
        from rich.panel import Panel
        from rich.text import Text

        lines = Text()
        lines.append(f"#{item.id}  ", style="dim")
        lines.append(item.title, style="bold")
        lines.append("\n")
        lines.append(
            f"Priority: {item.priority.value}  ",
            style=_pri_style(item.priority),
        )
        lines.append(f"Status: {item.status.value}  ")
        if item.deadline:
            dl = _deadline_str(item)
            lines.append(f"Deadline: {dl}  ", style=_deadline_style(item))
        lines.append("\n")
        lines.append(
            f"Created: {item.created_at.strftime('%b %d, %Y %H:%M')}   "
            f"Updated: {item.updated_at.strftime('%b %d, %Y %H:%M')}"
        )
        if item.done_at:
            lines.append(f"   Done: {item.done_at.strftime('%b %d, %Y %H:%M')}")
        if item.tags:
            lines.append(f"\nTags: {', '.join(item.tags)}")
        if item.blocked_by:
            blocked = ", ".join(f"#{i}" for i in item.blocked_by)
            lines.append(f"\nBlocked by: {blocked}")
        if item.blocking:
            blocking = ", ".join(f"#{i}" for i in item.blocking)
            lines.append(f"\nBlocking: {blocking}")
        if item.body:
            lines.append(f"\n\n{item.body}")

        self._console.print(Panel(lines))

    def print_summary(self, since: datetime, items: list[TodoItem]) -> None:
        now = datetime.now(tz=since.tzinfo)
        header = f"Done ({since.strftime('%b %d')} \u2192 {now.strftime('%b %d')})"
        self._console.rule(header)

        if not items:
            self._console.print("[dim]No items completed in this period.[/dim]")
            return

        from rich.table import Table

        table = Table(show_header=True, show_edge=False, pad_edge=False, box=None)
        table.add_column("#", style="dim", width=5, justify="right")
        table.add_column("Pri", width=7)
        table.add_column("Done", width=10)
        table.add_column("Title", min_width=20)

        for item in items:
            pri_style = _pri_style(item.priority)
            done_str = item.done_at.strftime("%b %d") if item.done_at else ""
            table.add_row(
                str(item.id),
                f"[{pri_style}]{_priority_label(item.priority)}[/{pri_style}]",
                done_str,
                item.title,
            )

        self._console.print(table)
        self._console.print(
            f"\n[dim]{len(items)} item{'s' if len(items) != 1 else ''} completed[/dim]"
        )

    def print_deleted(self, item_id: int) -> None:
        self._console.print(f"[dim]Deleted #{item_id}.[/dim]")

    def print_json_list(self, items: list[TodoItem]) -> None:
        print(json.dumps([_item_to_dict(i) for i in items], indent=2))

    def print_json_item(self, item: TodoItem) -> None:
        print(json.dumps(_item_to_dict(item), indent=2))

    def print_json_summary(self, since: datetime, items: list[TodoItem]) -> None:
        print(
            json.dumps(
                {
                    "since": since.isoformat(),
                    "items": [_item_to_dict(i) for i in items],
                    "count": len(items),
                },
                indent=2,
            )
        )


class PlainOutput:
    def print_list(self, items: list[TodoItem]) -> None:
        if not items:
            print("No items.")
            return
        for item in items:
            dl = _deadline_str(item)
            dl_part = f"  {dl}" if dl else ""
            title = f"\U0001f6a7 {item.title}" if item.is_blocked else item.title
            print(
                f"  {item.id:>4}  {_priority_label(item.priority)}  "
                f"{_status_label(item.status):<13} {title}{dl_part}"
            )
        print(f"\n{len(items)} item{'s' if len(items) != 1 else ''}")

    def print_item(self, item: TodoItem) -> None:
        print(f"#{item.id}  {item.title}")
        print(f"Priority: {item.priority.value}  Status: {item.status.value}")
        if item.deadline:
            print(f"Deadline: {_deadline_str(item)}")
        print(
            f"Created: {item.created_at.isoformat()}  "
            f"Updated: {item.updated_at.isoformat()}"
        )
        if item.done_at:
            print(f"Done: {item.done_at.isoformat()}")
        if item.tags:
            print(f"Tags: {', '.join(item.tags)}")
        if item.blocked_by:
            print(f"Blocked by: {', '.join(f'#{i}' for i in item.blocked_by)}")
        if item.blocking:
            print(f"Blocking: {', '.join(f'#{i}' for i in item.blocking)}")
        if item.body:
            print(f"\n{item.body}")

    def print_summary(self, since: datetime, items: list[TodoItem]) -> None:
        now = datetime.now(tz=since.tzinfo)
        print(f"-- Done ({since.strftime('%b %d')} -> {now.strftime('%b %d')}) --")
        if not items:
            print("No items completed in this period.")
            return
        for item in items:
            done_str = item.done_at.strftime("%b %d") if item.done_at else ""
            print(
                f"  {item.id:>4}  {_priority_label(item.priority)}  "
                f"{done_str:<10} {item.title}"
            )
        print(f"\n{len(items)} item{'s' if len(items) != 1 else ''} completed")

    def print_deleted(self, item_id: int) -> None:
        print(f"Deleted #{item_id}.")

    def print_json_list(self, items: list[TodoItem]) -> None:
        print(json.dumps([_item_to_dict(i) for i in items], indent=2))

    def print_json_item(self, item: TodoItem) -> None:
        print(json.dumps(_item_to_dict(item), indent=2))

    def print_json_summary(self, since: datetime, items: list[TodoItem]) -> None:
        print(
            json.dumps(
                {
                    "since": since.isoformat(),
                    "items": [_item_to_dict(i) for i in items],
                    "count": len(items),
                },
                indent=2,
            )
        )


def _pri_style(p: Priority) -> str:
    if p == Priority.URGENT:
        return "bold red"
    if p == Priority.HIGH:
        return "dark_orange"
    if p == Priority.LOW:
        return "dim"
    return ""


def _status_icon(s: Status) -> str:
    if s == Status.DONE:
        return "\u2713"
    if s == Status.IN_PROGRESS:
        return "\u25cf"
    return "\u25cb"


def _deadline_style(item: TodoItem) -> str:
    if item.is_overdue:
        return "bold red"
    if item.deadline_urgent:
        return "yellow"
    return "dim"


def create_output() -> RichOutput | PlainOutput:
    if sys.stdout.isatty():
        return RichOutput()
    return PlainOutput()
