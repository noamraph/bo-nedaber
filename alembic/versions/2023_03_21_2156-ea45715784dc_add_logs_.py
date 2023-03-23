"""add logs table

Revision ID: ea45715784dc
Revises: 1c9bdc5491ae
Create Date: 2023-03-21 21:56:57.885567+00:00

"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = 'ea45715784dc'
down_revision = '1c9bdc5491ae'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
    CREATE TABLE logs
    (
        id SERIAL PRIMARY KEY,
        ts TIMESTAMPTZ NOT NULL default NOW(),
        kind TEXT NOT NULL,
        data JSONB NOT NULL
    );
    """
    )


def downgrade() -> None:
    op.execute(
        """
    DROP TABLE logs;
    """
    )
