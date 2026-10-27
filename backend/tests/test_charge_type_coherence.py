import unittest
from datetime import date
from types import SimpleNamespace

from app.routers.customers import BILLING_CYCLE_CHARGE_TYPES
from app.routers.invoices import _invoice_charge_message, _manual_invoice_charge_type
from app.services.billing_policy import should_block_overdue_charges_for_late_reading
from app.services.notification_templates import render_invoice_customer_message


class ManualChargeTypeTest(unittest.TestCase):
    def test_manual_charge_type_is_preserved_without_reading(self):
        self.assertEqual(_manual_invoice_charge_type(None, "manual"), "manual")

    def test_reading_without_installation_kind_becomes_water(self):
        reading = SimpleNamespace(reading_kind="water")
        self.assertEqual(_manual_invoice_charge_type(reading, "manual"), "water")

    def test_installation_reading_overrides_requested_type(self):
        reading = SimpleNamespace(reading_kind="installation")
        self.assertEqual(_manual_invoice_charge_type(reading, "manual"), "installation")


class FixedChargeTypeTest(unittest.TestCase):
    def test_fixed_rate_belongs_to_the_monthly_billing_cycle(self):
        self.assertIn("fixed", BILLING_CYCLE_CHARGE_TYPES)

    def test_fixed_rate_never_blocks_overdue_charges_for_late_reading(self):
        """A taxa fixa nao tem leitura, logo a regra de leitura atrasada nao se aplica."""
        self.assertFalse(
            should_block_overdue_charges_for_late_reading(
                charge_type="fixed",
                invoice_due_date=date(2026, 6, 10),
                created_on=date(2026, 6, 30),
            )
        )

    def test_fixed_charge_has_its_own_provider_message(self):
        invoice = SimpleNamespace(charge_type="fixed", reference_month="2026-06")
        self.assertEqual(_invoice_charge_message(invoice), "Taxa fixa mensal - Ref: 2026-06")

    def test_fixed_charge_has_its_own_customer_message(self):
        message = render_invoice_customer_message(
            None,
            charge_type="fixed",
            customer_name="Maria",
            amount=100.0,
            due_date=date(2026, 6, 10),
            reference_month="2026-06",
        )
        self.assertIn("taxa fixa mensal", message)
        self.assertIn("2026-06", message)
        self.assertIn("10/06/2026", message)


class ManualChargeMessageTest(unittest.TestCase):
    def test_manual_charge_keeps_avulsa_wording(self):
        invoice = SimpleNamespace(charge_type="manual", reference_month="2026-06")
        self.assertEqual(_invoice_charge_message(invoice), "Cobranca avulsa - Ref: 2026-06")


if __name__ == "__main__":
    unittest.main()
