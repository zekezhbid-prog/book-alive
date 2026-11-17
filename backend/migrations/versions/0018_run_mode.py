"""deep search: the mode of an analysis run

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs",
        sa.Column("mode", sa.String(20), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "mode")
