import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.hydrometer import Hydrometer
from app.models.notification import Notification
from app.routers.readings import _evaluate_location
from app.schemas.reading import ReadingApprove, ReadingResponse
from app.services.invoice_whatsapp import MAX_ATTEMPTS, _schedule_retry
from app.services.whatsapp_api import WhatsAppService


class DashboardReadingContractTest(unittest.TestCase):
    def test_pending_capture_has_no_official_value_or_consumption(self):
        response = ReadingResponse.model_validate({
            "id": "11111111-1111-1111-1111-111111111111",
            "hydrometer_id": "22222222-2222-2222-2222-222222222222",
            "collaborator_id": "33333333-3333-3333-3333-333333333333",
            "current_value": None,
            "previous_value": 12.0,
            "consumption": None,
            "photo_url": "/uploads/test.jpg",
            "photo_extracted_code": "0012450",
            "photo_extracted_value": 12.45,
            "ocr_confidence": 0.91,
            "latitude": None,
            "longitude": None,
            "captured_at": datetime(2026, 7, 21, tzinfo=timezone.utc),
            "status": "pending",
            "rejection_reason": None,
            "approved_by": None,
            "approved_at": None,
            "created_at": datetime(2026, 7, 21, tzinfo=timezone.utc),
        })

        self.assertIsNone(response.current_value)
        self.assertIsNone(response.consumption)

    def test_dashboard_approval_accepts_confirmed_value_and_reason(self):
        request = ReadingApprove(current_value=12.451, adjustment_reason="Digito em transicao")

        self.assertEqual(request.current_value, 12.451)
        self.assertEqual(request.adjustment_reason, "Digito em transicao")

    def test_far_capture_is_marked_for_blocked_review(self):
        hydrometer = Hydrometer(
            latitude=-8.0000,
            longitude=-40.0000,
            allowed_radius_meters=80,
            location_required=True,
        )

        status, distance, flags = _evaluate_location(
            hydrometer=hydrometer,
            latitude=-8.0100,
            longitude=-40.0100,
            location_accuracy_meters=8,
        )

        self.assertEqual(status, "blocked_review")
        self.assertGreater(distance, 320)
        self.assertIn("location_far", {flag["code"] for flag in flags})

    def test_failed_delivery_gets_bounded_retry(self):
        notification = Notification(attempt_count=1, status="queued")

        _schedule_retry(notification, "Evolution desconectada")

        self.assertEqual(notification.status, "failed")
        self.assertIsNotNone(notification.next_attempt_at)
        self.assertEqual(notification.error_message, "Evolution desconectada")

        notification.attempt_count = MAX_ATTEMPTS
        _schedule_retry(notification, "Ainda desconectada")
        self.assertIsNone(notification.next_attempt_at)


class WhatsAppHealthTest(unittest.IsolatedAsyncioTestCase):
    async def test_health_reports_real_closed_instance(self):
        response = MagicMock()
        response.content = b'{"instance":{"state":"close"}}'
        response.json.return_value = {"instance": {"state": "close"}}
        response.raise_for_status.return_value = None
        client = AsyncMock()
        client.get.return_value = response
        service = WhatsAppService()

        with (
            patch("app.services.whatsapp_api.settings.whatsapp_enabled", True),
            patch("app.services.whatsapp_api.settings.evolution_api_url", "https://evolution.example"),
            patch("app.services.whatsapp_api.settings.evolution_api_key", "secret"),
            patch("app.services.whatsapp_api.settings.evolution_instance_name", "AquaMoab"),
            patch.object(service, "_get_client", AsyncMock(return_value=client)),
        ):
            health = await service.health()

        self.assertTrue(health["reachable"])
        self.assertFalse(health["connected"])
        self.assertEqual(health["instance_state"], "close")


if __name__ == "__main__":
    unittest.main()
