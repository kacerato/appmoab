import base64
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest

from app.schemas.hydrometer import HydrometerIdentifyRequest, KimiVisionFeedbackRequest
from app.routers import hydrometers as hydrometers_router
from app.scripts.calibrate_meter_vision import build_profile
from app.scripts.promote_meter_vision import DEFAULT_GATES, evaluate
from app.services.meter_vision import DigitObservation, VisionResult, meter_vision_service
from app.services.vision_decision import DECODER_VERSION, fuse_burst_results


def _synthetic_meter_data_uri() -> str:
    image = np.full((420, 900, 3), 210, dtype=np.uint8)
    cv2.rectangle(image, (120, 130), (780, 290), (15, 15, 15), -1)
    cv2.putText(image, "0012345", (145, 255), cv2.FONT_HERSHEY_SIMPLEX, 2.7, (250, 250, 250), 7, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return base64.b64encode(encoded.tobytes()).decode()


def _result(code: str, confidence: float, *, transition: bool = False) -> VisionResult:
    digits = []
    for position, digit in enumerate(code):
        observation = DigitObservation(
            position=position,
            value=int(digit),
            confidence=confidence,
            probabilities=[1.0 if candidate == int(digit) else 0.0 for candidate in range(10)],
        )
        if transition and position == len(code) - 1:
            observation.transitional = True
            observation.current_digit = 5
            observation.next_digit = 6
            observation.upper_digit = 5
            observation.lower_digit = 6
            observation.transition_phase = 0.42
            observation.transition_confidence = 0.91
        digits.append(observation.__dict__)
    return VisionResult(
        predicted_code=code,
        predicted_value=int(code) / 1000,
        confidence=confidence,
        auto_fill_allowed=False,
        red_digits=3,
        black_digits=4,
        model_version="test",
        quality={"usable": True, "blur": 0.1, "glare": 0.0, "perspective": 0.0},
        digits=digits,
        alternatives=[],
        flags=[],
    )


def test_quality_preflight_returns_actionable_contract():
    result = meter_vision_service.inspect_capture(
        _synthetic_meter_data_uri(),
        red_digits=3,
        black_digits=4,
    )

    assert isinstance(result["usable"], bool)
    assert 0 <= result["display_area_ratio"] <= 1
    assert result["image_width"] == 900
    assert result["image_height"] == 420
    if not result["usable"]:
        assert result["guidance_code"]
        assert result["recapture_reason"]


def test_quality_preflight_downscales_large_frames_but_reports_original_dimensions():
    image = np.full((1800, 3000, 3), 210, dtype=np.uint8)
    cv2.rectangle(image, (400, 560), (2600, 1240), (15, 15, 15), -1)
    cv2.putText(image, "0012345", (510, 1070), cv2.FONT_HERSHEY_SIMPLEX, 8.0, (250, 250, 250), 22, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok

    result = meter_vision_service.inspect_capture(
        base64.b64encode(encoded.tobytes()).decode(),
        red_digits=3,
        black_digits=4,
    )

    assert result["image_width"] == 3000
    assert result["image_height"] == 1800
    assert max(result["inspection_width"], result["inspection_height"]) == 1200


def test_temporal_fusion_keeps_transition_state_and_requires_calibration():
    _, result = fuse_burst_results(
        [
            _result("0090645", 0.88, transition=True),
            _result("0090646", 0.82, transition=True),
            _result("0090645", 0.91, transition=True),
        ],
        selected_index=0,
        red_digits=3,
        black_digits=4,
        previous_value=90.640,
        hydrometer_brand="unknown",
        hydrometer_model="unknown",
    )

    assert result.predicted_code == "0090645"
    assert result.decoder_version == DECODER_VERSION
    assert result.decision == "confirm"
    assert result.auto_fill_allowed is False
    assert result.digits[-1]["transitional"] is True
    assert result.digits[-1]["current_digit"] == 5
    assert result.digits[-1]["next_digit"] == 6
    assert result.quality["temporal_fusion"]["calibrated"] is False


def test_capture_contract_limits_burst_and_accepts_slot_labels():
    request = HydrometerIdentifyRequest(
        photo_base64="abc",
        frames_base64=["frame"] * 7,
        capture_metadata={"capture_pipeline": "mobile-burst-v2"},
    )
    feedback = KimiVisionFeedbackRequest(
        confirmed_value=90.645,
        slot_labels=[{"position": 6, "state": "transition", "current_digit": 5, "next_digit": 6, "transition_phase": 0.5}],
    )

    assert len(request.frames_base64) == 7
    assert feedback.slot_labels[0]["state"] == "transition"
    with pytest.raises(Exception):
        HydrometerIdentifyRequest(photo_base64="abc", frames_base64=["frame"] * 8)


def test_calibration_and_promotion_are_blocked_without_evidence():
    tiny_report = {
        "count": 13,
        "exact_accuracy": 0.62,
        "digit_accuracy": 0.80,
        "transition_exact_accuracy": 0.50,
        "burst_exact_accuracy": 1.0,
        "silent_errors": 0,
        "p95_ms": 1800,
        "cases": [{"confidence": 0.8, "exact": True, "tags": []}] * 13,
    }

    failures = evaluate(tiny_report, DEFAULT_GATES)
    assert any("count=" in failure for failure in failures)
    assert any("exact_accuracy=" in failure for failure in failures)
    with pytest.raises(RuntimeError, match="Dataset insuficiente"):
        build_profile(
            tiny_report,
            minimum_cases=500,
            minimum_transition_cases=100,
            minimum_bin_size=30,
            target_precision=0.998,
            allow_small_diagnostic=False,
        )


class VisionVerdictEndpointContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_endpoint_uses_supported_meter_service_arguments(self):
        result = _result("0012345", 0.91)
        db = MagicMock()
        db.flush = AsyncMock()
        user = SimpleNamespace(id=uuid.uuid4())
        request = HydrometerIdentifyRequest(
            photo_base64=_synthetic_meter_data_uri(),
            hydrometer_brand="Aqua",
            hydrometer_model="M1",
        )

        def analyze(
            image_base64: str,
            *,
            red_digits: int | None = 3,
            black_digits: int | None = None,
            previous_value: float | None = None,
            expensive_ocr: bool = True,
            hydrometer_brand: str | None = None,
            hydrometer_model: str | None = None,
        ) -> VisionResult:
            self.assertTrue(image_base64)
            self.assertEqual(red_digits, 3)
            self.assertTrue(expensive_ocr)
            self.assertEqual(hydrometer_brand, "Aqua")
            self.assertEqual(hydrometer_model, "M1")
            return result

        with (
            patch.object(hydrometers_router.meter_vision_service, "analyze", side_effect=analyze),
            patch.object(
                hydrometers_router,
                "decode_base64_upload",
                return_value=("jpg", b"frame", "image/jpeg"),
            ),
            patch.object(hydrometers_router, "save_binary", return_value="vision/test/frame.jpg"),
            patch("app.config.get_settings", return_value=SimpleNamespace(vision_glm_shadow_enabled=False)),
        ):
            response = await hydrometers_router.kimi_vision_verdict(request, db, user)

        self.assertEqual(response["predicted_code"], "0012345")
        self.assertEqual(response["inference_id"], str(db.add.call_args.args[0].id))
        db.flush.assert_awaited_once()
