import unittest
from uuid import uuid4

from pydantic import ValidationError

from app.models.whatsapp_message import WhatsAppMessage
from app.routers.whatsapp_messages import _build_evolution_quote
from app.schemas.whatsapp_message import WhatsAppSendMessageRequest


class WhatsAppMessageFlowTest(unittest.TestCase):
    def test_send_message_request_requires_destination(self):
        with self.assertRaises(ValidationError):
            WhatsAppSendMessageRequest(text="Ola")

    def test_send_message_request_rejects_empty_text(self):
        with self.assertRaises(ValidationError):
            WhatsAppSendMessageRequest(phone="87981327592", text="   ")

    def test_send_message_request_accepts_quote_reference(self):
        request = WhatsAppSendMessageRequest(
            phone="87981327592",
            text="Tudo certo",
            quoted_message_id="11111111-1111-1111-1111-111111111111",
        )

        self.assertEqual(request.text, "Tudo certo")
        self.assertEqual(str(request.quoted_message_id), "11111111-1111-1111-1111-111111111111")

    def test_builds_native_evolution_quote_payload(self):
        message = WhatsAppMessage(
            id=uuid4(),
            phone="5587981327592",
            direction="inbound",
            body="Mensagem original",
            external_message_id="3EB0ABC123",
            status="received",
            payload={
                "data": {
                    "key": {
                        "id": "3EB0ABC123",
                        "remoteJid": "5587981327592@s.whatsapp.net",
                        "fromMe": False,
                    },
                    "message": {"conversation": "Mensagem original"},
                }
            },
        )

        quote = _build_evolution_quote(message)

        self.assertEqual(quote["key"]["id"], "3EB0ABC123")
        self.assertEqual(quote["key"]["remoteJid"], "5587981327592@s.whatsapp.net")
        self.assertFalse(quote["key"]["fromMe"])
        self.assertEqual(quote["message"], {"conversation": "Mensagem original"})


if __name__ == "__main__":
    unittest.main()
