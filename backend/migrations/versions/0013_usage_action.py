"""usage events of one user action share an id

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("usage_events", sa.Column("action_id", sa.String(32), nullable=True))
    op.create_index("ix_usage_events_action_id", "usage_events", ["action_id"])


def downgrade() -> None:
    op.drop_index("ix_usage_events_action_id", "usage_events")
    op.drop_column("usage_events", "action_id")
