import unittest
import uuid
from datetime import date

from fastapi import HTTPException

from app.models.invoice import Invoice
from app.routers.invoices import (
    _clear_efi_payment_data,
    _merge_efi_raw,
    _record_invoice_event,
    _validate_new_invoice_due_date,
)


class FakeDb:
    def __init__(self):
        self.items = []

    def add(self, item):
        self.items.append(item)


class FakeUser:
    def __init__(self):
        self.id = uuid.uuid4()


class InvoiceFlowHelperTest(unittest.TestCase):
    def test_new_manual_invoice_preserves_today_or_future_due_date(self):
        _validate_new_invoice_due_date(date(2026, 8, 3), today=date(2026, 8, 3))
        _validate_new_invoice_due_date(date(2026, 8, 20), today=date(2026, 8, 3))

    def test_new_manual_invoice_rejects_past_due_date_instead_of_replacing_it(self):
        with self.assertRaises(HTTPException) as raised:
            _validate_new_invoice_due_date(date(2026, 8, 2), today=date(2026, 8, 3))
        self.assertEqual(raised.exception.status_code, 422)

    def test_reopen_helper_clears_old_efi_payment_data(self):
        invoice = Invoice(
            id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            consumption_m3=0,
            tariff_rate=0,
            amount=150,
            original_amount=150,
            charge_type="installation",
            reference_month="2026-06",
            due_date=date(2026, 6, 19),
            status="cancelled",
            payment_provider="efi",
            payment_due_date=date(2026, 6, 19),
            efi_charge_id="123456",
            efi_status="canceled",
            efi_barcode="00190",
            efi_payment_url="https://example.com/pay",
            efi_pdf_url="https://example.com/boleto.pdf",
            efi_pix_qrcode="pix",
            efi_payment_receipt_url="https://example.com/receipt",
            pdf_data=b"pdf",
        )

        invoice.efi_raw_response = _merge_efi_raw(invoice, reopened_from_charge_id=invoice.efi_charge_id)
        _clear_efi_payment_data(invoice)

        self.assertIsNone(invoice.payment_provider)
        self.assertIsNone(invoice.payment_due_date)
        self.assertIsNone(invoice.efi_charge_id)
        self.assertIsNone(invoice.efi_status)
        self.assertIsNone(invoice.efi_barcode)
        self.assertIsNone(invoice.efi_payment_url)
        self.assertIsNone(invoice.efi_pdf_url)
        self.assertIsNone(invoice.efi_pix_qrcode)
        self.assertIsNone(invoice.efi_payment_receipt_url)
        self.assertIsNone(invoice.pdf_data)
        self.assertEqual(invoice.efi_raw_response["reopened_from_charge_id"], "123456")

    def test_record_invoice_event_keeps_financial_audit_context(self):
        db = FakeDb()
        user = FakeUser()
        invoice = Invoice(
            id=uuid.uuid4(),
            customer_id=uuid.uuid4(),
            consumption_m3=0,
            tariff_rate=0,
            amount=150,
            original_amount=150,
            charge_type="installation",
            reference_month="2026-06",
            due_date=date(2026, 6, 19),
            status="pending",
        )

        _record_invoice_event(
            db,
            invoice=invoice,
            event_type="invoice_reopened",
            previous_status="cancelled",
            new_status="pending",
            user=user,
            reason=" boleto cancelado por erro ",
            payload={"previous_efi_charge_id": "123456"},
        )

        self.assertEqual(len(db.items), 1)
        event = db.items[0]
        self.assertEqual(event.invoice_id, invoice.id)
        self.assertEqual(event.user_id, user.id)
        self.assertEqual(event.event_type, "invoice_reopened")
        self.assertEqual(event.previous_status, "cancelled")
        self.assertEqual(event.new_status, "pending")
        self.assertEqual(event.reason, "boleto cancelado por erro")
        self.assertEqual(event.payload["previous_efi_charge_id"], "123456")


if __name__ == "__main__":
    unittest.main()
