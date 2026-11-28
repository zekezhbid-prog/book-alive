"""a scene broken down into sub-scenes: one place, one time, one action each

Revision ID: 0032
Revises: 0031
Create Date: 2026-11-28 16:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0032"
down_revision: str | Sequence[str] | None = "0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "scenes",
        sa.Column("subscenes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("scenes", "subscenes")
