"""AquaMoab - OCR de hidrometros via GLM-OCR."""

import json
import logging
import re
from typing import Any
from uuid import uuid4

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class GlmOcrError(Exception):
    pass


class GlmOcrService:
    def __init__(self) -> None:
        self._api_key = settings.glm_api_key
        self._base_url = "https://api.z.ai/api/paas/v4"
        if not self._api_key:
            logger.warning("GLM_API_KEY nao configurada")

    async def extract_hydrometer_data(self, image_base64: str) -> dict:
        if not self._api_key:
            raise GlmOcrError("API Key do GLM nao configurada")

        file_value = _strip_data_uri_prefix(image_base64)
        payload = {
            "model": "glm-ocr",
            "file": file_value,
            "request_id": f"aqmoab-{uuid4().hex[:24]}",
            "user_id": "aquamoab-ocr",
        }

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                response = await client.post(
                    f"{self._base_url}/layout_parsing",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPStatusError as exc:
            detail = _safe_json(exc.response)
            logger.error("GLM OCR HTTP error: %s", detail)
            raise GlmOcrError(f"Falha no GLM-OCR: HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            logger.error("GLM OCR error: %s", exc)
            raise GlmOcrError(f"Falha no GLM-OCR: {exc}") from exc

        text = self._extract_text(data)
        logger.info("GLM OCR text: %s", text[:600])
        return self._parse_text(text)

    def _extract_text(self, data: dict[str, Any]) -> str:
        parts: list[str] = []
        md_results = data.get("md_results")
        if isinstance(md_results, str):
            parts.append(md_results)

        layout_details = data.get("layout_details")
        if isinstance(layout_details, list):
            for page in layout_details:
                if not isinstance(page, list):
                    continue
                for item in page:
                    if isinstance(item, dict) and isinstance(item.get("content"), str):
                        parts.append(item["content"])

        return "\n".join(part for part in parts if part.strip()).strip()

    def _parse_text(self, text: str) -> dict:
        normalized = text.replace(",", ".")
        digit_runs = re.findall(r"\d{3,12}", normalized)
        decimal_values = [
            self._safe_float(match)
            for match in re.findall(r"\d{1,7}\.\d{1,4}", normalized)
        ]
        decimal_values = [value for value in decimal_values if value is not None]

        code = self._select_code(normalized, digit_runs)
        reading = self._select_reading(normalized, digit_runs, code, decimal_values)
        confidence = 0.7 if code or reading is not None else 0.0

        return {
            "codigo": code,
            "leitura_m3": reading,
            "confianca": confidence,
            "digitos_vermelhos": self._infer_red_digits(digit_runs),
            "digitos_pretos": None,
            "raw_text": text,
        }

    def _select_code(self, text: str, digit_runs: list[str]) -> str | None:
        keyword_match = re.search(r"(?:codigo|código|cod\.?)\D{0,24}(\d{3,12})", text, re.IGNORECASE)
        if keyword_match:
            return keyword_match.group(1)
        if not digit_runs:
            return None
        candidates = sorted(digit_runs, key=lambda value: (-len(value), digit_runs.index(value)))
        return candidates[0]

    def _select_reading(
        self,
        text: str,
        digit_runs: list[str],
        code: str | None,
        decimal_values: list[float],
    ) -> float | None:
        keyword_decimal = re.search(r"(?:leitura|visor|atual)\D{0,24}(\d{1,7}\.\d{1,4})", text, re.IGNORECASE)
        if keyword_decimal:
            return self._safe_float(keyword_decimal.group(1))

        keyword_digits = re.search(r"(?:leitura|visor|atual)\D{0,24}(\d{5,12})", text, re.IGNORECASE)
        if keyword_digits:
            return int(keyword_digits.group(1)) / 1000

        if decimal_values:
            return decimal_values[0]

        for run in digit_runs:
            if run == code:
                continue
            if len(run) >= 5:
                return int(run) / 1000
        if code and len(code) >= 5:
            return int(code) / 1000
        return None

    def _infer_red_digits(self, digit_runs: list[str]) -> int | None:
        return 3 if any(len(run) >= 5 for run in digit_runs) else None

    @staticmethod
    def _safe_float(value: object) -> float | None:
        if value is None:
            return None
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None


def _safe_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError:
        return response.text


def _strip_data_uri_prefix(value: str) -> str:
    if value.startswith("data:") and "," in value:
        return value.split(",", 1)[1]
    return value


glm_ocr_service = GlmOcrService()
