"""the user's own call on a card in question

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entities", sa.Column("uncertain_own", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_column("entities", "uncertain_own")
