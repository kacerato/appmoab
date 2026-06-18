"""Persistencia e recuperacao do dossie documental das faturas."""

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.invoice import Invoice
from app.models.invoice_document import InvoiceDocument
from app.utils.storage import binary_sha256, read_binary, save_binary


BOLETO_PDF = "boleto_pdf"
EFI_PAYMENT_EVENT = "efi_payment_event"
PAYMENT_RECEIPT_UPLOAD = "payment_receipt_upload"
PAYMENT_CONFIRMATION_PDF = "payment_confirmation_pdf"

ALLOWED_UPLOAD_TYPES = {PAYMENT_RECEIPT_UPLOAD, PAYMENT_CONFIRMATION_PDF}


@dataclass(frozen=True)
class DocumentPayload:
    raw: bytes
    document_type: str
    source: str
    original_name: str
    mime_type: str
    provider_document_id: str | None = None
    metadata: dict | None = None
    notes: str | None = None


def _extension_for_mime(mime_type: str) -> str:
    return {
        "application/pdf": "pdf",
        "application/json": "json",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(mime_type, "bin")


def _storage_key(invoice: Invoice, document_id: uuid.UUID, payload: DocumentPayload) -> str:
    folder = {
        BOLETO_PDF: "boleto",
        EFI_PAYMENT_EVENT: "payment-events",
        PAYMENT_RECEIPT_UPLOAD: "receipts",
        PAYMENT_CONFIRMATION_PDF: "receipts",
    }.get(payload.document_type, "other")
    extension = _extension_for_mime(payload.mime_type)
    return f"billing/{invoice.customer_id}/{invoice.id}/{folder}/{document_id}.{extension}"


async def store_invoice_document(
    db: AsyncSession,
    invoice: Invoice,
    payload: DocumentPayload,
) -> InvoiceDocument:
    sha256 = binary_sha256(payload.raw)
    existing_result = await db.execute(
        select(InvoiceDocument).where(
            InvoiceDocument.invoice_id == invoice.id,
            InvoiceDocument.document_type == payload.document_type,
            InvoiceDocument.sha256 == sha256,
        )
    )
    existing = existing_result.scalar_one_or_none()
    if existing:
        return existing

    document_id = uuid.uuid4()
    object_key = await asyncio.to_thread(
        save_binary,
        payload.raw,
        _storage_key(invoice, document_id, payload),
        payload.mime_type,
    )
    document = InvoiceDocument(
        id=document_id,
        invoice_id=invoice.id,
        customer_id=invoice.customer_id,
        document_type=payload.document_type,
        source=payload.source,
        object_key=object_key,
        original_name=payload.original_name,
        mime_type=payload.mime_type,
        size_bytes=len(payload.raw),
        sha256=sha256,
        provider_document_id=payload.provider_document_id,
        metadata_json=payload.metadata,
        notes=payload.notes,
    )
    db.add(document)
    await db.flush()
    return document


async def latest_invoice_document(
    db: AsyncSession,
    invoice_id: uuid.UUID,
    document_type: str,
) -> InvoiceDocument | None:
    result = await db.execute(
        select(InvoiceDocument)
        .where(
            InvoiceDocument.invoice_id == invoice_id,
            InvoiceDocument.document_type == document_type,
        )
        .order_by(InvoiceDocument.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def read_invoice_document(document: InvoiceDocument) -> bytes | None:
    return await asyncio.to_thread(read_binary, document.object_key)


async def persist_boleto_pdf(
    db: AsyncSession,
    invoice: Invoice,
    raw: bytes,
    *,
    source: str = "efi_api",
) -> InvoiceDocument:
    if not raw.startswith(b"%PDF"):
        raise ValueError("O arquivo retornado pela Efí não é um PDF válido")
    return await store_invoice_document(
        db,
        invoice,
        DocumentPayload(
            raw=raw,
            document_type=BOLETO_PDF,
            source=source,
            original_name=f"boleto_{str(invoice.id)[:8]}.pdf",
            mime_type="application/pdf",
            provider_document_id=invoice.efi_charge_id,
            metadata={"efi_pdf_url_present": bool(invoice.efi_pdf_url)},
        ),
    )


async def get_or_create_boleto_pdf(
    db: AsyncSession,
    invoice: Invoice,
    fetch_pdf: Callable[[str], Awaitable[bytes | None]],
    *,
    source: str,
) -> bytes | None:
    document = await latest_invoice_document(db, invoice.id, BOLETO_PDF)
    if document and (
        not invoice.efi_charge_id
        or not document.provider_document_id
        or document.provider_document_id == invoice.efi_charge_id
    ):
        raw = await read_invoice_document(document)
        if raw:
            return raw

    legacy_result = await db.execute(select(Invoice.pdf_data).where(Invoice.id == invoice.id))
    legacy_pdf = legacy_result.scalar_one_or_none()
    if legacy_pdf:
        await persist_boleto_pdf(db, invoice, legacy_pdf, source="legacy_database_migration")
        return legacy_pdf

    if not invoice.efi_pdf_url:
        return None
    raw = await fetch_pdf(invoice.efi_pdf_url)
    if raw:
        await persist_boleto_pdf(db, invoice, raw, source=source)
    return raw


def validate_receipt_upload(raw: bytes, mime_type: str) -> None:
    if mime_type == "application/pdf" and raw.startswith(b"%PDF"):
        return
    if mime_type == "image/jpeg" and raw.startswith(b"\xff\xd8\xff"):
        return
    if mime_type == "image/png" and raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return
    if mime_type == "image/webp" and len(raw) >= 12 and raw[:4] == b"RIFF" and raw[8:12] == b"WEBP":
        return
    raise ValueError("Conteúdo do arquivo não corresponde ao tipo PDF/JPEG/PNG/WEBP informado")
