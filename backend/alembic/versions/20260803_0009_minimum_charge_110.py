"""set default minimum charge to 110

Revision ID: 20260803_0009
Revises: 20260727_0008
Create Date: 2026-08-03
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260803_0009"
down_revision: str | None = "20260727_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("tariff_tiers", "minimum_charge", server_default="110")
    op.execute("UPDATE tariff_tiers SET minimum_charge = 110")


def downgrade() -> None:
    op.execute("UPDATE tariff_tiers SET minimum_charge = 100 WHERE minimum_charge = 110")
    op.alter_column("tariff_tiers", "minimum_charge", server_default="100")
