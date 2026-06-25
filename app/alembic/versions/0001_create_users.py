"""create users table

Revision ID: 0001_create_users
Revises:
Create Date: 2026-06-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = "0001_create_users"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column(
            "username",
            sqlmodel.sql.sqltypes.AutoString(length=64),
            nullable=False,
        ),
        sa.Column("email", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("full_name", sqlmodel.sql.sqltypes.AutoString(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column(
            "hashed_password",
            sqlmodel.sql.sqltypes.AutoString(length=255),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_username"), table_name="users")
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
