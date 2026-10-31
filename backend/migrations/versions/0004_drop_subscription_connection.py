"""drop the Claude subscription connection: the app now talks to API providers only

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-31 12:00:00

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Settings that pointed at the removed connection are cleared, as when it is deleted by hand.
    for prefix in ("text", "image"):
        op.execute(
            f"UPDATE app_settings SET value = '' WHERE key IN ('{prefix}_connection_id', '{prefix}_model') "
            f"AND EXISTS (SELECT 1 FROM app_settings c WHERE c.key = '{prefix}_connection_id' "
            "AND c.value IN (SELECT id FROM connections WHERE kind = 'claude_cli'))"
        )
    op.execute("DELETE FROM connections WHERE kind = 'claude_cli'")


def downgrade() -> None:
    pass  # the deleted connections cannot be restored
