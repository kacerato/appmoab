"""move reading confirmation to dashboard and make invoice dispatch durable

Revision ID: 20260721_0005
Revises: 20260721_0004
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260721_0005"
down_revision: str | None = "20260721_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE readings ALTER COLUMN current_value DROP NOT NULL")
    op.execute("ALTER TABLE readings ALTER COLUMN consumption DROP NOT NULL")
    op.execute("ALTER TABLE readings ADD COLUMN IF NOT EXISTS review_adjustment_reason TEXT")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(255)")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS last_attempt_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMP WITH TIME ZONE")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_notifications_idempotency_key ON notifications (idempotency_key) WHERE idempotency_key IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_notifications_retry ON notifications (status, next_attempt_at) WHERE status IN ('queued', 'failed')")
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_invoices_reading_id ON invoices (reading_id) WHERE reading_id IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_invoices_reading_id")
    op.execute("DROP INDEX IF EXISTS ix_notifications_retry")
    op.execute("DROP INDEX IF EXISTS ix_notifications_idempotency_key")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS next_attempt_at")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS last_attempt_at")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS attempt_count")
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS idempotency_key")
    op.execute("ALTER TABLE readings DROP COLUMN IF EXISTS review_adjustment_reason")
    op.execute("UPDATE readings SET current_value = 0 WHERE current_value IS NULL")
    op.execute("UPDATE readings SET consumption = 0 WHERE consumption IS NULL")
    op.execute("ALTER TABLE readings ALTER COLUMN consumption SET NOT NULL")
    op.execute("ALTER TABLE readings ALTER COLUMN current_value SET NOT NULL")
