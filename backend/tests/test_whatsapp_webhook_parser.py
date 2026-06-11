import unittest

from app.routers.webhooks import (
    _event_items,
    _extract_message_body,
    _map_delivery_status,
    _normalize_evolution_event,
    _normalize_webhook_phone,
)


class WhatsAppWebhookParserTest(unittest.TestCase):
    def test_normalizes_evolution_event_names(self):
        self.assertEqual(_normalize_evolution_event("MESSAGES_UPSERT"), "messages.upsert")
        self.assertEqual(_normalize_evolution_event("messages.update"), "messages.update")

    def test_extracts_text_from_supported_message_shapes(self):
        self.assertEqual(
            _extract_message_body({"message": {"conversation": "Ola"}}),
            "Ola",
        )
        self.assertEqual(
            _extract_message_body({"message": {"extendedTextMessage": {"text": "Resposta do cliente"}}}),
            "Resposta do cliente",
        )
        self.assertEqual(
            _extract_message_body({"message": {"documentMessage": {"fileName": "comprovante.pdf"}}}),
            "Documento recebido: comprovante.pdf",
        )

    def test_maps_delivery_statuses(self):
        self.assertEqual(_map_delivery_status("DELIVERY_ACK"), "delivered")
        self.assertEqual(_map_delivery_status("READ"), "read")
        self.assertEqual(_map_delivery_status("FAILED"), "failed")

    def test_normalizes_phone_from_remote_jid(self):
        self.assertEqual(_normalize_webhook_phone("87981327592@s.whatsapp.net"), "5587981327592")
        self.assertEqual(_normalize_webhook_phone("5587981327592@s.whatsapp.net"), "5587981327592")

    def test_iterates_single_or_multiple_data_items(self):
        self.assertEqual(_event_items({"data": {"id": "1"}}), [{"id": "1"}])
        self.assertEqual(_event_items({"data": [{"id": "1"}, {"id": "2"}]}), [{"id": "1"}, {"id": "2"}])
        self.assertEqual(_event_items({"data": None}), [])


if __name__ == "__main__":
    unittest.main()
