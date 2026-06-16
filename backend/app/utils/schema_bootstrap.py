from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection


async def _table_exists(conn: AsyncConnection, table_name: str) -> bool:
    result = await conn.execute(text("SELECT to_regclass(:table_name) IS NOT NULL"), {"table_name": table_name})
    return bool(result.scalar())


async def _column_exists(conn: AsyncConnection, table_name: str, column_name: str) -> bool:
    result = await conn.execute(
        text("""
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
        """),
        {"table_name": table_name, "column_name": column_name},
    )
    return result.scalar_one_or_none() is not None


async def _column_is_not_null(conn: AsyncConnection, table_name: str, column_name: str) -> bool:
    result = await conn.execute(
        text("""
            SELECT is_nullable = 'NO'
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = :table_name
              AND column_name = :column_name
            LIMIT 1
        """),
        {"table_name": table_name, "column_name": column_name},
    )
    return bool(result.scalar())


async def _add_column_if_missing(conn: AsyncConnection, table_name: str, column_sql: str, column_name: str) -> None:
    if not await _table_exists(conn, table_name):
        return
    if await _column_exists(conn, table_name, column_name):
        return
    await conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_sql}"))


async def _set_not_null_if_needed(conn: AsyncConnection, table_name: str, column_name: str) -> None:
    if await _column_is_not_null(conn, table_name, column_name):
        return
    await conn.execute(text(f"ALTER TABLE {table_name} ALTER COLUMN {column_name} SET NOT NULL"))


async def _index_exists(conn: AsyncConnection, index_name: str) -> bool:
    result = await conn.execute(text("SELECT to_regclass(:index_name) IS NOT NULL"), {"index_name": index_name})
    return bool(result.scalar())


async def _create_index_if_missing(conn: AsyncConnection, index_name: str, sql: str) -> None:
    if await _index_exists(conn, index_name):
        return
    await conn.execute(text(sql))


async def _has_rows_matching(conn: AsyncConnection, table_name: str, condition: str) -> bool:
    if not await _table_exists(conn, table_name):
        return False
    result = await conn.execute(text(f"SELECT EXISTS (SELECT 1 FROM {table_name} WHERE {condition})"))
    return bool(result.scalar())


