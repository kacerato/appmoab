import unittest
from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError

from app.models.whatsapp_message import WhatsAppMessage
from app.routers.whatsapp_messages import (
    _build_evolution_quote,
    _conversation_phone,
    _extract_media_entry,
    _extract_media_entry_with_key,
    _find_media_base64,
    _message_response,
    _media_data_uri,
)
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

    def test_extracts_sticker_media_entry(self):
        media_entry = _extract_media_entry({
            "stickerMessage": {
                "mimetype": "image/webp",
                "fileName": "figurinha.webp",
            }
        })

        self.assertIsNotNone(media_entry)
        media_type, fallback_mime, media = media_entry
        self.assertEqual(media_type, "sticker")
        self.assertEqual(fallback_mime, "image/webp")
        self.assertEqual(media["fileName"], "figurinha.webp")

    def test_extracts_document_media_entry_with_key(self):
        media_entry = _extract_media_entry_with_key({
            "documentMessage": {
                "mimetype": "application/pdf",
                "fileName": "boleto.pdf",
                "url": "/uploads/boleto.pdf",
            }
        })

        self.assertIsNotNone(media_entry)
        media_key, media_type, fallback_mime, media = media_entry
        self.assertEqual(media_key, "documentMessage")
        self.assertEqual(media_type, "document")
        self.assertEqual(fallback_mime, "application/octet-stream")
        self.assertEqual(media["url"], "/uploads/boleto.pdf")

    def test_finds_nested_media_base64_and_builds_data_uri(self):
        encoded = "a" * 120
        payload = {"payload": {"message": {"stickerMessage": {"base64": encoded}}}}

        self.assertEqual(_find_media_base64(payload), encoded)
        self.assertEqual(_media_data_uri(encoded, "image/webp"), f"data:image/webp;base64,{encoded}")

    def test_conversation_phone_normalizes_to_single_thread_key(self):
        self.assertEqual(_conversation_phone("(87) 98132-7592"), "5587981327592")
        self.assertEqual(_conversation_phone("87981327592"), "5587981327592")
        self.assertEqual(_conversation_phone("5587981327592"), "5587981327592")

    def test_message_response_returns_normalized_phone(self):
        message = WhatsAppMessage(
            id=uuid4(),
            phone="87981327592",
            direction="outbound",
            body="Arquivo enviado: boleto.pdf",
            external_message_id="MSG123",
            status="sent",
            payload={"message": {"documentMessage": {"fileName": "boleto.pdf"}}},
            created_at=datetime.now(timezone.utc),
        )

        response = _message_response(message)

        self.assertEqual(response.phone, "5587981327592")
        self.assertEqual(response.body, "Arquivo enviado: boleto.pdf")


if __name__ == "__main__":
    unittest.main()
