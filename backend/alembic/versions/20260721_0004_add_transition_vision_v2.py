"""add transition-aware vision capture and decision metadata

Revision ID: 20260721_0004
Revises: 20260618_0003
Create Date: 2026-07-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260721_0004"
down_revision: str | None = "20260618_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE vision_inferences ADD COLUMN IF NOT EXISTS frame_object_keys JSONB")
    op.execute("ALTER TABLE vision_inferences ADD COLUMN IF NOT EXISTS capture_id UUID")
    op.execute("ALTER TABLE vision_inferences ADD COLUMN IF NOT EXISTS capture_metadata JSONB")
    op.execute("ALTER TABLE vision_inferences ADD COLUMN IF NOT EXISTS decision VARCHAR(30) NOT NULL DEFAULT 'confirm'")
    op.execute("ALTER TABLE vision_inferences ADD COLUMN IF NOT EXISTS calibrated_confidence DOUBLE PRECISION")
    op.execute("ALTER TABLE vision_inferences ADD COLUMN IF NOT EXISTS decoder_version VARCHAR(100)")
    op.execute("ALTER TABLE vision_inferences ADD COLUMN IF NOT EXISTS calibration_version VARCHAR(100)")
    op.execute("ALTER TABLE vision_inferences ADD COLUMN IF NOT EXISTS slot_labels JSONB")
    op.execute("ALTER TABLE vision_inferences ADD COLUMN IF NOT EXISTS dataset_version VARCHAR(100)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vision_inferences_capture_id ON vision_inferences (capture_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vision_inferences_decision ON vision_inferences (decision)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_vision_inferences_decision")
    op.execute("DROP INDEX IF EXISTS ix_vision_inferences_capture_id")
    op.execute("ALTER TABLE vision_inferences DROP COLUMN IF EXISTS dataset_version")
    op.execute("ALTER TABLE vision_inferences DROP COLUMN IF EXISTS slot_labels")
    op.execute("ALTER TABLE vision_inferences DROP COLUMN IF EXISTS calibration_version")
    op.execute("ALTER TABLE vision_inferences DROP COLUMN IF EXISTS decoder_version")
    op.execute("ALTER TABLE vision_inferences DROP COLUMN IF EXISTS calibrated_confidence")
    op.execute("ALTER TABLE vision_inferences DROP COLUMN IF EXISTS decision")
    op.execute("ALTER TABLE vision_inferences DROP COLUMN IF EXISTS capture_metadata")
    op.execute("ALTER TABLE vision_inferences DROP COLUMN IF EXISTS capture_id")
    op.execute("ALTER TABLE vision_inferences DROP COLUMN IF EXISTS frame_object_keys")
