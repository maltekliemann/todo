from __future__ import annotations

import os
from pathlib import Path


def get_db_path() -> Path:
    env = os.environ.get("TODO_DB")
    if env:
        return Path(env)
    return Path.home() / ".todo" / "todos.db"
