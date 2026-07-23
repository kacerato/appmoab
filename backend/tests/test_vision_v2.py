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


def _result(
    code: str,
    confidence: float,
    *,
    transition: bool = False,
    text_evidence: bool = True,
) -> VisionResult:
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
        quality={
            "usable": True,
            "blur": 0.1,
            "glare": 0.0,
            "perspective": 0.0,
            "sequence_ocr": {
                "digits": code if text_evidence else None,
                "confidence": 0.91 if text_evidence else 0.0,
            },
        },
        digits=digits,
        alternatives=[],
        flags=["sequence_exact"] if text_evidence else [],
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
    assert isinstance(result["meter_found"], bool)
    assert 0 <= result["meter_confidence"] <= 1
    assert set(result["display_bounds"]) == {"x", "y", "width", "height"}
    assert 0 <= result["display_bounds"]["x"] <= 1
    assert 0 < result["display_bounds"]["width"] <= 1
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


def test_temporal_text_consensus_overrides_isolated_blur_advisory():
    frames = [
        _result("0090645", 0.72, text_evidence=True),
        _result("0090645", 0.69, text_evidence=True),
        _result("0090645", 0.75, text_evidence=True),
    ]
    for frame in frames:
        frame.quality["usable"] = False
        frame.quality["recapture_reason"] = "Possível movimento no quadro."

    _, result = fuse_burst_results(
        frames,
        selected_index=2,
        red_digits=3,
        black_digits=4,
        previous_value=90.640,
    )

    assert result.predicted_code == "0090645"
    assert result.decision == "confirm"
    assert result.quality["temporal_fusion"]["consensus_valid"] is True


def test_temporal_fusion_rejects_repeated_slot_only_hallucination():
    _, result = fuse_burst_results(
        [
            _result("5030441", 0.72, text_evidence=False),
            _result("5030441", 0.69, text_evidence=False),
            _result("5030441", 0.74, text_evidence=False),
        ],
        selected_index=2,
        red_digits=3,
        black_digits=4,
    )

    assert result.predicted_code is None
    assert result.predicted_value is None
    assert result.confidence == 0.0
    assert result.decision == "confirm"
    assert "burst_insufficient_text_evidence" in result.flags
    assert result.quality["temporal_fusion"]["rejected_candidate"] == "5030441"


def test_temporal_fusion_keeps_repeated_reliably_anchored_slots_as_suggestion():
    frames = [
        _result("0090645", 0.72, text_evidence=False),
        _result("0090645", 0.69, text_evidence=False),
        _result("1471009", 0.74, text_evidence=False),
    ]
    for frame in frames[:2]:
        frame.quality["display_detection"] = {"source": "red_roller_anchor"}

    _, result = fuse_burst_results(
        frames,
        selected_index=2,
        red_digits=3,
        black_digits=4,
    )

    assert result.predicted_code == "0090645"
    assert result.decision == "confirm"
    assert result.auto_fill_allowed is False
    assert "burst_anchored_slot_suggestion" in result.flags
    assert result.quality["temporal_fusion"]["anchored_slot_frames"] == 2
    assert result.quality["temporal_fusion"]["suggestion_valid"] is True


def test_temporal_fusion_keeps_one_text_frame_as_dashboard_only_suggestion():
    _, result = fuse_burst_results(
        [
            _result("0000000", 0.72, text_evidence=False),
            _result("0090045", 0.61, text_evidence=True),
            _result("1471009", 0.76, text_evidence=False),
        ],
        selected_index=2,
        red_digits=3,
        black_digits=4,
    )

    assert result.predicted_code == "0090045"
    assert result.predicted_value == pytest.approx(90.045)
    assert result.decision == "confirm"
    assert result.auto_fill_allowed is False
    assert "burst_single_text_suggestion" in result.flags
    assert result.quality["temporal_fusion"]["text_evidence_frames"] == 1
    assert result.quality["temporal_fusion"]["consensus_valid"] is False
    assert result.quality["temporal_fusion"]["suggestion_valid"] is True


def test_temporal_fusion_accepts_one_text_frame_when_an_independent_slot_frame_matches():
    _, result = fuse_burst_results(
        [
            _result("0090645", 0.84, text_evidence=True),
            _result("0090645", 0.78, text_evidence=False),
            _result("1471009", 0.72, text_evidence=False),
        ],
        selected_index=0,
        red_digits=3,
        black_digits=4,
        previous_value=90.640,
    )

    assert result.predicted_code == "0090645"
    assert result.decision == "confirm"
    assert "burst_hybrid_text_slot_consensus" in result.flags
    assert result.quality["temporal_fusion"]["consensus_valid"] is True


