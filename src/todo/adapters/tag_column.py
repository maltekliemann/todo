"""How the tags column is written and read.

Tags live comma-joined in one TEXT column. That is this adapter's choice
of encoding, not a fact about tags, so the codec lives here — with the
schema that made it — and never inside the domain.
"""

from __future__ import annotations

from collections.abc import Iterable

from todo.domain.tag import Tag


def decode_tags(raw: str) -> list[Tag]:
    """The stored column back into tags. Empty segments are dropped: a
    trailing or doubled comma is a formatting artefact, not a tag."""
    return [Tag(piece) for piece in raw.split(",") if piece.strip()]


def encode_tags(tags: Iterable[Tag]) -> str:
    """Tags into the stored column. Tag itself refuses a comma, which is
    what keeps this join reversible."""
    return ",".join(tags)
