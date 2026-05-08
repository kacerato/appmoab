"""
AquaMoab - servico de visao computacional com Kimi.
"""

import json
import logging
import re

from openai import AsyncOpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

HYDROMETER_OCR_PROMPT = """Analise a imagem e extraia, com foco operacional:
1. CODIGO DE IDENTIFICACAO do hidrometro
2. LEITURA ATUAL em m3
3. CONFIANCA de 0 a 1

Regras importantes:
- Se houver um hidrometro real visivel, priorize o codigo gravado nele.
- Se nao houver um hidrometro real, mas existir um codigo numerico isolado e legivel na imagem, retorne esse codigo como fallback visual.
- Nunca escreva explicacoes fora do JSON.
- Se nao houver codigo legivel, use null.
- Se nao houver leitura legivel, use null.

Responda exclusivamente em JSON, neste formato:
{"codigo": "000001", "leitura_m3": 12345.678, "confianca": 0.95}
"""


class KimiVisionError(Exception):
    pass


class KimiVisionService:
    def __init__(self):
        if not settings.kimi_api_key:
            logger.warning("KIMI_API_KEY nao configurada")
            self._client = None
        else:
            self._client = AsyncOpenAI(
                api_key=settings.kimi_api_key,
                base_url="https://api.moonshot.ai/v1",
            )

    async def extract_hydrometer_data(self, image_base64: str) -> dict:
        if self._client is None:
            raise KimiVisionError("API Key do Kimi nao configurada")

        if not image_base64.startswith("data:"):
            image_base64 = f"data:image/jpeg;base64,{image_base64}"

        try:
            completion = await self._client.chat.completions.create(
                model="kimi-k2.6",
                messages=[
                    {"role": "system", "content": "Especialista em leitura operacional de hidrometros e codigos numericos."},
                    {
                        "role": "user",
                        "content": [
                            {"type": "image_url", "image_url": {"url": image_base64}},
                            {"type": "text", "text": HYDROMETER_OCR_PROMPT},
                        ],
                    },
                ],
                extra_body={"thinking": {"type": "disabled"}},
                max_tokens=500,
                temperature=0.6,
            )
            response_text = (completion.choices[0].message.content or "").strip()
            logger.info("Kimi OCR response: %s", response_text)
            return self._parse_response(response_text)
        except Exception as exc:
            logger.error("Kimi Vision error: %s", exc)
            raise KimiVisionError(f"Falha no OCR: {exc}") from exc

    def _parse_response(self, text: str) -> dict:
        clean = text.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:-1]).strip()

        try:
            data = self._extract_json_payload(clean)
        except json.JSONDecodeError:
            data = self._fallback_payload(clean)

        return {
            "codigo": self._safe_code(data.get("codigo")),
            "leitura_m3": self._safe_float(data.get("leitura_m3")),
            "confianca": self._safe_float(data.get("confianca"), 0.0),
        }

    def _extract_json_payload(self, text: str) -> dict:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", text)
            if not match:
                raise
            return json.loads(match.group())

    def _fallback_payload(self, text: str) -> dict:
        code_match = re.search(r'["“]?([0-9]{4,12})["”]?', text)
        confidence_match = re.search(r"([01](?:[.,]\d+)?)", text)
        confidence = 0.35 if code_match else 0.0
        if confidence_match:
          parsed_confidence = self._safe_float(confidence_match.group(1).replace(",", "."), confidence)
          if parsed_confidence is not None:
              confidence = parsed_confidence

        return {
            "codigo": code_match.group(1) if code_match else None,
            "leitura_m3": None,
            "confianca": confidence,
        }

    @staticmethod
    def _safe_code(value: object) -> str | None:
        if value is None:
            return None
        digits = "".join(char for char in str(value) if char.isdigit())
        return digits or None

    @staticmethod
    def _safe_float(value, default=None):
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default


kimi_service = KimiVisionService()