def test_temporal_fusion_requires_text_frames_to_agree_on_prefix():
    _, result = fuse_burst_results(
        [
            _result("1630847", 0.75, text_evidence=True),
            _result("0090644", 0.72, text_evidence=True),
            _result("0016747", 0.78, text_evidence=False),
        ],
        selected_index=2,
        red_digits=3,
        black_digits=4,
    )

    assert result.predicted_code is None
    assert result.predicted_value is None
    assert "burst_text_evidence_disagreement" in result.flags
    assert result.quality["temporal_fusion"]["text_evidence_frames"] == 2
    assert result.quality["temporal_fusion"]["text_evidence_codes"] == ["1630847", "0090644"]


def test_temporal_fusion_does_not_guess_when_only_last_roller_disagrees():
    _, result = fuse_burst_results(
        [
            _result("0090644", 0.74, text_evidence=True),
            _result("0090640", 0.68, text_evidence=True),
            _result("0090645", 0.81, text_evidence=False),
        ],
        selected_index=2,
        red_digits=3,
        black_digits=4,
        previous_value=90.640,
    )

    assert result.predicted_code is None
    assert result.predicted_value is None
    assert "burst_text_evidence_disagreement" in result.flags
    assert result.quality["temporal_fusion"]["text_evidence_codes"] == ["0090644", "0090640"]


def test_temporal_fusion_reapplies_history_guard_after_consensus():
    _, result = fuse_burst_results(
        [
            _result("5030441", 0.90),
            _result("5030441", 0.88),
            _result("5030441", 0.92),
        ],
        selected_index=2,
        red_digits=3,
        black_digits=4,
        previous_value=90.645,
    )

    assert result.predicted_code is None
    assert result.predicted_value is None
    assert "implausible_consumption_jump" in result.flags
    assert result.quality["temporal_fusion"]["rejected_candidate"] == "5030441"


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
    async def test_live_presence_uses_fast_detector_without_ocr(self):
        user = SimpleNamespace(id=uuid.uuid4())
        request = HydrometerIdentifyRequest(
            photo_base64=_synthetic_meter_data_uri(),
            red_digits=3,
            black_digits=4,
        )
        expected = {
            "meter_found": True,
            "display_found": True,
            "display_bounds": {"x": 0.2, "y": 0.3, "width": 0.6, "height": 0.2},
        }

        with patch.object(
            hydrometers_router.meter_vision_service,
            "inspect_capture",
            return_value=expected,
        ) as inspect_capture:
            result = await hydrometers_router.inspect_vision_presence(request, user)

        self.assertEqual(result, expected)
        inspect_capture.assert_called_once_with(
            request.photo_base64,
            red_digits=3,
            black_digits=4,
        )

    def test_tap_burst_uses_primary_and_last_settled_frame_for_full_ocr(self):
        indexes = hydrometers_router._expensive_probe_indexes(6, [
            {"primary": True},
            {"source": "tap_burst"},
            {"source": "tap_burst"},
            {"source": "live_preview_cache"},
            {"source": "live_preview_cache"},
            {"source": "live_preview_cache"},
        ])

        self.assertEqual(indexes, {0, 2})

    def test_live_fallback_uses_highest_detection_score(self):
        indexes = hydrometers_router._expensive_probe_indexes(3, [
            {"primary": True},
            {"source": "live_preview_cache", "detection_score": 3.2},
            {"source": "live_preview_cache", "detection_score": 6.8},
        ])

        self.assertEqual(indexes, {0, 2})

    async def test_live_preview_requires_textual_digit_evidence(self):
        user = SimpleNamespace(id=uuid.uuid4())
        request = HydrometerIdentifyRequest(
            photo_base64=_synthetic_meter_data_uri(),
            red_digits=3,
            black_digits=4,
            previous_value=90.640,
        )

        with patch.object(
            hydrometers_router.meter_vision_service,
            "analyze",
            return_value=_result("0090645", 0.91, text_evidence=True),
        ):
            ready = await hydrometers_router.inspect_vision_capture(request, user)

        with patch.object(
            hydrometers_router.meter_vision_service,
            "analyze",
            return_value=_result("5030441", 0.91, text_evidence=False),
        ):
            rejected = await hydrometers_router.inspect_vision_capture(request, user)

        self.assertTrue(ready["recognition_ready"])
        self.assertEqual(ready["predicted_code"], "0090645")
        self.assertFalse(rejected["recognition_ready"])
        self.assertIsNone(rejected["predicted_code"])

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
