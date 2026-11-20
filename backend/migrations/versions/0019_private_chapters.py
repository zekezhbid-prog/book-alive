"""chapters closed to AI; the author's personal data at the start of existing books is
split off into such a chapter

Revision ID: 0019
Revises: 0018
"""

import hashlib
import uuid

import sqlalchemy as sa
from alembic import op

from app.importing.private import PRIVATE_TITLE, personal_block

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "chapters",
        sa.Column("private", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    db = op.get_bind()
    firsts = db.execute(
        sa.text(
            "SELECT DISTINCT ON (project_id) id, project_id, text FROM chapters "
            "ORDER BY project_id, position"
        )
    ).all()
    for chapter_id, project_id, text in firsts:
        paragraphs = (text or "").split("\n\n")
        count = personal_block(paragraphs)
        if not count:
            continue
        if count == len(paragraphs):
            db.execute(
                sa.text(
                    "UPDATE chapters SET private = true, "
                    "title = CASE WHEN title = '' THEN :title ELSE title END WHERE id = :id"
                ),
                {"id": chapter_id, "title": PRIVATE_TITLE},
            )
            continue
        block, rest = "\n\n".join(paragraphs[:count]), "\n\n".join(paragraphs[count:])
        db.execute(
            sa.text("UPDATE chapters SET position = position + 1 WHERE project_id = :p"),
            {"p": project_id},
        )
        db.execute(
            sa.text("UPDATE chapters SET text = :t, content_hash = :h WHERE id = :id"),
            {"t": rest, "h": _hash(rest), "id": chapter_id},
        )
        db.execute(
            sa.text(
                "INSERT INTO chapters (id, project_id, position, title, text, content_hash, "
                "private) VALUES (:id, :p, 0, :title, :t, :h, true)"
            ),
            {
                "id": uuid.uuid4().hex,
                "p": project_id,
                "title": PRIVATE_TITLE,
                "t": block,
                "h": _hash(block),
            },
        )


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def downgrade() -> None:
    op.drop_column("chapters", "private")
