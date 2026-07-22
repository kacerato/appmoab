import base64
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import pytest

from app.routers.hydrometers import _apply_burst_consensus
from app.schemas.hydrometer import KimiVisionFeedbackRequest
from app.services.invoice_documents import validate_receipt_upload
from app.services.meter_vision import (
    DigitObservation,
    VisionResult,
    _PortableKnnClassifier,
    _candidate_prefixes_from_digits,
    _candidate_sequences_from_digits,
    _decode_image,
    _fuse_digit_sequences,
    _hydrometer_face_candidate,
    _prediction_anomaly,
    _red_roller_strip_candidate,
    _temporal_candidates,
    _trained_classifier,
    meter_vision_service,
)
from app.utils.storage import binary_sha256, decode_base64_upload


def _synthetic_meter_data_uri() -> str:
    image = np.full((420, 900, 3), 210, dtype=np.uint8)
    cv2.rectangle(image, (120, 130), (780, 290), (15, 15, 15), -1)
    cv2.rectangle(image, (120, 130), (780, 290), (245, 245, 245), 6)
    cv2.putText(image, "0012345", (145, 255), cv2.FONT_HERSHEY_SIMPLEX, 2.7, (250, 250, 250), 7, cv2.LINE_AA)
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    return "data:image/jpeg;base64," + base64.b64encode(encoded.tobytes()).decode()


def test_local_meter_vision_returns_structured_contract():
    result = meter_vision_service.analyze(
        _synthetic_meter_data_uri(),
        red_digits=3,
        black_digits=4,
        previous_value=10.0,
    )

    assert result.model_version
    assert len(result.digits) == 7
    assert 0 <= result.confidence <= 1
    assert "usable" in result.quality
    if result.predicted_value is not None:
        assert result.predicted_code
    assert result.rectified_jpeg and result.rectified_jpeg.startswith(b"\xff\xd8")


def test_mobile_base64_without_padding_or_with_line_breaks_is_decoded():
    encoded = _synthetic_meter_data_uri().split(",", 1)[1]
    without_padding = encoded.rstrip("=")
    with_line_breaks = "\n".join(without_padding[index:index + 71] for index in range(0, len(without_padding), 71))

    decoded = _decode_image(with_line_breaks)

    assert decoded.shape[:2] == (420, 900)


def test_bundled_field_model_and_red_roller_anchor_are_available():
    assert _trained_classifier() is not None

    image = np.full((700, 900, 3), 235, dtype=np.uint8)
    cv2.rectangle(image, (125, 270), (790, 390), (250, 250, 250), -1)
    for index, digit in enumerate("0025748"):
        color = (25, 25, 25) if index < 4 else (30, 30, 205)
        cv2.putText(
            image,
            digit,
            (145 + index * 88, 365),
            cv2.FONT_HERSHEY_SIMPLEX,
            2.5,
            color,
            7,
            cv2.LINE_AA,
        )

    corners = _red_roller_strip_candidate(image, red_digits=3, black_digits=4)
    assert corners is not None
    assert corners.shape == (4, 2)


def test_hydrometer_face_is_detected_independently_from_digit_window():
    image = np.full((900, 900, 3), 32, dtype=np.uint8)
    cv2.circle(image, (450, 455), 330, (225, 225, 225), -1)
    cv2.circle(image, (450, 455), 330, (35, 78, 130), 18)
    cv2.rectangle(image, (245, 350), (655, 455), (250, 250, 250), -1)
    cv2.putText(image, "0090645", (265, 425), cv2.FONT_HERSHEY_SIMPLEX, 1.65, (20, 20, 20), 5, cv2.LINE_AA)

    detection = _hydrometer_face_candidate(image)

    assert detection is not None
    assert detection.confidence >= 0.46
    _, _, width, height = detection.bounds
    assert width >= 600
    assert height >= 600


def test_knn_model_loads_without_opencv_ml_module():
    model_path = Path(__file__).parents[1] / "app" / "assets" / "meter-field-v3-20260622.yml"

    with patch.object(cv2, "ml", None):
        classifier = _PortableKnnClassifier(str(model_path))

    assert classifier.is_trained()


def test_model_runtime_self_test_requires_complete_opencv_hog():
    model_path = Path(__file__).parents[1] / "app" / "assets" / "meter-field-v3-20260622.yml"
    classifier = _PortableKnnClassifier(str(model_path))

    with patch.object(cv2, "HOGDescriptor", None), pytest.raises(
        RuntimeError,
        match="HOGDescriptor não está disponível",
    ):
        classifier.verify_runtime()


def test_complete_decoder_does_not_touch_opencv_ml_module():
    _trained_classifier.cache_clear()
    try:
        with patch.object(cv2, "ml", None):
            classifier = _trained_classifier()
            result = meter_vision_service.analyze(
                _synthetic_meter_data_uri(),
                red_digits=3,
                black_digits=4,
            )
    finally:
        _trained_classifier.cache_clear()

    assert isinstance(classifier, _PortableKnnClassifier)
    assert "trained_model_unavailable" not in result.flags


def test_runtime_ocr_failure_is_contained_for_dashboard_review():
    with patch("app.services.meter_vision._slot_observation", side_effect=RuntimeError("broken runtime")):
        result = meter_vision_service.analyze(
            _synthetic_meter_data_uri(),
            red_digits=3,
            black_digits=4,
        )

    assert result.predicted_code is None
    assert result.predicted_value is None
    assert result.auto_fill_allowed is False
    assert result.decision == "confirm"
    assert result.flags == ["vision_runtime_error"]
    assert "dashboard" in result.quality["recapture_reason"]


