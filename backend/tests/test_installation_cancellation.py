from datetime import date, datetime, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from app.models.customer import Customer
from app.models.hydrometer import Hydrometer
from app.models.invoice import Invoice
from app.models.reading import Reading
from app.models.reading_cycle import ReadingCycle
from app.models.user import User
from app.routers.invoices import _mark_invoice_cancelled, _reverse_linked_reading


class InstallationCancellationTest(IsolatedAsyncioTestCase):
    def test_cancel_without_preserving_keeps_cycle_open_for_recapture(self):
        cycle = ReadingCycle(status="recapture_required")
        invoice = Invoice(status="sent")
        invoice.cycle = cycle

        _mark_invoice_cancelled(invoice, preserve_reading=False)

        self.assertEqual(invoice.status, "cancelled")
        self.assertEqual(cycle.status, "recapture_required")

    def test_cancel_preserving_reading_closes_only_the_billing_cycle(self):
        cycle = ReadingCycle(status="invoiced")
        invoice = Invoice(status="sent")
        invoice.cycle = cycle

        _mark_invoice_cancelled(invoice, preserve_reading=True)

        self.assertEqual(invoice.status, "cancelled")
        self.assertEqual(cycle.status, "invoice_cancelled")

    async def test_reversing_first_reading_reopens_installation_and_removes_baseline(self):
        customer_id = UUID("11111111-1111-1111-1111-111111111111")
        hydrometer_id = UUID("22222222-2222-2222-2222-222222222222")
        reading_id = UUID("33333333-3333-3333-3333-333333333333")
        cycle_id = UUID("44444444-4444-4444-4444-444444444444")
        invoice_id = UUID("55555555-5555-5555-5555-555555555555")
        admin_id = UUID("66666666-6666-6666-6666-666666666666")

        customer = Customer(id=customer_id, due_day=20)
        hydrometer = Hydrometer(
            id=hydrometer_id,
            customer_id=customer_id,
            code="000001",
            last_reading_value=90.645,
            last_reading_date=datetime(2026, 7, 27, tzinfo=timezone.utc),
        )
        hydrometer.customer = customer
        cycle = ReadingCycle(
            id=cycle_id,
            customer_id=customer_id,
            hydrometer_id=hydrometer_id,
            reference_month="2026-07",
            due_date=date(2026, 7, 20),
            cycle_type="water",
            status="invoice_cancelled",
        )
        reading = Reading(
            id=reading_id,
            hydrometer_id=hydrometer_id,
            collaborator_id=admin_id,
            current_value=90.645,
            previous_value=0.0,
            consumption=90.645,
            photo_url="reading.jpg",
            captured_at=datetime(2026, 7, 27, tzinfo=timezone.utc),
            status="approved",
            reading_kind="water",
            reference_month="2026-07",
        )
        reading.hydrometer = hydrometer
        reading.cycle = cycle
        invoice = Invoice(
            id=invoice_id,
            customer_id=customer_id,
            reading_id=reading_id,
            cycle_id=cycle_id,
            consumption_m3=0,
            tariff_rate=0,
            amount=5.01,
            reference_month="2026-07",
            due_date=date(2026, 7, 20),
            status="cancelled",
            charge_type="installation",
        )
        invoice.reading = reading
        invoice.cycle = cycle
        admin = User(id=admin_id, role="admin", is_active=True)

        no_later_reading = MagicMock()
        no_later_reading.scalar_one_or_none.return_value = None
        no_prior_reading = MagicMock()
        no_prior_reading.scalar_one_or_none.return_value = None
        no_future_cycles = MagicMock()
        no_future_cycles.scalars.return_value.unique.return_value.all.return_value = []
        db = MagicMock()
        db.execute = AsyncMock(
            side_effect=[no_later_reading, no_prior_reading, no_future_cycles]
        )

        async def promote(_, target):
            target.cycle_type = "installation"
            return target

        with patch(
            "app.routers.invoices.promote_cycle_to_installation",
            side_effect=promote,
        ):
            await _reverse_linked_reading(
                db,
                invoice=invoice,
                admin=admin,
                reason="Valor da instalação emitido incorretamente",
            )

        self.assertEqual(reading.status, "rejected")
        self.assertEqual(reading.reading_kind, "installation")
        self.assertEqual(cycle.cycle_type, "installation")
        self.assertEqual(cycle.status, "recapture_required")
        self.assertIsNone(hydrometer.last_reading_date)
        self.assertEqual(hydrometer.last_reading_value, 0.0)
