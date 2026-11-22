"""improve a card: the author's notes on it and the wishes of one run

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column("author_notes", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "analysis_runs",
        sa.Column("wishes", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "wishes")
    op.drop_column("entities", "author_notes")
