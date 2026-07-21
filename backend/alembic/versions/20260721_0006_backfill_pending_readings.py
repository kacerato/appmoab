"""move existing pending readings back to dashboard confirmation

Revision ID: 20260721_0006
Revises: 20260721_0005
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260721_0006"
down_revision: str | None = "20260721_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        UPDATE readings
        SET photo_extracted_value = COALESCE(photo_extracted_value, current_value),
            current_value = NULL,
            consumption = NULL
        WHERE status = 'pending'
    """)


def downgrade() -> None:
    op.execute("""
        UPDATE readings
        SET current_value = COALESCE(current_value, photo_extracted_value, 0),
            consumption = COALESCE(consumption, GREATEST(COALESCE(current_value, photo_extracted_value, 0) - previous_value, 0))
        WHERE status = 'pending'
    """)
