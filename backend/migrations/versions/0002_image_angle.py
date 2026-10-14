"""image angle: several main pictures per card, one view each

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-14 19:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "images", sa.Column("angle", sa.String(length=20), nullable=False, server_default="")
    )


def downgrade() -> None:
    op.drop_column("images", "angle")
