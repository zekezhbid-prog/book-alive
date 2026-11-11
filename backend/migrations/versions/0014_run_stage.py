"""the final step a run is on after the chapters, shown in the progress

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_runs", sa.Column("stage", sa.String(20), nullable=False, server_default="")
    )
    op.add_column(
        "analysis_runs", sa.Column("stage_done", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "analysis_runs", sa.Column("stage_total", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    op.drop_column("analysis_runs", "stage_total")
    op.drop_column("analysis_runs", "stage_done")
    op.drop_column("analysis_runs", "stage")
