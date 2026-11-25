"""outward looks of a character: entity variants and the variant of a base picture

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-25 15:00:00

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024"
down_revision: str | Sequence[str] | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "entities",
        sa.Column("variants", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "images",
        sa.Column("variant", sa.String(40), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("images", "variant")
    op.drop_column("entities", "variants")