def test_requirements_install_only_one_opencv_distribution():
    requirements = (Path(__file__).parents[1] / "requirements.txt").read_text(encoding="utf-8")
    packages = [
        line.strip().split("==", 1)[0].lower()
        for line in requirements.splitlines()
        if line.strip().lower().startswith("opencv-")
    ]

    assert packages == ["opencv-python"]


def test_broken_primary_model_never_falls_back_to_unsafe_suggestion():
    with patch("app.services.meter_vision._trained_classifier", return_value=None):
        result = meter_vision_service.analyze(
            _synthetic_meter_data_uri(),
            red_digits=3,
            black_digits=4,
            previous_value=10.0,
        )

    assert result.predicted_code is None
    assert result.predicted_value is None
    assert result.decision == "confirm"
    assert "trained_model_unavailable" in result.flags


def test_implausible_ocr_jump_is_rejected_before_dashboard_suggestion():
    assert _prediction_anomaly(1151.808, 90.0) == "implausible_consumption_jump"
    assert _prediction_anomaly(90.645, 90.0) is None
    assert _prediction_anomaly(89.999, 90.0) == "below_previous_reading"


def test_sequence_fusion_handles_transition_and_false_separator():
    fused, mode = _fuse_digit_sequences(
        [0, 0, 9, 0, 6, 4, 5],
        [0, 0, 9, 0, 6, 4],
        0.96,
    )
    assert fused == [0, 0, 9, 0, 6, 4, 5]
    assert mode == "sequence_missing_transition"

    fused, mode = _fuse_digit_sequences(
        [0, 0, 2, 5, 7, 4, 8],
        [0, 0, 2, 5, 1, 7, 4, 8],
        0.91,
    )
    assert fused == [0, 0, 2, 5, 7, 4, 8]
    assert mode == "sequence_removed_separator"

    fused, mode = _fuse_digit_sequences(
        [0, 0, 9, 0, 6, 4, 5],
        [0, 0, 1, 9, 1, 0, 1, 6, 4, 5],
        0.91,
    )
    assert fused == [0, 0, 9, 0, 6, 4, 5]
    assert mode == "sequence_removed_separators"


def test_full_frame_candidate_normalization_prefers_false_separator_ones():
    candidates = _candidate_sequences_from_digits([0, 0, 2, 1, 5, 1, 7, 4, 8], 7)
    best = min(candidates, key=lambda item: item[1])

    assert best[0] == [0, 0, 2, 5, 7, 4, 8]
    assert best[2] is False


def test_meter_tail_prefix_normalization_prefers_trailing_unit_noise():
    candidates = _candidate_prefixes_from_digits([0, 0, 9, 0, 6, 4, 9], 6)
    best = min(candidates, key=lambda item: item[1])

    assert best[0] == [0, 0, 9, 0, 6, 4]


def test_burst_consensus_uses_median_for_partial_last_digit():
    def result(code: str, confidence: float) -> VisionResult:
        return VisionResult(
            predicted_code=None,
            predicted_value=int(code) / 1000,
            confidence=confidence,
            auto_fill_allowed=False,
            red_digits=3,
            black_digits=4,
            model_version="test",
            quality={
                "usable": True,
                "blur": 0.1,
                "sequence_ocr": {"digits": code, "confidence": 0.91},
            },
            digits=[{"position": index, "value": int(digit), "confidence": confidence} for index, digit in enumerate(code)],
            alternatives=[],
            flags=["sequence_exact"],
        )

    selected_index, selected = _apply_burst_consensus(
        [result("0090645", 0.17), result("0090642", 0.96), result("0090646", 0.72)],
        selected_index=1,
        red_digits=3,
        black_digits=4,
    )

    assert selected_index == 0
    assert selected.predicted_value == 90.645
    assert selected.predicted_code == "0090645"
    assert "burst_consensus_median" in selected.flags
    assert selected.quality["burst_consensus"]["selected"] == "0090645"


def test_transition_decoder_considers_both_visible_digits_and_history():
    observations = [
        DigitObservation(position=0, value=1, confidence=0.99),
        DigitObservation(position=1, value=2, confidence=0.99),
        DigitObservation(
            position=2,
            value=4,
            confidence=0.82,
            upper_digit=4,
            lower_digit=5,
            transition_phase=0.61,
            transitional=True,
        ),
    ]

    selected, alternatives, flags = _temporal_candidates(observations, red_digits=0, previous_value=123)

    assert selected == 124
    assert alternatives == [124.0, 125.0]
    assert "transitional_digit" in flags


def test_receipt_signature_validation_rejects_spoofed_mime():
    validate_receipt_upload(b"%PDF-1.7\ncontent", "application/pdf")

    try:
        validate_receipt_upload(b"not a pdf", "application/pdf")
    except ValueError as exc:
        assert "não corresponde" in str(exc)
    else:
        raise AssertionError("MIME falso deveria ser rejeitado")


def test_storage_decoder_and_sha_are_deterministic():
    payload = base64.b64encode(b"%PDF-1.7\ncontent").decode()
    ext, raw, mime = decode_base64_upload(f"data:application/pdf;base64,{payload}", "bin")

    assert (ext, mime) == ("pdf", "application/pdf")
    assert raw.startswith(b"%PDF")
    assert binary_sha256(raw) == binary_sha256(raw)


def test_dev_vision_feedback_can_mark_confirmed_capture_for_training():
    request = KimiVisionFeedbackRequest(
        stage="dev_test",
        predicted_value=90.64,
        confirmed_value=90.645,
        approve_for_training=True,
    )

    assert request.stage == "dev_test"
    assert request.approve_for_training is True
