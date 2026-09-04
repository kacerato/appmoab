"""Regressões da seleção manual, sem acesso ao banco ou aos provedores reais."""

import unittest
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.database import get_db
from app.models.customer import Customer
from app.models.invoice import Invoice
from app.models.notification import Notification
from app.models.reading import Reading
from app.models.system_setting import SystemSetting
from app.routers.invoices import _due_month_range, router, send_invoice_whatsapp_batch
from app.schemas.invoice import InvoiceWhatsAppBatchRequest
from app.services import invoice_whatsapp as queue
from app.utils.security import get_current_user


def make_invoice(**overrides):
    data = dict(
        id=uuid4(), customer_id=uuid4(), reading_id=None, status="sent",
        efi_status="waiting", efi_charge_id="charge-test", efi_payment_url="https://example.com/pay",
        amount=100, charge_type="water", reference_month="2026-05",
        due_date=date(2026, 5, 15), payment_due_date=date(2026, 9, 15),
        customer=Customer(name="Cliente teste", phone="87999999999"),
    )
    return Invoice(**{**data, **overrides})


def make_notification(invoice, **overrides):
    data = dict(
        id=uuid4(), invoice_id=invoice.id, customer_id=invoice.customer_id,
        channel="whatsapp", type="invoice_generated", status="queued", attempt_count=0,
        next_attempt_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        payload={"manual_requested": True, "source": "manual_batch"},
    )
    return Notification(**{**data, **overrides})


def result(value):
    response = MagicMock()
    response.scalar_one_or_none.return_value = value
    response.scalars.return_value.all.return_value = value
    response.scalar.return_value = value
    return response


def fake_db(values):
    db = MagicMock()
    db.execute = AsyncMock(side_effect=[result(value) for value in values])
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


class InvoiceSelectionTest(unittest.TestCase):
    def test_month_boundaries_and_invalid_month(self):
        self.assertEqual(_due_month_range("2026-12"), (date(2026, 12, 1), date(2027, 1, 1)))
        for month in ("2026-13", "2026-00", "invalid", "2026-08-01"):
            with self.subTest(month=month), self.assertRaises(HTTPException):
                _due_month_range(month)

    def test_batch_requires_bounded_uuid_selection(self):
        for ids in ([], [uuid4() for _ in range(101)], ["not-an-id"]):
            with self.assertRaises(ValidationError):
                InvoiceWhatsAppBatchRequest(invoice_ids=ids)

    def test_no_month_restriction_and_reading_optional_for_manual_charge(self):
        self.assertIsNone(queue.invoice_whatsapp_block_reason(make_invoice()))

    def test_closed_invoices_and_provider_payment_are_blocked(self):
        for status in ("paid", "cancelled"):
            self.assertEqual(queue.invoice_whatsapp_block_reason(make_invoice(status=status))[0], "invoice_closed")
        for provider_status in ("identified", "approved", "paid", "settled", "canceled"):
            self.assertEqual(queue.invoice_whatsapp_block_reason(make_invoice(efi_status=provider_status))[0], "charge_unavailable")

    def test_linked_reading_must_be_approved(self):
        invoice = make_invoice(reading_id=uuid4(), reading=Reading(status="pending"))
        self.assertEqual(queue.invoice_whatsapp_block_reason(invoice)[0], "reading_not_approved")
        invoice.reading.status = "approved"
        self.assertIsNone(queue.invoice_whatsapp_block_reason(invoice))

    def test_missing_charge_and_invalid_phones(self):
        self.assertEqual(queue.invoice_whatsapp_block_reason(make_invoice(efi_charge_id=None, efi_payment_url=None))[0], "boleto_missing")
        invoice = make_invoice()
        for phone, reason in ((None, "phone_missing"), ("123", "phone_invalid"), ("559999999999999999", "phone_invalid")):
            invoice.customer.phone = phone
            self.assertEqual(queue.invoice_whatsapp_block_reason(invoice)[0], reason)

    def test_overdue_is_not_a_paid_or_cancelled_charge(self):
        self.assertIsNone(queue.invoice_whatsapp_block_reason(make_invoice(status="overdue", efi_status="unpaid")))

    def test_batch_endpoint_requires_admin(self):
        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role="collaborator")
        db = fake_db([])
        app.dependency_overrides[get_db] = lambda: db
        with TestClient(app) as client:
            response = client.post("/invoices/send-whatsapp-batch", json={"invoice_ids": [str(uuid4())]})
        self.assertEqual(response.status_code, 403)
        db.execute.assert_not_called()