async def ensure_runtime_schema(conn: AsyncConnection) -> None:
    """Mantem bancos existentes compatíveis antes de qualquer SELECT ORM."""
    await _add_column_if_missing(conn, "hydrometers", "red_digits INTEGER NOT NULL DEFAULT 3", "red_digits")
    await _add_column_if_missing(conn, "hydrometers", "black_digits INTEGER", "black_digits")
    await _add_column_if_missing(conn, "hydrometers", "qr_code_token VARCHAR(120)", "qr_code_token")
    if await _has_rows_matching(conn, "hydrometers", "qr_code_token IS NULL OR qr_code_token = ''"):
        await conn.execute(text("UPDATE hydrometers SET qr_code_token = 'AQMOAB-' || replace(id::text, '-', '') WHERE qr_code_token IS NULL OR qr_code_token = ''"))
    await _set_not_null_if_needed(conn, "hydrometers", "qr_code_token")
    await _create_index_if_missing(conn, "ix_hydrometers_qr_code_token", "CREATE UNIQUE INDEX ix_hydrometers_qr_code_token ON hydrometers (qr_code_token)")
    await _add_column_if_missing(conn, "hydrometers", "disconnected_at TIMESTAMP WITH TIME ZONE", "disconnected_at")
    await _add_column_if_missing(conn, "hydrometers", "reconnected_at TIMESTAMP WITH TIME ZONE", "reconnected_at")
    await _add_column_if_missing(conn, "hydrometers", "disconnection_reason TEXT", "disconnection_reason")
    await _add_column_if_missing(conn, "hydrometers", "allowed_radius_meters DOUBLE PRECISION NOT NULL DEFAULT 80", "allowed_radius_meters")
    await _add_column_if_missing(conn, "hydrometers", "location_required BOOLEAN NOT NULL DEFAULT true", "location_required")
    await _add_column_if_missing(conn, "hydrometers", "location_source VARCHAR(40)", "location_source")

    await _add_column_if_missing(conn, "readings", "location_accuracy_meters DOUBLE PRECISION", "location_accuracy_meters")
    await _add_column_if_missing(conn, "readings", "distance_from_hydrometer_meters DOUBLE PRECISION", "distance_from_hydrometer_meters")
    await _add_column_if_missing(conn, "readings", "location_status VARCHAR(30) NOT NULL DEFAULT 'unchecked'", "location_status")
    await _add_column_if_missing(conn, "readings", "validation_flags JSONB NOT NULL DEFAULT '[]'::jsonb", "validation_flags")
    await _add_column_if_missing(conn, "readings", "anomaly_override_reason TEXT", "anomaly_override_reason")

    await _add_column_if_missing(conn, "invoices", "original_amount DOUBLE PRECISION", "original_amount")
    if await _has_rows_matching(conn, "invoices", "original_amount IS NULL"):
        await conn.execute(text("UPDATE invoices SET original_amount = amount WHERE original_amount IS NULL"))
    await _add_column_if_missing(conn, "invoices", "custom_adjustment_amount DOUBLE PRECISION NOT NULL DEFAULT 0", "custom_adjustment_amount")
    await _add_column_if_missing(conn, "invoices", "late_fee_amount DOUBLE PRECISION NOT NULL DEFAULT 0", "late_fee_amount")
    await _add_column_if_missing(conn, "invoices", "interest_amount DOUBLE PRECISION NOT NULL DEFAULT 0", "interest_amount")
    await _add_column_if_missing(conn, "invoices", "days_overdue_charged INTEGER NOT NULL DEFAULT 0", "days_overdue_charged")
    await _add_column_if_missing(conn, "invoices", "overdue_charges_allowed BOOLEAN NOT NULL DEFAULT true", "overdue_charges_allowed")
    await _add_column_if_missing(conn, "invoices", "overdue_charge_blocked_reason TEXT", "overdue_charge_blocked_reason")
    await _add_column_if_missing(conn, "invoices", "adjustment_reason TEXT", "adjustment_reason")
    await _add_column_if_missing(conn, "invoices", "charge_type VARCHAR(30) NOT NULL DEFAULT 'water'", "charge_type")
    await _add_column_if_missing(conn, "invoices", "payment_provider VARCHAR(30)", "payment_provider")
    await _add_column_if_missing(conn, "invoices", "payment_due_date DATE", "payment_due_date")
    await _add_column_if_missing(conn, "invoices", "efi_charge_id VARCHAR(100)", "efi_charge_id")
    await _add_column_if_missing(conn, "invoices", "efi_status VARCHAR(30)", "efi_status")
    await _add_column_if_missing(conn, "invoices", "efi_barcode VARCHAR(150)", "efi_barcode")
    await _add_column_if_missing(conn, "invoices", "efi_payment_url TEXT", "efi_payment_url")
    await _add_column_if_missing(conn, "invoices", "efi_pdf_url TEXT", "efi_pdf_url")
    await _add_column_if_missing(conn, "invoices", "efi_pix_qrcode TEXT", "efi_pix_qrcode")
    await _add_column_if_missing(conn, "invoices", "efi_payment_receipt_url TEXT", "efi_payment_receipt_url")
    await _add_column_if_missing(conn, "invoices", "efi_raw_response JSONB", "efi_raw_response")

    await _add_column_if_missing(conn, "system_settings", "daily_interest_percent DOUBLE PRECISION NOT NULL DEFAULT 0.033", "daily_interest_percent")
    await _add_column_if_missing(conn, "system_settings", "late_fee_percent DOUBLE PRECISION NOT NULL DEFAULT 10", "late_fee_percent")
    await _add_column_if_missing(conn, "system_settings", "installation_fee_amount DOUBLE PRECISION NOT NULL DEFAULT 100", "installation_fee_amount")
    await _add_column_if_missing(conn, "system_settings", "reconnection_fee_amount DOUBLE PRECISION NOT NULL DEFAULT 160", "reconnection_fee_amount")
    await _add_column_if_missing(conn, "system_settings", "cut_notice_days_after_due INTEGER NOT NULL DEFAULT 5", "cut_notice_days_after_due")
    await _add_column_if_missing(conn, "system_settings", "default_due_day INTEGER NOT NULL DEFAULT 10", "default_due_day")
    await _add_column_if_missing(conn, "system_settings", "auto_send_invoice_on_approval BOOLEAN NOT NULL DEFAULT true", "auto_send_invoice_on_approval")
    await _add_column_if_missing(conn, "system_settings", "notification_flows JSONB NOT NULL DEFAULT '{}'::jsonb", "notification_flows")

    if not await _table_exists(conn, "whatsapp_messages"):
        await conn.execute(text("""
            CREATE TABLE whatsapp_messages (
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
    await _create_index_if_missing(conn, "ix_whatsapp_messages_phone", "CREATE INDEX ix_whatsapp_messages_phone ON whatsapp_messages (phone)")
    await _create_index_if_missing(conn, "ix_whatsapp_messages_created_at", "CREATE INDEX ix_whatsapp_messages_created_at ON whatsapp_messages (created_at DESC)")

    await _add_column_if_missing(conn, "kimi_vision_memory", "red_digits INTEGER", "red_digits")
    await _add_column_if_missing(conn, "kimi_vision_memory", "black_digits INTEGER", "black_digits")
    await _add_column_if_missing(conn, "kimi_vision_memory", "hydrometer_brand VARCHAR(100)", "hydrometer_brand")
    await _add_column_if_missing(conn, "kimi_vision_memory", "hydrometer_model VARCHAR(100)", "hydrometer_model")
    await _add_column_if_missing(conn, "kimi_vision_memory", "reasoning_log TEXT", "reasoning_log")
    await _add_column_if_missing(conn, "kimi_vision_memory", "divergence_reason TEXT", "divergence_reason")

    await _create_index_if_missing(conn, "ix_customers_status_name", "CREATE INDEX ix_customers_status_name ON customers (status, name)")
    await _create_index_if_missing(conn, "ix_customers_has_hydrometer_name", "CREATE INDEX ix_customers_has_hydrometer_name ON customers (has_hydrometer, name)")
    await _create_index_if_missing(conn, "ix_customers_phone", "CREATE INDEX ix_customers_phone ON customers (phone)")
    await _create_index_if_missing(conn, "ix_customers_phone_suffix", "CREATE INDEX ix_customers_phone_suffix ON customers (right(regexp_replace(coalesce(phone, ''), '\\D', '', 'g'), 8))")
    await _create_index_if_missing(conn, "ix_hydrometers_customer_active", "CREATE INDEX ix_hydrometers_customer_active ON hydrometers (customer_id, is_active)")
    await _create_index_if_missing(conn, "ix_hydrometers_active_code", "CREATE INDEX ix_hydrometers_active_code ON hydrometers (is_active, code)")
    await _create_index_if_missing(conn, "ix_readings_status_created_at", "CREATE INDEX ix_readings_status_created_at ON readings (status, created_at DESC)")
    await _create_index_if_missing(conn, "ix_readings_hydrometer_created_at", "CREATE INDEX ix_readings_hydrometer_created_at ON readings (hydrometer_id, created_at DESC)")
    await _create_index_if_missing(conn, "ix_invoices_status_due_date", "CREATE INDEX ix_invoices_status_due_date ON invoices (status, due_date DESC)")
    await _create_index_if_missing(conn, "ix_invoices_customer_status_due", "CREATE INDEX ix_invoices_customer_status_due ON invoices (customer_id, status, due_date DESC)")
    await _create_index_if_missing(conn, "ix_invoices_customer_paid_date", "CREATE INDEX ix_invoices_customer_paid_date ON invoices (customer_id, paid_date DESC) WHERE paid_date IS NOT NULL")
    await _create_index_if_missing(conn, "ix_invoices_reference_month", "CREATE INDEX ix_invoices_reference_month ON invoices (reference_month)")
    await _create_index_if_missing(conn, "ix_invoices_efi_charge_id", "CREATE INDEX ix_invoices_efi_charge_id ON invoices (efi_charge_id)")
    await _create_index_if_missing(conn, "ix_whatsapp_messages_phone_created_at", "CREATE INDEX ix_whatsapp_messages_phone_created_at ON whatsapp_messages (phone, created_at DESC)")
    await _create_index_if_missing(conn, "ix_whatsapp_messages_external_message_id", "CREATE INDEX ix_whatsapp_messages_external_message_id ON whatsapp_messages (external_message_id)")
