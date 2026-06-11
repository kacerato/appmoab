import unittest

from pydantic import ValidationError

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


if __name__ == "__main__":
    unittest.main()
