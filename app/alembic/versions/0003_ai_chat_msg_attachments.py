"""add ai chat message attachments

Revision ID: 0003_ai_chat_msg_attachments
Revises: 0002_ai_chat_conversations
Create Date: 2026-07-08
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003_ai_chat_msg_attachments"
down_revision: str | None = "0002_ai_chat_conversations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_chat_messages",
        sa.Column(
            "attachments",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_chat_messages", "attachments")
