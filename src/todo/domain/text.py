"""Text normalization rules shared by every layer.

Single-line fields (titles, project names, descriptions, log bodies) and
the migrations that clean up legacy rows must agree byte-for-byte on what
"normalized" means — one implementation, not synced copies.
"""

from __future__ import annotations


def single_line(value: str) -> str:
    """Collapse every whitespace run (including newlines) to one space."""
    return " ".join(value.split())
