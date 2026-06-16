import unittest

from app.services.glm_ocr import GlmOcrService, _strip_data_uri_prefix


class GlmOcrServiceTest(unittest.TestCase):
    def test_extracts_text_from_markdown_and_layout_details(self):
        service = GlmOcrService()

        text = service._extract_text({
            "md_results": "HID 000123",
            "layout_details": [[{"content": "0090600"}]],
        })

        self.assertIn("HID 000123", text)
        self.assertIn("0090600", text)

    def test_parses_hydrometer_reading_with_three_red_digits(self):
        service = GlmOcrService()

        result = service._parse_text("Codigo 000123\nLeitura 0090600")

        self.assertEqual(result["codigo"], "000123")
        self.assertEqual(result["leitura_m3"], 90.6)
        self.assertEqual(result["digitos_vermelhos"], 3)

    def test_parses_decimal_reading_when_present(self):
        service = GlmOcrService()

        result = service._parse_text("Hidrometro 000123 leitura 90.600")

        self.assertEqual(result["leitura_m3"], 90.6)

    def test_strips_data_uri_before_calling_glm(self):
        self.assertEqual(_strip_data_uri_prefix("data:image/png;base64,abc123"), "abc123")
        self.assertEqual(_strip_data_uri_prefix("abc123"), "abc123")


if __name__ == "__main__":
    unittest.main()
