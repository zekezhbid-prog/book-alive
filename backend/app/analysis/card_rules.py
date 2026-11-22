"""Which card is a main one, and which of two cards stays when the author merges them."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import deep
from app.config import settings
from app.models import Entity


def chapter_count(entity: Entity) -> int:
    return len({f.chapter_id for f in entity.facts})


def is_main(session: Session, entity_id: str) -> bool:
    """A main card is written by the strong model, and improved by it too. The same rule as
    the deep search: a proper name, seen in enough chapters, among the most frequent ones."""
    entity = session.get(Entity, entity_id)
    if entity is None or entity.uncertain or chapter_count(entity) < deep.MAIN_MIN_CHAPTERS:
        return False
    ranked = sorted(
        (
            e
            for e in session.scalars(
                select(Entity).where(
                    Entity.project_id == entity.project_id, Entity.kind == entity.kind
                )
            )
            if not e.uncertain and chapter_count(e) >= deep.MAIN_MIN_CHAPTERS
        ),
        key=lambda e: -chapter_count(e),
    )
    return entity.id in {e.id for e in ranked[: settings.deep_main_limit]}


def merge_main(a: Entity, b: Entity) -> tuple[Entity, Entity]:
    """(the card that stays, the card folded into it). A card with a proper name wins over
    one without; otherwise the one seen in more chapters, then the one with more facts.
    On a full tie the card the author started from stays."""

    def weight(e: Entity) -> tuple[bool, int, int]:
        return (
            not e.uncertain,
            chapter_count(e),
            sum(1 for f in e.facts if (f.text or "").strip()),
        )

    return (b, a) if weight(b) > weight(a) else (a, b)
