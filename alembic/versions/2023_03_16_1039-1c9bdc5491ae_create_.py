"""create states table

Revision ID: 1c9bdc5491ae
Revises:
Create Date: 2023-03-16 10:39:57.511529+00:00

"""
from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "1c9bdc5491ae"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
    CREATE TABLE states
    (
        uid bigint,
        state jsonb NOT NULL,
        PRIMARY KEY (uid)
    );
    """
    )


def downgrade() -> None:
    op.execute(
        """
    DROP TABLE states;
    """
    )
