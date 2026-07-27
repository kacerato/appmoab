"""add durable reading cycles and immutable reading competence

Revision ID: 20260727_0007
Revises: 20260721_0006
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260727_0007"
down_revision: str | None = "20260721_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS reading_cycles (
            id UUID PRIMARY KEY,
            customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            hydrometer_id UUID NOT NULL REFERENCES hydrometers(id) ON DELETE CASCADE,
            reference_month VARCHAR(7) NOT NULL,
            due_date DATE NOT NULL,
            cycle_type VARCHAR(20) NOT NULL,
            status VARCHAR(30) NOT NULL DEFAULT 'open',
            opened_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            completed_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_reading_cycles_meter_reference_type
                UNIQUE (hydrometer_id, reference_month, cycle_type)
        )
    """)
    op.execute("ALTER TABLE readings ADD COLUMN IF NOT EXISTS cycle_id UUID REFERENCES reading_cycles(id) ON DELETE SET NULL")
    op.execute("ALTER TABLE readings ADD COLUMN IF NOT EXISTS reference_month VARCHAR(7)")
    op.execute("ALTER TABLE readings ADD COLUMN IF NOT EXISTS reading_kind VARCHAR(20) NOT NULL DEFAULT 'water'")
    op.execute("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS cycle_id UUID REFERENCES reading_cycles(id) ON DELETE SET NULL")

    op.execute("""
        UPDATE readings r
        SET reference_month = i.reference_month,
            reading_kind = CASE WHEN i.charge_type = 'installation' THEN 'installation' ELSE 'water' END
        FROM invoices i
        WHERE i.reading_id = r.id
          AND r.reference_month IS NULL
    """)
    op.execute("""
        UPDATE readings
        SET reference_month = to_char(captured_at AT TIME ZONE 'UTC', 'YYYY-MM')
        WHERE reference_month IS NULL
    """)
    op.execute("""
        INSERT INTO reading_cycles (
            id, customer_id, hydrometer_id, reference_month, due_date,
            cycle_type, status, opened_at, completed_at, created_at, updated_at
        )
        SELECT gen_random_uuid(), h.customer_id, r.hydrometer_id, r.reference_month,
               make_date(split_part(r.reference_month, '-', 1)::int,
                         split_part(r.reference_month, '-', 2)::int,
                         c.due_day),
               r.reading_kind,
               CASE
                   WHEN r.status = 'pending' THEN 'pending_review'
                   WHEN r.status = 'rejected' THEN 'recapture_required'
                   WHEN i.status = 'cancelled' THEN 'invoice_cancelled'
                   WHEN i.status = 'paid' THEN 'paid'
                   ELSE 'invoiced'
               END,
               r.created_at,
               CASE WHEN r.status = 'approved' THEN r.approved_at ELSE NULL END,
               r.created_at,
               now()
        FROM readings r
        JOIN hydrometers h ON h.id = r.hydrometer_id
        JOIN customers c ON c.id = h.customer_id
        LEFT JOIN invoices i ON i.reading_id = r.id
        ON CONFLICT (hydrometer_id, reference_month, cycle_type) DO NOTHING
    """)
    op.execute("""
        UPDATE readings r
        SET cycle_id = rc.id
        FROM reading_cycles rc
        WHERE rc.hydrometer_id = r.hydrometer_id
          AND rc.reference_month = r.reference_month
          AND rc.cycle_type = r.reading_kind
          AND r.cycle_id IS NULL
    """)
    op.execute("""
        UPDATE invoices i
        SET cycle_id = r.cycle_id
        FROM readings r
        WHERE r.id = i.reading_id
          AND i.cycle_id IS NULL
    """)
    op.execute("""
        INSERT INTO reading_cycles (
            id, customer_id, hydrometer_id, reference_month, due_date,
            cycle_type, status, opened_at, created_at, updated_at
        )
        SELECT gen_random_uuid(), h.customer_id, h.id,
               to_char(
                   CASE
                       WHEN latest.reference_month IS NOT NULL
                           THEN (latest.reference_month || '-01')::date + interval '1 month'
                       ELSE date_trunc('month', h.last_reading_date) + interval '1 month'
                   END,
                   'YYYY-MM'
               ),
               make_date(
                   extract(year FROM CASE
                       WHEN latest.reference_month IS NOT NULL
                           THEN (latest.reference_month || '-01')::date + interval '1 month'
                       ELSE date_trunc('month', h.last_reading_date) + interval '1 month'
                   END)::int,
                   extract(month FROM CASE
                       WHEN latest.reference_month IS NOT NULL
                           THEN (latest.reference_month || '-01')::date + interval '1 month'
                       ELSE date_trunc('month', h.last_reading_date) + interval '1 month'
                   END)::int,
                   c.due_day
               ),
               'water', 'open', now(), now(), now()
        FROM hydrometers h
        JOIN customers c ON c.id = h.customer_id
        LEFT JOIN LATERAL (
            SELECT r.reference_month
            FROM readings r
            WHERE r.hydrometer_id = h.id
              AND r.status = 'approved'
              AND r.reference_month IS NOT NULL
            ORDER BY r.captured_at DESC
            LIMIT 1
        ) latest ON true
        WHERE h.last_reading_date IS NOT NULL
          AND h.is_active = true
          AND NOT EXISTS (
              SELECT 1 FROM reading_cycles rc
              WHERE rc.hydrometer_id = h.id
                AND rc.status IN ('open', 'pending_review', 'recapture_required')
          )
        ON CONFLICT (hydrometer_id, reference_month, cycle_type) DO NOTHING
    """)
    op.execute("""
        INSERT INTO reading_cycles (
            id, customer_id, hydrometer_id, reference_month, due_date,
            cycle_type, status, opened_at, created_at, updated_at
        )
        SELECT gen_random_uuid(), h.customer_id, h.id,
               to_char(current_date, 'YYYY-MM'),
               make_date(extract(year FROM current_date)::int,
                         extract(month FROM current_date)::int,
                         c.due_day),
               'installation', 'open', now(), now(), now()
        FROM hydrometers h
        JOIN customers c ON c.id = h.customer_id
        WHERE h.last_reading_date IS NULL
          AND h.is_active = true
          AND NOT EXISTS (
              SELECT 1 FROM reading_cycles rc
              WHERE rc.hydrometer_id = h.id
                AND rc.status IN ('open', 'pending_review', 'recapture_required')
          )
        ON CONFLICT (hydrometer_id, reference_month, cycle_type) DO NOTHING
    """)

    op.execute("CREATE INDEX IF NOT EXISTS ix_reading_cycles_route ON reading_cycles (status, due_date, customer_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_reading_cycles_hydrometer ON reading_cycles (hydrometer_id, due_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_readings_cycle_id ON readings (cycle_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_readings_reference_month ON readings (reference_month)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_invoices_cycle_id ON invoices (cycle_id)")
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_readings_active_cycle
        ON readings (cycle_id)
        WHERE cycle_id IS NOT NULL AND status IN ('pending', 'approved')
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ux_readings_active_cycle")
    op.execute("DROP INDEX IF EXISTS ix_invoices_cycle_id")
    op.execute("DROP INDEX IF EXISTS ix_readings_reference_month")
    op.execute("DROP INDEX IF EXISTS ix_readings_cycle_id")
    op.execute("DROP INDEX IF EXISTS ix_reading_cycles_hydrometer")
    op.execute("DROP INDEX IF EXISTS ix_reading_cycles_route")
    op.execute("ALTER TABLE invoices DROP COLUMN IF EXISTS cycle_id")
    op.execute("ALTER TABLE readings DROP COLUMN IF EXISTS reading_kind")
    op.execute("ALTER TABLE readings DROP COLUMN IF EXISTS reference_month")
    op.execute("ALTER TABLE readings DROP COLUMN IF EXISTS cycle_id")
    op.execute("DROP TABLE IF EXISTS reading_cycles")
