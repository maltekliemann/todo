from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from todo.application.contracts.storage import StorageProtocol
from todo.domain.enums import Priority, Status
from todo.domain.models import TodoItem


def list_todos(
    storage: StorageProtocol,
    *,
    status: Status | None = None,
    priority: Priority | None = None,
    tag: str | None = None,
    include_done: bool = False,
) -> list[TodoItem]:
    return storage.list(
        status=status,
        priority=priority,
        tag=tag,
        include_done=include_done,
    )


def show_todo(
    storage: StorageProtocol,
    item_id: int,
) -> TodoItem:
    return storage.get(item_id)


def parse_since(since: str) -> datetime:
    """Parse a --since value into a datetime.

    Accepts either:
      - A relative duration like "7 days", "2 weeks", "1 month"
      - An ISO date like "2025-04-01"
    """
    parts = since.strip().split()
    if len(parts) == 2:
        amount_str, unit = parts
        try:
            amount = int(amount_str)
        except ValueError:
            pass
        else:
            unit = unit.lower().rstrip("s")  # "days" -> "day"
            if unit == "day":
                return datetime.now(tz=ZoneInfo("UTC")) - timedelta(days=amount)
            if unit == "week":
                return datetime.now(tz=ZoneInfo("UTC")) - timedelta(weeks=amount)
            if unit == "month":
                return datetime.now(tz=ZoneInfo("UTC")) - timedelta(days=amount * 30)
            raise ValueError(f"Unknown time unit: '{unit}'")

    # Try ISO date
    try:
        dt = datetime.strptime(since, "%Y-%m-%d")
        return dt.replace(tzinfo=ZoneInfo("UTC"))
    except ValueError:
        pass

    raise ValueError(
        f"Cannot parse '{since}'. Use a relative duration like '7 days' "
        "or an ISO date like '2025-04-01'."
    )


def summary(
    storage: StorageProtocol,
    since: str,
) -> tuple[datetime, list[TodoItem]]:
    since_dt = parse_since(since)
    items = storage.done_since(since_dt)
    return since_dt, items
