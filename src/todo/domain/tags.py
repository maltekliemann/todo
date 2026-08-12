"""Tag string rules shared by every layer.

Tags are stored comma-joined; the split/strip/drop-empties rule must be
identical wherever a comma-separated tag string is parsed (storage rows,
tag counting, editor and dialog fields, migrations).
"""

from __future__ import annotations

from collections.abc import Iterable


def split_tags(raw: str) -> list[str]:
    """Comma-separated string -> stripped, non-empty tags (order kept)."""
    return [tag for tag in (segment.strip() for segment in raw.split(",")) if tag]


def dedupe_tags(tags: Iterable[str]) -> list[str]:
    """Drop duplicates, preserving first-seen order."""
    seen: list[str] = []
    for tag in tags:
        if tag not in seen:
            seen.append(tag)
    return seen
