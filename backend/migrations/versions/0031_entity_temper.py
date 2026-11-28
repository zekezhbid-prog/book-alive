"""a character's nature as it shows (behaviour, speech, movement, usual mood)

Revision ID: 0031
Revises: 0030
Create Date: 2026-11-28 00:30:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0031"
down_revision: str | Sequence[str] | None = "0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column("temper", sa.Text(), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("entities", "temper")
