"""scenes proposed for a chapter are kept; a card is made from one the user picks

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-27 22:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0029"
down_revision: str | Sequence[str] | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scene_splits",
        sa.Column("chapter_id", sa.String(length=32), nullable=False),
        sa.Column("project_id", sa.String(length=32), nullable=False),
        sa.Column("chapter_hash", sa.String(length=64), nullable=False),
        sa.Column("proposals", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("chapter_id"),
    )
    op.create_index("ix_scene_splits_project_id", "scene_splits", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_scene_splits_project_id", table_name="scene_splits")
    op.drop_table("scene_splits")
