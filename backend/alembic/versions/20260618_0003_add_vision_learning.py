"""add generic meter vision inference and learning records

Revision ID: 20260618_0003
Revises: 20260618_0002
Create Date: 2026-06-18
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260618_0003"
down_revision: str | None = "20260618_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS vision_inferences (
            id UUID PRIMARY KEY,
            hydrometer_id UUID REFERENCES hydrometers(id) ON DELETE SET NULL,
            collaborator_id UUID REFERENCES users(id) ON DELETE SET NULL,
            stage VARCHAR(30) NOT NULL DEFAULT 'reading',
            original_object_key VARCHAR(700),
            rectified_object_key VARCHAR(700),
            model_version VARCHAR(100) NOT NULL,
            predicted_code VARCHAR(50),
            predicted_value DOUBLE PRECISION,
            confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            auto_fill_allowed BOOLEAN NOT NULL DEFAULT false,
            quality JSONB,
            digits JSONB,
            alternatives JSONB,
            flags JSONB,
            red_digits INTEGER,
            black_digits INTEGER,
            hydrometer_brand VARCHAR(100),
            hydrometer_model VARCHAR(100),
            confirmed_code VARCHAR(50),
            confirmed_value DOUBLE PRECISION,
            was_correct BOOLEAN,
            approved_for_training BOOLEAN NOT NULL DEFAULT false,
            divergence_reason TEXT,
            confirmed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_vision_inferences_created ON vision_inferences (created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vision_inferences_training_queue ON vision_inferences (approved_for_training, was_correct, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vision_inferences_model_version ON vision_inferences (model_version)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_vision_inferences_hydrometer_id ON vision_inferences (hydrometer_id)")
    op.execute("ALTER TABLE readings ADD COLUMN IF NOT EXISTS vision_inference_id UUID REFERENCES vision_inferences(id) ON DELETE SET NULL")
    op.execute("CREATE INDEX IF NOT EXISTS ix_readings_vision_inference_id ON readings (vision_inference_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS vision_inferences")
