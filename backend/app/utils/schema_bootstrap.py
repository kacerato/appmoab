from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def ensure_runtime_schema(conn: AsyncConnection) -> None:
    """Mantem bancos existentes compatíveis antes de qualquer SELECT ORM."""
    await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS red_digits INTEGER NOT NULL DEFAULT 3"))
    await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS black_digits INTEGER"))
    await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS qr_code_token VARCHAR(120)"))
    await conn.execute(text("UPDATE hydrometers SET qr_code_token = 'AQMOAB-' || replace(id::text, '-', '') WHERE qr_code_token IS NULL OR qr_code_token = ''"))
    await conn.execute(text("ALTER TABLE hydrometers ALTER COLUMN qr_code_token SET NOT NULL"))
    await conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_hydrometers_qr_code_token ON hydrometers (qr_code_token)"))
    await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS disconnected_at TIMESTAMP WITH TIME ZONE"))
    await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS reconnected_at TIMESTAMP WITH TIME ZONE"))
    await conn.execute(text("ALTER TABLE hydrometers ADD COLUMN IF NOT EXISTS disconnection_reason TEXT"))

    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS original_amount DOUBLE PRECISION"))
    await conn.execute(text("UPDATE invoices SET original_amount = amount WHERE original_amount IS NULL"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS custom_adjustment_amount DOUBLE PRECISION NOT NULL DEFAULT 0"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS late_fee_amount DOUBLE PRECISION NOT NULL DEFAULT 0"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS interest_amount DOUBLE PRECISION NOT NULL DEFAULT 0"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS days_overdue_charged INTEGER NOT NULL DEFAULT 0"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS overdue_charges_allowed BOOLEAN NOT NULL DEFAULT true"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS overdue_charge_blocked_reason TEXT"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS adjustment_reason TEXT"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS charge_type VARCHAR(30) NOT NULL DEFAULT 'water'"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_provider VARCHAR(30)"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS payment_due_date DATE"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS efi_charge_id VARCHAR(100)"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS efi_status VARCHAR(30)"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS efi_barcode VARCHAR(150)"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS efi_payment_url TEXT"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS efi_pdf_url TEXT"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS efi_pix_qrcode TEXT"))
    await conn.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS efi_raw_response JSONB"))

    await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS daily_interest_percent DOUBLE PRECISION NOT NULL DEFAULT 0.033"))
    await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS late_fee_percent DOUBLE PRECISION NOT NULL DEFAULT 10"))
    await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS installation_fee_amount DOUBLE PRECISION NOT NULL DEFAULT 100"))
    await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS reconnection_fee_amount DOUBLE PRECISION NOT NULL DEFAULT 160"))
    await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS cut_notice_days_after_due INTEGER NOT NULL DEFAULT 5"))
    await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS default_due_day INTEGER NOT NULL DEFAULT 10"))
    await conn.execute(text("ALTER TABLE system_settings ADD COLUMN IF NOT EXISTS notification_flows JSONB NOT NULL DEFAULT '{}'::jsonb"))

    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS whatsapp_messages (
            id UUID PRIMARY KEY,
            customer_id UUID NULL REFERENCES customers(id) ON DELETE SET NULL,
            phone VARCHAR(30) NOT NULL,
            direction VARCHAR(12) NOT NULL DEFAULT 'inbound',
            body TEXT NOT NULL,
            external_message_id VARCHAR(255),
            status VARCHAR(30) NOT NULL DEFAULT 'received',
            payload JSONB,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_whatsapp_messages_phone ON whatsapp_messages (phone)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_whatsapp_messages_created_at ON whatsapp_messages (created_at DESC)"))

    await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS red_digits INTEGER"))
    await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS black_digits INTEGER"))
    await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS hydrometer_brand VARCHAR(100)"))
    await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS hydrometer_model VARCHAR(100)"))
    await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS reasoning_log TEXT"))
    await conn.execute(text("ALTER TABLE kimi_vision_memory ADD COLUMN IF NOT EXISTS divergence_reason TEXT"))

    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_customers_status_name ON customers (status, name)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_customers_has_hydrometer_name ON customers (has_hydrometer, name)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_readings_status_created_at ON readings (status, created_at DESC)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_status_due_date ON invoices (status, due_date DESC)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_reference_month ON invoices (reference_month)"))
    await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_invoices_efi_charge_id ON invoices (efi_charge_id)"))
