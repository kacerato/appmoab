"""Migra PDFs legados do PostgreSQL para o dossie no R2 em lotes idempotentes."""

import asyncio
import logging
import json

from sqlalchemy import select

from app.database import async_session_factory
from app.models.invoice import Invoice
from app.services.invoice_documents import (
    DocumentPayload,
    EFI_PAYMENT_EVENT,
    persist_boleto_pdf,
    read_invoice_document,
    store_invoice_document,
)
from app.utils.storage import binary_sha256, read_binary

logger = logging.getLogger(__name__)


async def backfill(batch_size: int = 25, clear_legacy_pdf: bool = True) -> dict[str, int]:
    migrated = 0
    receipts_migrated = 0
    failed = 0
    last_id = None

    while True:
        async with async_session_factory() as db:
            query = (
                select(Invoice.id, Invoice.pdf_data)
                .where(Invoice.pdf_data.is_not(None))
                .order_by(Invoice.id)
                .limit(batch_size)
            )
            if last_id is not None:
                query = query.where(Invoice.id > last_id)
            rows = (await db.execute(query)).all()
            if not rows:
                break

            for invoice_id, pdf_data in rows:
                last_id = invoice_id
                try:
                    invoice = await db.get(Invoice, invoice_id)
                    if invoice and pdf_data:
                        document = await persist_boleto_pdf(db, invoice, pdf_data, source="legacy_database_migration")
                        stored = await read_invoice_document(document)
                        if stored is None or binary_sha256(stored) != binary_sha256(pdf_data):
                            raise RuntimeError("Hash do PDF no R2 diverge do banco")
                        if clear_legacy_pdf:
                            invoice.pdf_data = None
                        migrated += 1
                except Exception:
                    failed += 1
                    logger.exception("Falha ao migrar PDF da fatura %s", invoice_id)
            await db.commit()

    async with async_session_factory() as db:
        invoices = (await db.execute(
            select(Invoice).where(Invoice.efi_payment_receipt_url.is_not(None))
        )).scalars().all()
        for invoice in invoices:
            try:
                raw = read_binary(invoice.efi_payment_receipt_url or "")
                if not raw:
                    continue
                # Confirma que o legado e JSON valido antes de classifica-lo como evento Efí.
                json.loads(raw.decode("utf-8"))
                await store_invoice_document(
                    db,
                    invoice,
                    DocumentPayload(
                        raw=raw,
                        document_type=EFI_PAYMENT_EVENT,
                        source="legacy_payment_receipt_migration",
                        original_name=f"confirmacao_efi_{str(invoice.id)[:8]}.json",
                        mime_type="application/json",
                        provider_document_id=invoice.efi_charge_id,
                    ),
                )
                receipts_migrated += 1
            except Exception:
                failed += 1
                logger.exception("Falha ao migrar comprovante Efí da fatura %s", invoice.id)
        await db.commit()

    return {"migrated": migrated, "receipts_migrated": receipts_migrated, "failed": failed}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(asyncio.run(backfill()))
