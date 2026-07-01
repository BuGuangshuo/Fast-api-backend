"""create ai chat conversations

Revision ID: 0002_ai_chat_conversations
Revises: 0001_create_users
Create Date: 2026-06-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0002_ai_chat_conversations"
down_revision: str | None = "0001_create_users"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_chat_conversations",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(length=128), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_message_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_chat_conversations_last_message_at"),
        "ai_chat_conversations",
        ["last_message_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_chat_conversations_title"),
        "ai_chat_conversations",
        ["title"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_chat_conversations_user_id"),
        "ai_chat_conversations",
        ["user_id"],
        unique=False,
    )

    op.create_table(
        "ai_chat_messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("role", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("reasoning_content", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["ai_chat_conversations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_ai_chat_messages_conversation_id"),
        "ai_chat_messages",
        ["conversation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ai_chat_messages_sort_order"),
        "ai_chat_messages",
        ["sort_order"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_ai_chat_messages_sort_order"), table_name="ai_chat_messages")
    op.drop_index(
        op.f("ix_ai_chat_messages_conversation_id"),
        table_name="ai_chat_messages",
    )
    op.drop_table("ai_chat_messages")
    op.drop_index(
        op.f("ix_ai_chat_conversations_user_id"),
        table_name="ai_chat_conversations",
    )
    op.drop_index(
        op.f("ix_ai_chat_conversations_title"),
        table_name="ai_chat_conversations",
    )
    op.drop_index(
        op.f("ix_ai_chat_conversations_last_message_at"),
        table_name="ai_chat_conversations",
    )
    op.drop_table("ai_chat_conversations")
