"""runs over one card: rebuild a character or a location across the book

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analysis_runs", sa.Column("entity_id", sa.String(32), nullable=True))
    op.add_column(
        "analysis_runs", sa.Column("parts", sa.JSON(), nullable=False, server_default="[]")
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "parts")
    op.drop_column("analysis_runs", "entity_id")
