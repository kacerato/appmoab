import base64

import cv2
import numpy as np

from app.services.invoice_documents import validate_receipt_upload
from app.services.meter_vision import (
    DigitObservation,
    _temporal_candidates,
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
    assert result.rectified_jpeg and result.rectified_jpeg.startswith(b"\xff\xd8")


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
