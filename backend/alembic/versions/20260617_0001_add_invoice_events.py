"""add invoice events audit table

Revision ID: 20260617_0001
Revises:
Create Date: 2026-06-17
"""

from collections.abc import Sequence

from alembic import op


revision: str = "20260617_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS invoice_events (
            id UUID PRIMARY KEY,
            invoice_id UUID NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
            user_id UUID NULL REFERENCES users(id) ON DELETE SET NULL,
            event_type VARCHAR(60) NOT NULL,
            previous_status VARCHAR(30) NULL,
            new_status VARCHAR(30) NULL,
            reason TEXT NULL,
            payload JSONB NULL,
            created_at TIMESTAMPTZ NOT NULL
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_events_created_at ON invoice_events (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_events_event_type ON invoice_events (event_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_events_invoice_id ON invoice_events (invoice_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoice_events_user_id ON invoice_events (user_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_invoice_events_user_id")
    op.execute("DROP INDEX IF EXISTS ix_invoice_events_invoice_id")
    op.execute("DROP INDEX IF EXISTS ix_invoice_events_event_type")
    op.execute("DROP INDEX IF EXISTS ix_invoice_events_created_at")
    op.execute("DROP TABLE IF EXISTS invoice_events")
