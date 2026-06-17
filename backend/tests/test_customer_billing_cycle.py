import unittest
from datetime import date, datetime, timezone

from app.models.customer import Customer
from app.routers.customers import _next_due_date


class CustomerBillingCycleTest(unittest.TestCase):
    def test_customer_created_this_month_starts_regular_billing_next_month(self):
        customer = Customer(
            name="Cliente Novo",
            cpf_cnpj="12345678909",
            address="Rua A",
            neighborhood="Centro",
            city="Petrolina",
            state="PE",
            zip_code="56300000",
            due_day=19,
            created_at=datetime(2026, 6, 17, tzinfo=timezone.utc),
        )

        self.assertEqual(_next_due_date(customer, date(2026, 6, 17)), date(2026, 7, 19))

    def test_existing_customer_keeps_current_month_due_date_when_still_open(self):
        customer = Customer(
            name="Cliente Antigo",
            cpf_cnpj="12345678909",
            address="Rua A",
            neighborhood="Centro",
            city="Petrolina",
            state="PE",
            zip_code="56300000",
            due_day=19,
            created_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        )

        self.assertEqual(_next_due_date(customer, date(2026, 6, 17)), date(2026, 6, 19))


if __name__ == "__main__":
    unittest.main()
