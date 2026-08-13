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
    """Tags into the stored column, in a fixed order.

    They are a set on the item, so sorting is what makes the stored form
    a function of the tags rather than of iteration order.
    """
    return ",".join(sorted(tags))
