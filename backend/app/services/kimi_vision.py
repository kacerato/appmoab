"""
AquaMoab — Serviço de Visão Computacional (Kimi K2.6).
Processa fotos de hidrômetros e extrai código + leitura via OCR.
"""

import json
import logging
import re

from openai import AsyncOpenAI
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

HYDROMETER_OCR_PROMPT = """Analise esta foto de um hidrômetro de água e extraia:
1. CÓDIGO DE IDENTIFICAÇÃO (número de série gravado no corpo)
2. LEITURA ATUAL em m³ (números do mostrador)
3. CONFIANÇA de 0 a 1

Responda EXCLUSIVAMENTE em JSON:
{"codigo": "ABC123456", "leitura_m3": 12345.678, "confianca": 0.95}
Se não conseguir ler, use null e confianca < 0.5."""


class KimiVisionError(Exception):
    pass


class KimiVisionService:
    def __init__(self):
        if not settings.kimi_api_key:
            logger.warning("KIMI_API_KEY não configurada")
            self._client = None
        else:
            self._client = AsyncOpenAI(
                api_key=settings.kimi_api_key,
                base_url="https://api.moonshot.ai/v1",
            )

    async def extract_hydrometer_data(self, image_base64: str) -> dict:
        if self._client is None:
            raise KimiVisionError("API Key do Kimi não configurada")

        if not image_base64.startswith("data:"):
            image_base64 = f"data:image/jpeg;base64,{image_base64}"

        try:
            completion = await self._client.chat.completions.create(
                model="kimi-k2.6",
                messages=[
                    {"role": "system", "content": "Especialista em leitura de hidrômetros."},
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
                temperature=0.1,
            )
            response_text = completion.choices[0].message.content.strip()
            logger.info(f"Kimi OCR response: {response_text}")
            return self._parse_response(response_text)
        except Exception as e:
            logger.error(f"Kimi Vision error: {e}")
            raise KimiVisionError(f"Falha no OCR: {str(e)}")

    def _parse_response(self, text: str) -> dict:
        clean = text.strip()
        if clean.startswith("```"):
            clean = "\n".join(clean.split("\n")[1:-1])
        try:
            data = json.loads(clean)
        except json.JSONDecodeError:
            match = re.search(r"\{[^}]+\}", clean)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return {"codigo": None, "leitura_m3": None, "confianca": 0.0}
            else:
                return {"codigo": None, "leitura_m3": None, "confianca": 0.0}

        return {
            "codigo": data.get("codigo"),
            "leitura_m3": self._safe_float(data.get("leitura_m3")),
            "confianca": self._safe_float(data.get("confianca"), 0.0),
        }

    @staticmethod
    def _safe_float(value, default=None):
        if value is None:
            return default
        try:
            return float(value)
        except (ValueError, TypeError):
            return default


kimi_service = KimiVisionService()
