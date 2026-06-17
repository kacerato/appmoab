import unittest

from app.routers.dashboard import _issue


class DashboardOperationalIssuesTest(unittest.TestCase):
    def test_issue_payload_has_required_fields_for_frontend(self):
        issue = _issue(
            code="active_invoice_without_charge",
            title="Fatura ativa sem boleto/link",
            detail="Cliente Teste - 2026-06",
            severity="warning",
            href="/faturas/11111111-1111-1111-1111-111111111111",
        )

        self.assertEqual(issue["code"], "active_invoice_without_charge")
        self.assertEqual(issue["title"], "Fatura ativa sem boleto/link")
        self.assertEqual(issue["detail"], "Cliente Teste - 2026-06")
        self.assertEqual(issue["severity"], "warning")
        self.assertEqual(issue["href"], "/faturas/11111111-1111-1111-1111-111111111111")


if __name__ == "__main__":
    unittest.main()
