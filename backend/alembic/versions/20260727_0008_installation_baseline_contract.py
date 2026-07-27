"""enforce installation baseline billing contract

Revision ID: 20260727_0008
Revises: 20260727_0007
Create Date: 2026-07-27
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260727_0008"
down_revision: str | None = "20260727_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Corrige somente primeiras leituras que foram faturadas como agua e cujo
    # boleto ja esta cancelado. Cobrancas externas ativas nunca sao alteradas
    # silenciosamente por uma migracao.
    op.execute("""
        WITH first_approved AS (
            SELECT r.id, r.cycle_id,
                   row_number() OVER (
                       PARTITION BY r.hydrometer_id
                       ORDER BY r.captured_at, r.created_at
                   ) AS position
            FROM readings r
            WHERE r.status = 'approved'
        ),
        targets AS (
            SELECT r.id AS reading_id, r.cycle_id, i.id AS invoice_id
            FROM first_approved ranked
            JOIN readings r ON r.id = ranked.id
            JOIN invoices i ON i.reading_id = r.id
            WHERE ranked.position = 1
              AND r.reading_kind <> 'installation'
              AND i.charge_type = 'water'
              AND i.status = 'cancelled'
        )
        UPDATE reading_cycles cycle
        SET cycle_type = 'installation',
            updated_at = now()
        FROM targets target
        WHERE cycle.id = target.cycle_id
          AND NOT EXISTS (
              SELECT 1
              FROM reading_cycles existing
              WHERE existing.hydrometer_id = cycle.hydrometer_id
                AND existing.reference_month = cycle.reference_month
                AND existing.cycle_type = 'installation'
                AND existing.id <> cycle.id
          )
    """)
    op.execute("""
        WITH first_approved AS (
            SELECT r.id,
                   row_number() OVER (
                       PARTITION BY r.hydrometer_id
                       ORDER BY r.captured_at, r.created_at
                   ) AS position
            FROM readings r
            WHERE r.status = 'approved'
        )
        UPDATE readings reading
        SET reading_kind = 'installation',
            consumption = 0
        FROM first_approved ranked, invoices invoice
        WHERE reading.id = ranked.id
          AND ranked.position = 1
          AND invoice.reading_id = reading.id
          AND invoice.charge_type = 'water'
          AND invoice.status = 'cancelled'
    """)
    op.execute("""
        WITH first_approved AS (
            SELECT r.id,
                   row_number() OVER (
                       PARTITION BY r.hydrometer_id
                       ORDER BY r.captured_at, r.created_at
                   ) AS position
            FROM readings r
            WHERE r.status = 'approved'
        )
        UPDATE invoices invoice
        SET charge_type = 'installation',
            consumption_m3 = 0,
            tariff_rate = 0,
            amount = settings.installation_fee_amount,
            original_amount = settings.installation_fee_amount,
            custom_adjustment_amount = 0,
            late_fee_amount = 0,
            interest_amount = 0,
            days_overdue_charged = 0,
            adjustment_reason = 'Primeira leitura reclassificada como base de instalação',
            updated_at = now()
        FROM first_approved ranked
        CROSS JOIN system_settings settings
        WHERE invoice.reading_id = ranked.id
          AND ranked.position = 1
          AND invoice.charge_type = 'water'
          AND invoice.status = 'cancelled'
          AND settings.id = 1
    """)
    op.execute("""
        INSERT INTO invoice_events (
            id, invoice_id, user_id, event_type, previous_status, new_status,
            reason, payload, created_at
        )
        SELECT gen_random_uuid(), invoice.id, NULL,
               'installation_baseline_reclassified',
               invoice.status, invoice.status,
               'Primeira leitura corrigida para base de instalacao',
               jsonb_build_object(
                   'reading_id', invoice.reading_id,
                   'corrected_charge_type', 'installation',
                   'corrected_amount', invoice.amount
               ),
               now()
        FROM invoices invoice
        WHERE invoice.status = 'cancelled'
          AND invoice.charge_type = 'installation'
          AND invoice.adjustment_reason = 'Primeira leitura reclassificada como base de instalação'
          AND NOT EXISTS (
              SELECT 1
              FROM invoice_events event
              WHERE event.invoice_id = invoice.id
                AND event.event_type = 'installation_baseline_reclassified'
          )
    """)


def downgrade() -> None:
    # A classificacao corrigida representa o fato operacional e nao deve ser
    # revertida automaticamente.
    pass
