"""a coherent description of a card, written at the end of a run

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entities", sa.Column("summary", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("entities", "summary")
