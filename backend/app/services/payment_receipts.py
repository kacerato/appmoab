"""Persistencia de comprovantes tecnicos de pagamento."""

import json
from datetime import datetime, timezone
from typing import Any

from app.models.invoice import Invoice
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.invoice_documents import (
    DocumentPayload,
    EFI_PAYMENT_EVENT,
    store_invoice_document,
)


async def store_efi_payment_receipt(
    db: AsyncSession,
    invoice: Invoice,
    payload: dict[str, Any],
) -> str:
    document = {
        "provider": "efi",
        "invoice_id": str(invoice.id),
        "customer_id": str(invoice.customer_id),
        "charge_id": invoice.efi_charge_id,
        "amount": invoice.amount,
        "status": invoice.status,
        "efi_status": invoice.efi_status,
        "paid_date": invoice.paid_date.isoformat() if invoice.paid_date else None,
        "stored_at": datetime.now(timezone.utc).isoformat(),
        "payload": payload,
    }
    raw = json.dumps(document, ensure_ascii=False, indent=2).encode("utf-8")
    document = await store_invoice_document(
        db,
        invoice,
        DocumentPayload(
            raw=raw,
            document_type=EFI_PAYMENT_EVENT,
            source="efi_webhook",
            original_name=f"confirmacao_efi_{str(invoice.id)[:8]}.json",
            mime_type="application/json",
            provider_document_id=invoice.efi_charge_id,
            metadata={"status": invoice.status, "efi_status": invoice.efi_status},
        ),
    )
    return document.object_key