class InvoiceQueueTest(unittest.IsolatedAsyncioTestCase):
    async def test_manual_enqueues_when_automatic_flow_is_off(self):
        invoice = make_invoice()
        db = fake_db([None, None])
        settings = SystemSetting(notification_flows={"invoice_generated": {"enabled": False}})
        admin_id = uuid4()
        with patch.object(queue, "_settings", AsyncMock(return_value=settings)):
            automatic = await queue.enqueue_invoice_whatsapp(db, invoice, source="reading_approval")
            self.assertIsNone(automatic)
            db.execute.assert_not_called()
            manual = await queue.enqueue_invoice_whatsapp(db, invoice, source="manual_batch", manual=True, requested_by=admin_id)
        self.assertTrue(manual.payload["manual_requested"])
        self.assertEqual(manual.payload["requested_by"], str(admin_id))
        self.assertEqual(manual.status, "queued")
        self.assertIsNotNone(db.execute.call_args_list[0].args[0]._for_update_arg)

    async def test_repeated_enqueue_preserves_existing_pause(self):
        invoice = make_invoice()
        pause = datetime.now(timezone.utc) + timedelta(hours=2)
        delivery = make_notification(invoice, next_attempt_at=pause, error_message="Conta restrita")
        db = fake_db([None, delivery])
        with patch.object(queue, "_settings", AsyncMock(return_value=SystemSetting())):
            same = await queue.enqueue_invoice_whatsapp(db, invoice, source="manual_batch", manual=True)
        self.assertIs(same, delivery)
        self.assertEqual(delivery.next_attempt_at, pause)
        self.assertEqual(delivery.error_message, "Conta restrita")
        db.add.assert_not_called()

    async def test_already_sent_and_exhausted_never_create_another_delivery(self):
        invoice = make_invoice()
        for status, attempts in (("sent", 1), ("delivered", 1), ("read", 1), ("failed", queue.MAX_ATTEMPTS)):
            delivery = make_notification(invoice, status=status, attempt_count=attempts)
            db = fake_db([None, delivery])
            with patch.object(queue, "_settings", AsyncMock(return_value=SystemSetting())):
                self.assertIs(await queue.enqueue_invoice_whatsapp(db, invoice, source="manual_batch", manual=True), delivery)
            db.add.assert_not_called()

    async def test_dispatch_rechecks_paid_cancelled_and_reading_state(self):
        for invoice in (
            make_invoice(status="paid"), make_invoice(status="cancelled"),
            make_invoice(reading_id=uuid4(), reading=Reading(status="pending")),
        ):
            delivery = make_notification(invoice)
            db = fake_db([delivery, invoice])
            with patch.object(queue.whatsapp_service, "health", AsyncMock()) as health:
                response = await queue.dispatch_invoice_notification(db, delivery.id)
            self.assertEqual(response["status"], "failed")
            self.assertIsNone(delivery.next_attempt_at)
            health.assert_not_called()

    async def test_dispatch_does_not_bypass_next_attempt_time(self):
        invoice = make_invoice()
        delivery = make_notification(invoice, next_attempt_at=datetime.now(timezone.utc) + timedelta(minutes=15))
        with patch.object(queue.whatsapp_service, "health", AsyncMock()) as health:
            response = await queue.dispatch_invoice_notification(fake_db([delivery, invoice]), delivery.id)
        self.assertEqual(response["reason"], "scheduled")
        health.assert_not_called()
        self.assertEqual(delivery.attempt_count, 0)

    async def test_manual_dispatch_keeps_channel_requirement_with_flow_off(self):
        invoice = make_invoice()
        delivery = make_notification(invoice)
        settings = SystemSetting(notification_flows={"invoice_generated": {"enabled": False}})
        with patch.object(queue, "_settings", AsyncMock(return_value=settings)), patch.object(queue.whatsapp_service, "health", AsyncMock(return_value={"connected": False})):
            response = await queue.dispatch_invoice_notification(fake_db([delivery, invoice]), delivery.id)
        self.assertEqual(response["reason"], "whatsapp_disconnected")
        self.assertEqual(response["status"], "queued")
        self.assertEqual(delivery.attempt_count, 0)

    async def test_automatic_dispatch_still_respects_disabled_flow(self):
        invoice = make_invoice()
        delivery = make_notification(invoice, payload={"source": "reading_approval"})
        settings = SystemSetting(notification_flows={"invoice_generated": {"enabled": False}})
        with patch.object(queue, "_settings", AsyncMock(return_value=settings)), patch.object(queue.whatsapp_service, "health", AsyncMock()) as health:
            response = await queue.dispatch_invoice_notification(fake_db([delivery, invoice]), delivery.id)
        self.assertEqual(response["reason"], "flow_disabled")
        health.assert_not_called()

    async def test_customer_interval_and_global_rate_limit_keep_delivery_queued(self):
        for slot, customer, expected in ((False, True, "local_rate_limit"), (True, False, "customer_frequency_limit")):
            invoice = make_invoice()
            delivery = make_notification(invoice)
            with patch.object(queue, "_settings", AsyncMock(return_value=SystemSetting())), patch.object(queue.whatsapp_service, "health", AsyncMock(return_value={"connected": True})), patch.object(queue, "_reserve_dispatch_slot", AsyncMock(return_value=(slot, None))), patch.object(queue, "_customer_interval_available", AsyncMock(return_value=(customer, datetime.now(timezone.utc) + timedelta(minutes=5)))):
                response = await queue.dispatch_invoice_notification(fake_db([delivery, invoice]), delivery.id)
            self.assertEqual(response["reason"], expected)
            self.assertEqual(delivery.attempt_count, 0)

    async def test_success_uses_actual_boleto_due_date_and_customer_destination(self):
        invoice = make_invoice()
        delivery = make_notification(invoice)
        db = fake_db([delivery, invoice])
        with patch.object(queue, "_settings", AsyncMock(return_value=SystemSetting())), patch.object(queue.whatsapp_service, "health", AsyncMock(return_value={"connected": True})), patch.object(queue, "_reserve_dispatch_slot", AsyncMock(return_value=(True, None))), patch.object(queue, "_customer_interval_available", AsyncMock(return_value=(True, None))), patch.object(queue, "get_or_create_boleto_pdf", AsyncMock(return_value=None)), patch.object(queue, "render_invoice_customer_message", return_value="Mensagem") as render, patch.object(queue.whatsapp_service, "send_text", AsyncMock(return_value={"status": "sent", "message_id": "test-id"})) as send:
            response = await queue.dispatch_invoice_notification(db, delivery.id)
        self.assertEqual(response["status"], "sent")
        self.assertEqual(render.call_args.kwargs["due_date"], date(2026, 9, 15))
        self.assertEqual(send.call_args.args[0], invoice.customer.phone)
        self.assertEqual(delivery.external_message_id, "test-id")

    async def test_new_deliveries_obey_global_account_pause(self):
        db = fake_db([datetime.now(timezone.utc) + timedelta(hours=2)])
        db.get_bind.return_value.dialect.name = "test"
        available, detail = await queue._reserve_dispatch_slot(db)
        self.assertFalse(available)
        self.assertIn("restrita", detail)

    async def test_batch_deduplicates_and_commits_before_background_work(self):
        invoice = make_invoice()
        paid = make_invoice(status="paid")
        missing_id = uuid4()
        delivery = make_notification(invoice)
        db = fake_db([[invoice, paid]])
        tasks = BackgroundTasks()
        with patch("app.routers.invoices.enqueue_invoice_whatsapp", AsyncMock(return_value=delivery)) as enqueue, patch.object(queue.whatsapp_service, "send_text", AsyncMock()) as send:
            response = await send_invoice_whatsapp_batch(
                InvoiceWhatsAppBatchRequest(invoice_ids=[invoice.id, invoice.id, paid.id, missing_id]),
                tasks, db, SimpleNamespace(id=uuid4()),
            )
        self.assertEqual(len(response.items), 3)
        self.assertEqual(sum(item.status == "queued" for item in response.items), 1)
        self.assertEqual(sum(item.status == "failed" for item in response.items), 2)
        enqueue.assert_awaited_once()
        self.assertTrue(enqueue.call_args.kwargs["manual"])
        db.commit.assert_awaited_once()
        self.assertEqual(len(tasks.tasks), 1)
        send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
