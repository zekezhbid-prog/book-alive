"""how a card looks: written by the model, and the user's own version

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entities", sa.Column("appearance", sa.Text(), nullable=False, server_default=""))
    op.add_column(
        "entities", sa.Column("appearance_own", sa.Text(), nullable=False, server_default="")
    )


def downgrade() -> None:
    op.drop_column("entities", "appearance_own")
    op.drop_column("entities", "appearance")
