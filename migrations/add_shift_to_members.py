"""add shift column to members

WHY THIS MIGRATION:
  Adds a non-nullable `shift` String column with a server_default of 'Day'.
  Using server_default means:
    - Existing rows are automatically set to 'Day' with no manual UPDATE.
    - The column is immediately NOT NULL without needing a two-step migration.
  This is safe for PostgreSQL, MySQL, and SQLite.

Revision ID: 001_add_shift_to_members
Revises: <PREVIOUS_REVISION_ID>     ← replace with your last revision
Create Date: 2026-06-29
"""

from alembic   import op
import sqlalchemy as sa

# Revision identifiers used by Alembic
revision     = "001_add_shift_to_members"
down_revision = None   # ← replace with your actual previous revision id
branch_labels = None
depends_on    = None


def upgrade() -> None:
    # Add the column with a server_default so existing rows get 'Day' instantly.
    # No separate UPDATE statement needed — the DB handles it atomically.
    op.add_column(
        "members",
        sa.Column(
            "shift",
            sa.String(length=10),
            nullable=False,
            server_default="Day",
        ),
    )


def downgrade() -> None:
    op.drop_column("members", "shift")
