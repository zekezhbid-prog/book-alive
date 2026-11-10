"""separate chat conversations, each with its own scope

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chat_threads",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(32),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("chapter_ids", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_chat_threads_project_id", "chat_threads", ["project_id"])
    op.add_column("chat_messages", sa.Column("thread_id", sa.String(32), nullable=True))
    # The conversation each project already has becomes its first thread, named after
    # its first question.
    op.execute(
        """
        INSERT INTO chat_threads (id, project_id, title, chapter_ids, created_at, updated_at)
        SELECT replace(gen_random_uuid()::text, '-', ''), project_id,
               left(coalesce((array_agg(content ORDER BY created_at)
                              FILTER (WHERE role = 'user'))[1], ''), 60),
               '[]', min(created_at), max(created_at)
        FROM chat_messages GROUP BY project_id
        """
    )
    op.execute(
        "UPDATE chat_messages SET thread_id = t.id FROM chat_threads t "
        "WHERE t.project_id = chat_messages.project_id"
    )
    op.alter_column("chat_messages", "thread_id", nullable=False)
    op.create_foreign_key(
        "chat_messages_thread_id_fkey",
        "chat_messages",
        "chat_threads",
        ["thread_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_chat_messages_thread_id", "chat_messages", ["thread_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_thread_id", "chat_messages")
    op.drop_constraint("chat_messages_thread_id_fkey", "chat_messages", type_="foreignkey")
    op.drop_column("chat_messages", "thread_id")
    op.drop_index("ix_chat_threads_project_id", "chat_threads")
    op.drop_table("chat_threads")
