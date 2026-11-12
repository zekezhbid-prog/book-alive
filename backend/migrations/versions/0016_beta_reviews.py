"""beta reader reviews kept with the chapter

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "beta_reviews",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("chapter_id", sa.String(32), nullable=False),
        sa.Column("chapter_hash", sa.String(64), nullable=False),
        sa.Column("reader", sa.String(20), nullable=False),
        sa.Column("tone", sa.String(20), nullable=False),
        sa.Column("asks", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_beta_reviews_project_id", "beta_reviews", ["project_id"])
    op.create_index("ix_beta_reviews_chapter_id", "beta_reviews", ["chapter_id"])


def downgrade() -> None:
    op.drop_table("beta_reviews")
