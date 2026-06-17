from datetime import date, datetime, timezone
import unittest

from app.services.billing_policy import (
    calculate_overdue_amount,
    payment_due_date_for_provider,
    resolve_invoice_due_date,
    should_block_overdue_charges_for_late_reading,
)
from app.models.invoice import Invoice
from app.routers.invoices import _invoice_display_status
from app.schemas.reading import ReadingResponse


class BillingPolicyTest(unittest.TestCase):
    def test_due_date_stays_in_current_reference_month_after_due_day(self):
        self.assertEqual(resolve_invoice_due_date(date(2026, 6, 11), 10), date(2026, 6, 10))

    def test_provider_due_date_never_goes_to_the_past(self):
        self.assertEqual(payment_due_date_for_provider(date(2026, 6, 10), date(2026, 6, 11)), date(2026, 6, 11))

    def test_late_reading_blocks_overdue_charges(self):
        self.assertTrue(
            should_block_overdue_charges_for_late_reading(
                charge_type="water",
                invoice_due_date=date(2026, 6, 10),
                created_on=date(2026, 6, 11),
            )
        )

    def test_blocked_late_reading_keeps_amount_without_fee_or_interest(self):
        calc = calculate_overdue_amount(
            original_amount=100.0,
            custom_adjustment_amount=0.0,
            due_date=date(2026, 6, 10),
            today=date(2026, 6, 11),
            late_fee_percent=10.0,
            daily_interest_percent=0.033,
            overdue_charges_allowed=False,
        )
        self.assertEqual(calc.total_amount, 100.0)
        self.assertEqual(calc.late_fee_amount, 0.0)
        self.assertEqual(calc.interest_amount, 0.0)
        self.assertEqual(calc.days_overdue_charged, 0)
        self.assertTrue(calc.is_overdue)

    def test_allowed_overdue_applies_single_fee_and_daily_interest(self):
        calc = calculate_overdue_amount(
            original_amount=100.0,
            custom_adjustment_amount=5.0,
            due_date=date(2026, 6, 10),
            today=date(2026, 6, 12),
            late_fee_percent=10.0,
            daily_interest_percent=1.0,
            overdue_charges_allowed=True,
        )
        self.assertEqual(calc.total_amount, 117.0)
        self.assertEqual(calc.late_fee_amount, 10.0)
        self.assertEqual(calc.interest_amount, 2.0)
        self.assertEqual(calc.days_overdue_charged, 2)

    def test_future_pending_invoice_is_displayed_as_upcoming(self):
        invoice = Invoice(
            amount=100.0,
            original_amount=100.0,
            reference_month="2026-06",
            due_date=date(2026, 6, 19),
            consumption_m3=0.0,
            tariff_rate=0.0,
            status="pending",
        )

        status, label, days = _invoice_display_status(invoice, today=date(2026, 6, 17))

        self.assertEqual(status, "upcoming")
        self.assertEqual(label, "A vencer em 2 dia(s)")
        self.assertEqual(days, 2)

    def test_pending_invoice_due_today_is_not_upcoming(self):
        invoice = Invoice(
            amount=100.0,
            original_amount=100.0,
            reference_month="2026-06",
            due_date=date(2026, 6, 17),
            consumption_m3=0.0,
            tariff_rate=0.0,
            status="pending",
        )

        status, label, days = _invoice_display_status(invoice, today=date(2026, 6, 17))

        self.assertEqual(status, "due_today")
        self.assertEqual(label, "Vence hoje")
        self.assertEqual(days, 0)

    def test_reading_response_exposes_installation_marker(self):
        payload = {
            "id": "11111111-1111-1111-1111-111111111111",
            "hydrometer_id": "22222222-2222-2222-2222-222222222222",
            "collaborator_id": "33333333-3333-3333-3333-333333333333",
            "current_value": 10.0,
            "previous_value": 0.0,
            "consumption": 0.0,
            "photo_url": "/uploads/test.jpg",
            "photo_extracted_code": None,
            "photo_extracted_value": None,
            "ocr_confidence": None,
            "latitude": None,
            "longitude": None,
            "captured_at": datetime(2026, 6, 17, tzinfo=timezone.utc),
            "status": "pending",
            "rejection_reason": None,
            "approved_by": None,
            "approved_at": None,
            "created_at": datetime(2026, 6, 17, tzinfo=timezone.utc),
            "is_installation": True,
            "charge_type": "installation",
        }

        response = ReadingResponse.model_validate(payload)

        self.assertTrue(response.is_installation)
        self.assertEqual(response.charge_type, "installation")


if __name__ == "__main__":
    unittest.main()
