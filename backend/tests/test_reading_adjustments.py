from datetime import datetime, timezone
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

from app.models.hydrometer import Hydrometer
from app.models.invoice import Invoice
from app.models.reading import Reading
from app.routers.hydrometers import update_hydrometer
from app.schemas.hydrometer import HydrometerUpdate
from app.services.reading_adjustments import (
    ReadingAdjustmentError,
    adjust_latest_approved_reading,
)


HYDROMETER_ID = UUID("11111111-1111-1111-1111-111111111111")
USER_ID = UUID("22222222-2222-2222-2222-222222222222")


def _single(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _many(values):
    result = MagicMock()
    result.scalars.return_value.all.return_value = values
    return result


def _reading(*, current_value=103.101, invoice_status="cancelled") -> Reading:
    reading = Reading(
        hydrometer_id=HYDROMETER_ID,
        collaborator_id=USER_ID,
        current_value=current_value,
        previous_value=5.155,
        consumption=97.946,
        photo_url="reading.jpg",
        captured_at=datetime(2026, 7, 31, tzinfo=timezone.utc),
        status="approved",
        reading_kind="water",
        validation_flags=[{"code": "consumption_spike", "severity": "warning"}],
    )
    reading.invoice = Invoice(
        customer_id=USER_ID,
        reading_id=reading.id,
        consumption_m3=97.946,
        tariff_rate=14.75,
        amount=1444.70,
        reference_month="2026-07",
        due_date=datetime(2026, 7, 20).date(),
        status=invoice_status,
    )
    return reading


class ReadingAdjustmentTest(IsolatedAsyncioTestCase):
    async def test_hydrometer_patch_routes_last_value_through_history_adjustment(self):
        hydrometer = Hydrometer(
            id=HYDROMETER_ID,
            code="000020",
            last_reading_value=5.155,
            last_reading_date=datetime(2026, 7, 31, tzinfo=timezone.utc),
        )
        db = MagicMock()
        db.execute = AsyncMock(return_value=_single(hydrometer))
        db.flush = AsyncMock()

        with (
            patch(
                "app.routers.hydrometers.adjust_latest_approved_reading",
                AsyncMock(),
            ) as adjust,
            patch(
                "app.routers.hydrometers._fetch_hydrometer_response",
                AsyncMock(return_value=hydrometer),
            ),
        ):
            result = await update_hydrometer(
                str(HYDROMETER_ID),
                HydrometerUpdate(last_reading_value=5.155),
                db,
                MagicMock(id=USER_ID),
            )

        self.assertIs(result, hydrometer)
        adjust.assert_awaited_once_with(db, hydrometer, value=5.155)

    async def test_adjustment_synchronizes_history_summary_and_pending_capture(self):
        hydrometer = Hydrometer(
            id=HYDROMETER_ID,
            code="000020",
            black_digits=4,
            last_reading_value=103.101,
            last_reading_date=datetime(2026, 7, 31, tzinfo=timezone.utc),
        )
        approved = _reading()
        pending = Reading(
            hydrometer_id=HYDROMETER_ID,
            collaborator_id=USER_ID,
            current_value=None,
            previous_value=103.101,
            consumption=None,
            photo_url="pending.jpg",
            captured_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            status="pending",
        )
        db = MagicMock()
        db.execute = AsyncMock(side_effect=[_single(approved), _many([pending])])
        db.flush = AsyncMock()

        result = await adjust_latest_approved_reading(db, hydrometer, value=5.155)

        self.assertIs(result, approved)
        self.assertEqual(approved.current_value, 5.155)
        self.assertEqual(approved.consumption, 0.0)
        self.assertEqual(hydrometer.last_reading_value, 5.155)
        self.assertEqual(pending.previous_value, 5.155)
        self.assertIsNone(pending.consumption)
        self.assertIn(
            "manual_history_adjustment",
            {flag["code"] for flag in approved.validation_flags},
        )
        self.assertNotIn(
            "consumption_spike",
            {flag["code"] for flag in approved.validation_flags},
        )
        db.flush.assert_awaited_once()

    async def test_adjustment_rejects_water_reading_with_active_invoice(self):
        hydrometer = Hydrometer(
            id=HYDROMETER_ID,
            code="000020",
            black_digits=4,
            last_reading_value=103.101,
            last_reading_date=datetime(2026, 7, 31, tzinfo=timezone.utc),
        )
        approved = _reading(invoice_status="sent")
        db = MagicMock()
        db.execute = AsyncMock(return_value=_single(approved))

        with self.assertRaises(ReadingAdjustmentError) as raised:
            await adjust_latest_approved_reading(db, hydrometer, value=5.155)

        self.assertIn("cobrança ativa", str(raised.exception))
        self.assertEqual(approved.current_value, 103.101)
        self.assertEqual(hydrometer.last_reading_value, 103.101)
