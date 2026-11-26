"""a character's looks searched once on the first drawing; views of a place or object

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-26 18:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | Sequence[str] | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column("variants_checked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "entities",
        sa.Column("views", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade() -> None:
    op.drop_column("entities", "views")
    op.drop_column("entities", "variants_checked")
