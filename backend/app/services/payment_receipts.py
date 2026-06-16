"""Persistencia de comprovantes tecnicos de pagamento."""

import base64
import json
from datetime import datetime, timezone
from typing import Any

from app.models.invoice import Invoice
from app.utils.storage import save_binary_from_base64


def store_efi_payment_receipt(invoice: Invoice, payload: dict[str, Any]) -> str:
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
    encoded = base64.b64encode(raw).decode("utf-8")
    return save_binary_from_base64(
        f"data:application/json;base64,{encoded}",
        prefix=f"efi_receipt_{invoice.id}",
        fallback_ext="json",
    )
