from datetime import date
import unittest

from app.services.efi_api import EfiAPIError, EfiAPIService, _decode_p12_base64, _format_billet_message


class CapturingEfiService(EfiAPIService):
    def __init__(self, response: dict):
        super().__init__()
        self.response = response
        self.last_request: dict | None = None

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        self.last_request = {"method": method, "path": path, **kwargs}
        return self.response


class EfiAPIServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_emitir_cobranca_builds_bolix_one_step_payload(self):
        service = CapturingEfiService({
            "data": {
                "charge_id": 123,
                "status": "waiting",
                "billet_link": "https://cobrancas-h.api.efipay.com.br/boleto/123",
                "payment": {
                    "banking_billet": {
                        "barcode": "00190",
                        "pdf": {"charge": "https://example.com/boleto.pdf"},
                        "pix": {"qrcode": "pix-copia-e-cola"},
                    }
                },
            }
        })

        result = await service.emitir_cobranca(
            valor=100.50,
            cpf_cnpj="123.456.789-09",
            nome="Cliente Teste",
            email="cliente@example.com",
            telefone="(87) 98132-7592",
            endereco="Rua A",
            numero="10",
            bairro="Centro",
            cidade="Petrolina",
            uf="PE",
            cep="56300-000",
            data_vencimento=date(2026, 6, 30),
            seu_numero="AQ-12345678",
            mensagem="Fatura mensal AquaMoab",
            multa_percentual=10.0,
            juros_diario_percentual=0.033,
        )

        self.assertEqual(result["charge_id"], "123")
        self.assertEqual(result["status"], "waiting")
        self.assertEqual(result["barcode"], "00190")
        self.assertEqual(result["payment_url"], "https://cobrancas-h.api.efipay.com.br/boleto/123")
        self.assertEqual(result["pdf_url"], "https://example.com/boleto.pdf")
        self.assertEqual(result["pix_qrcode"], "pix-copia-e-cola")

        assert service.last_request is not None
        self.assertEqual(service.last_request["method"], "POST")
        self.assertEqual(service.last_request["path"], "/v1/charge/one-step")
        payload = service.last_request["json"]
        self.assertEqual(payload["items"][0]["value"], 10050)
        self.assertEqual(payload["items"][0]["amount"], 1)
        self.assertEqual(payload["metadata"]["custom_id"], "AQ-12345678")
        billet = payload["payment"]["banking_billet"]
        self.assertEqual(billet["expire_at"], "2026-06-30")
        self.assertEqual(billet["customer"]["cpf"], "12345678909")
        self.assertEqual(billet["customer"]["phone_number"], "87981327592")
        self.assertEqual(billet["customer"]["address"]["zipcode"], "56300000")
        self.assertEqual(billet["configurations"]["fine"], 1000)
        self.assertEqual(billet["configurations"]["interest"], 33)

    async def test_emitir_cobranca_rejects_invalid_customer_contract_before_api_call(self):
        service = CapturingEfiService({"data": {}})

        with self.assertRaises(EfiAPIError) as ctx:
            await service.emitir_cobranca(
                valor=50.0,
                cpf_cnpj="123",
                nome="Cliente Teste",
                email="",
                telefone=None,
                endereco="Rua A",
                numero="10",
                bairro="Centro",
                cidade="Petrolina",
                uf="PE",
                cep="56300-000",
                data_vencimento=date(2026, 6, 30),
                seu_numero="AQ-12345678",
            )

        self.assertIn("CPF/CNPJ", str(ctx.exception))
        self.assertIsNone(service.last_request)

    def test_normalizes_charge_response_when_payment_is_string(self):
        service = EfiAPIService()

        result = service._normalize_charge_response({
            "data": {
                "charge_id": 456,
                "status": "waiting",
                "payment": "banking_billet",
                "barcode": "00190",
                "payment_url": "https://example.com/pay",
            }
        })

        self.assertEqual(result["charge_id"], "456")
        self.assertEqual(result["status"], "waiting")
        self.assertEqual(result["barcode"], "00190")
        self.assertEqual(result["payment_url"], "https://example.com/pay")

    async def test_listar_cobrancas_uses_efi_billet_charge_type(self):
        service = CapturingEfiService({"data": [{"id": 1, "status": "waiting"}]})

        charges = await service.listar_cobrancas(
            statuses=["waiting"],
            begin_date=date(2026, 6, 16),
            end_date=date(2026, 6, 30),
        )

        self.assertEqual(len(charges), 1)
        assert service.last_request is not None
        self.assertEqual(service.last_request["method"], "GET")
        self.assertEqual(service.last_request["path"], "/v1/charges")
        self.assertEqual(service.last_request["params"]["charge_type"], "billet")
        self.assertEqual(service.last_request["params"]["status"], "waiting")

    def test_billet_message_is_limited_to_four_lines_of_one_hundred_chars(self):
        message = _format_billet_message("x" * 450)
        lines = message.splitlines()

        self.assertEqual(len(lines), 4)
        self.assertTrue(all(len(line) <= 100 for line in lines))
        self.assertEqual(sum(len(line) for line in lines), 400)

    def test_decodes_p12_base64_with_whitespace(self):
        self.assertEqual(_decode_p12_base64(" YWJjZA==\n"), b"abcd")


if __name__ == "__main__":
    unittest.main()
