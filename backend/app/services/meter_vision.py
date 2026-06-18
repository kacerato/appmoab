"""Visao computacional especializada em mostradores mecanicos de hidrometros.

O pipeline e local e deterministico: qualidade -> visor -> perspectiva -> slots
-> classificacao -> decodificacao mecanica/temporal. Um modelo ONNX treinado pode
substituir o classificador de templates sem mudar o contrato da API.
"""

import base64
import io
import logging
import math
import os
from dataclasses import asdict, dataclass
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

try:
    import cv2
    import numpy as np
except ImportError:  # pragma: no cover - ambiente sem extras de visao
    cv2 = None
    np = None

try:
    import onnxruntime as ort
except ImportError:  # pragma: no cover
    ort = None


@dataclass
class QualityMetrics:
    blur: float
    glare: float
    darkness: float
    contrast: float
    perspective: float
    usable: bool
    recapture_reason: str | None = None


@dataclass
class DigitObservation:
    position: int
    value: int | None
    confidence: float
    upper_digit: int | None = None
    lower_digit: int | None = None
    transition_phase: float | None = None
    transitional: bool = False


@dataclass
class VisionResult:
    predicted_code: str | None
    predicted_value: float | None
    confidence: float
    auto_fill_allowed: bool
    red_digits: int | None
    black_digits: int | None
    model_version: str
    quality: dict
    digits: list[dict]
    alternatives: list[float]
    flags: list[str]
    rectified_jpeg: bytes | None = None

    def public_dict(self) -> dict:
        data = asdict(self)
        data.pop("rectified_jpeg", None)
        return data


def _decode_image(data_uri: str):
    if np is None:
        raise RuntimeError("Dependencias locais de visao nao instaladas")
    payload = data_uri.split(",", 1)[1] if data_uri.startswith("data:") and "," in data_uri else data_uri
    raw = base64.b64decode(payload)
    image = Image.open(io.BytesIO(raw)).convert("RGB")
    return cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)


def _clamp(value: float) -> float:
    return round(max(0.0, min(1.0, float(value))), 4)


def _quality(image) -> QualityMetrics:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    blur = 1.0 - _clamp(sharpness / 500.0)
    glare = _clamp(float((gray >= 248).mean()) / 0.18)
    darkness = _clamp(float((gray <= 28).mean()) / 0.35)
    contrast = _clamp(float(gray.std()) / 72.0)

    reason = None
    if blur > 0.72:
        reason = "Imagem desfocada. Firme o aparelho e aproxime do visor."
    elif glare > 0.62:
        reason = "Reflexo forte sobre o visor. Mude levemente o angulo ou desligue o flash."
    elif darkness > 0.70:
        reason = "Imagem escura. Ilumine o hidrometro sem apontar o flash diretamente ao visor."
    elif contrast < 0.18:
        reason = "Pouco contraste no visor. Aproxime e ajuste a iluminacao."

    return QualityMetrics(
        blur=round(blur, 4),
        glare=round(glare, 4),
        darkness=round(darkness, 4),
        contrast=round(contrast, 4),
        perspective=0.0,
        usable=reason is None,
        recapture_reason=reason,
    )


def _order_corners(points):
    points = np.asarray(points, dtype="float32").reshape(4, 2)
    ordered = np.zeros((4, 2), dtype="float32")
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).reshape(-1)
    ordered[0] = points[np.argmin(sums)]
    ordered[2] = points[np.argmax(sums)]
    ordered[1] = points[np.argmin(diffs)]
    ordered[3] = points[np.argmax(diffs)]
    return ordered


def _display_candidate(image):
    height, width = image.shape[:2]
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.bilateralFilter(gray, 7, 45, 45)
    edges = cv2.Canny(gray, 45, 140)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((5, 11), np.uint8), iterations=2)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)

    best = None
    image_area = float(height * width)
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.025 * perimeter, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        x, y, w, h = cv2.boundingRect(polygon)
        area_ratio = (w * h) / image_area
        aspect = w / max(h, 1)
        if not (0.012 <= area_ratio <= 0.65 and 2.0 <= aspect <= 9.5):
            continue
        center_penalty = abs((x + w / 2) - width / 2) / width + abs((y + h / 2) - height / 2) / height
        score = area_ratio * 4 + min(aspect / 6, 1) - center_penalty * 0.35
        if best is None or score > best[0]:
            best = (score, _order_corners(polygon))

    if best:
        return best[1], False

    # Fallback seguro alinhado ao guia de captura do aplicativo.
    x1, x2 = int(width * 0.15), int(width * 0.85)
    y1, y2 = int(height * 0.32), int(height * 0.68)
    return np.array([[x1, y1], [x2, y1], [x2, y2], [x1, y2]], dtype="float32"), True


def _rectify(image, corners):
    tl, tr, br, bl = corners
    target_width = max(int(np.linalg.norm(tr - tl)), int(np.linalg.norm(br - bl)), 320)
    target_height = max(int(np.linalg.norm(bl - tl)), int(np.linalg.norm(br - tr)), 80)
    target_width = min(target_width, 1200)
    target_height = min(target_height, 400)
    destination = np.array(
        [[0, 0], [target_width - 1, 0], [target_width - 1, target_height - 1], [0, target_height - 1]],
        dtype="float32",
    )
    matrix = cv2.getPerspectiveTransform(corners, destination)
    rectified = cv2.warpPerspective(image, matrix, (target_width, target_height), flags=cv2.INTER_CUBIC)
    top = np.linalg.norm(tr - tl)
    bottom = np.linalg.norm(br - bl)
    left = np.linalg.norm(bl - tl)
    right = np.linalg.norm(br - tr)
    perspective = _clamp(abs(top - bottom) / max(top, bottom, 1) + abs(left - right) / max(left, right, 1))
    return rectified, perspective


def _font(size: int):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arial.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


@lru_cache(maxsize=1)
def _digit_templates():
    if np is None:
        return []
    templates = []
    for digit in range(10):
        canvas = Image.new("L", (64, 96), 0)
        draw = ImageDraw.Draw(canvas)
        font = _font(78)
        bbox = draw.textbbox((0, 0), str(digit), font=font)
        x = (64 - (bbox[2] - bbox[0])) // 2 - bbox[0]
        y = (96 - (bbox[3] - bbox[1])) // 2 - bbox[1]
        draw.text((x, y), str(digit), fill=255, font=font)
        template = np.asarray(canvas)
        template = cv2.GaussianBlur(template, (3, 3), 0)
        templates.append(template.astype("float32") / 255.0)
    return templates


class _OnnxClassifier:
    def __init__(self, path: str):
        self.session = ort.InferenceSession(path, providers=["CPUExecutionProvider"]) if ort and path else None
        self.input_name = self.session.get_inputs()[0].name if self.session else None

    def classify(self, slot) -> tuple[int | None, float, list[float]]:
        if not self.session or np is None:
            return None, 0.0, []
        normalized = _normalize_slot(slot, size=(28, 28)).astype("float32") / 255.0
        tensor = normalized[None, None, :, :]
        logits = np.asarray(self.session.run(None, {self.input_name: tensor})[0]).reshape(-1)[:10]
        logits = logits - logits.max()
        probs = np.exp(logits) / np.exp(logits).sum()
        digit = int(probs.argmax())
        return digit, float(probs[digit]), probs.tolist()


def hog_features(slot):
    normalized = _normalize_slot(slot, size=(28, 28))
    hog = cv2.HOGDescriptor((28, 28), (14, 14), (7, 7), (7, 7), 9)
    return hog.compute(normalized).reshape(1, -1).astype("float32")


class _OpenCvKnnClassifier:
    def __init__(self, path: str):
        self.model = cv2.ml.KNearest_load(path)

    def classify(self, slot) -> tuple[int | None, float, list[float]]:
        features = hog_features(slot)
        _, result, neighbours, distances = self.model.findNearest(features, k=5)
        digit = int(round(float(result[0, 0])))
        votes = [int(round(float(value))) for value in neighbours[0]]
        vote_share = votes.count(digit) / max(len(votes), 1)
        distance_score = math.exp(-float(distances[0, 0]) / 120.0)
        confidence = _clamp(vote_share * 0.75 + distance_score * 0.25)
        scores = [votes.count(value) / max(len(votes), 1) for value in range(10)]
        return digit, confidence, scores


@lru_cache(maxsize=1)
def _trained_classifier():
    path = settings.vision_model_path.strip()
    if not path or not os.path.exists(path):
        return None
    try:
        if path.lower().endswith((".yml", ".yaml", ".xml")) and cv2 is not None:
            return _OpenCvKnnClassifier(path)
        if ort is None:
            return None
        return _OnnxClassifier(path)
    except Exception:
        logger.exception("Nao foi possivel carregar o modelo ONNX de hidrometros")
        return None


def _normalize_slot(slot, size=(64, 96)):
    gray = cv2.cvtColor(slot, cv2.COLOR_BGR2GRAY) if slot.ndim == 3 else slot
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(gray)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 17, 3)
    if binary.mean() > 127:
        binary = 255 - binary
    coords = cv2.findNonZero(binary)
    if coords is not None:
        x, y, w, h = cv2.boundingRect(coords)
        if w > 2 and h > 2:
            binary = binary[y:y + h, x:x + w]
    target_w, target_h = size
    scale = min((target_w - 8) / max(binary.shape[1], 1), (target_h - 8) / max(binary.shape[0], 1))
    resized = cv2.resize(binary, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    canvas = np.zeros((target_h, target_w), dtype="uint8")
    y0 = (target_h - resized.shape[0]) // 2
    x0 = (target_w - resized.shape[1]) // 2
    canvas[y0:y0 + resized.shape[0], x0:x0 + resized.shape[1]] = resized
    return canvas


def _template_classify(slot) -> tuple[int | None, float, list[float]]:
    normalized = _normalize_slot(slot).astype("float32") / 255.0
    scores = []
    for template in _digit_templates():
        correlation = float(cv2.matchTemplate(normalized, template, cv2.TM_CCOEFF_NORMED)[0, 0])
        scores.append((correlation + 1) / 2)
    if not scores:
        return None, 0.0, []
    order = np.argsort(scores)[::-1]
    best = int(order[0])
    margin = scores[best] - scores[int(order[1])]
    confidence = _clamp(scores[best] * 0.72 + margin * 0.55)
    return best, confidence, scores


def _classify(slot) -> tuple[int | None, float, list[float]]:
    classifier = _trained_classifier()
    if classifier:
        return classifier.classify(slot)
    return _template_classify(slot)


def _slot_observation(slot, position: int) -> DigitObservation:
    value, confidence, _ = _classify(slot)
    height = slot.shape[0]
    upper, upper_conf, _ = _classify(slot[: max(int(height * 0.68), 1)])
    lower, lower_conf, _ = _classify(slot[min(int(height * 0.32), height - 1):])
    transitional = (
        upper is not None
        and lower is not None
        and upper != lower
        and ((upper + 1) % 10 == lower or (lower + 1) % 10 == upper)
        and min(upper_conf, lower_conf) >= 0.32
    )
    if transitional:
        # A energia na metade inferior aproxima quanto o proximo numero entrou no visor.
        normalized = _normalize_slot(slot)
        phase = _clamp(float(normalized[normalized.shape[0] // 2:].mean()) / 255.0)
        current = upper if (upper + 1) % 10 == lower else lower
        next_digit = (current + 1) % 10
        chosen = next_digit if phase >= 0.68 else current
        return DigitObservation(
            position=position,
            value=chosen,
            confidence=round(min(confidence, max(upper_conf, lower_conf)) * 0.88, 4),
            upper_digit=upper,
            lower_digit=lower,
            transition_phase=phase,
            transitional=True,
        )
    return DigitObservation(position=position, value=value, confidence=round(confidence, 4))


def _temporal_candidates(
    observations: list[DigitObservation],
    red_digits: int,
    previous_value: float | None,
) -> tuple[float | None, list[float], list[str]]:
    if not observations or any(item.value is None for item in observations):
        return None, [], ["incomplete_digits"]
    base_digits = [int(item.value) for item in observations]
    digit_sets: list[list[int]] = []
    flags = []
    for item, chosen in zip(observations, base_digits):
        options = [chosen]
        if item.transitional and item.upper_digit is not None and item.lower_digit is not None:
            flags.append("transitional_digit")
            options = list(dict.fromkeys([chosen, item.upper_digit, item.lower_digit]))
        digit_sets.append(options)

    raw_candidates = [[]]
    for options in digit_sets:
        raw_candidates = [prefix + [digit] for prefix in raw_candidates for digit in options]
        if len(raw_candidates) > 32:
            raw_candidates = raw_candidates[:32]
    values = sorted({int("".join(map(str, digits))) / (10 ** max(red_digits, 0)) for digits in raw_candidates})
    if not values:
        return None, [], flags

    if previous_value is None:
        selected = values[0]
    else:
        non_decreasing = [value for value in values if value >= previous_value]
        selected = min(non_decreasing, key=lambda value: value - previous_value) if non_decreasing else values[-1]
        if selected < previous_value:
            flags.append("below_previous_reading")
        elapsed_jump = selected - previous_value
        if elapsed_jump > max(100.0, previous_value * 0.5):
            flags.append("implausible_consumption_jump")
    return selected, values[:8], flags


class MeterVisionService:
    def analyze(
        self,
        image_base64: str,
        *,
        red_digits: int | None = 3,
        black_digits: int | None = None,
        previous_value: float | None = None,
    ) -> VisionResult:
        red_digits = red_digits if red_digits is not None and red_digits >= 0 else 3
        try:
            image = _decode_image(image_base64)
        except Exception as exc:
            logger.warning("Falha ao decodificar imagem para visao local: %s", exc)
            return VisionResult(None, None, 0.0, False, red_digits, black_digits, settings.vision_model_version, {
                "usable": False,
                "recapture_reason": "Não foi possível abrir a imagem capturada.",
            }, [], [], ["decode_failed"])

        quality = _quality(image)
        corners, used_fallback_roi = _display_candidate(image)
        rectified, perspective = _rectify(image, corners)
        quality.perspective = perspective
        if perspective > 0.72 and quality.recapture_reason is None:
            quality.usable = False
            quality.recapture_reason = "Angulo muito lateral. Posicione a camera mais de frente para o visor."

        total_digits = (black_digits or 4) + red_digits
        total_digits = max(3, min(total_digits, 10))
        margin_x = max(int(rectified.shape[1] * 0.025), 1)
        margin_y = max(int(rectified.shape[0] * 0.08), 1)
        usable_roi = rectified[margin_y:rectified.shape[0] - margin_y, margin_x:rectified.shape[1] - margin_x]
        slot_width = usable_roi.shape[1] / total_digits
        observations = []
        for index in range(total_digits):
            start = max(0, int(index * slot_width - slot_width * 0.08))
            end = min(usable_roi.shape[1], int((index + 1) * slot_width + slot_width * 0.08))
            observations.append(_slot_observation(usable_roi[:, start:end], index))

        predicted_value, alternatives, flags = _temporal_candidates(observations, red_digits, previous_value)
        confidences = [item.confidence for item in observations if item.value is not None]
        confidence = float(math.prod(confidences) ** (1 / len(confidences))) if len(confidences) == total_digits else 0.0
        confidence *= max(0.0, 1 - quality.blur * 0.35 - quality.glare * 0.25 - perspective * 0.2)
        if used_fallback_roi:
            confidence *= 0.72
            flags.append("fallback_roi")
        if not quality.usable:
            confidence *= 0.25
            flags.append("recapture_recommended")
        confidence = round(_clamp(confidence), 4)
        auto_fill = bool(
            predicted_value is not None
            and quality.usable
            and confidence >= settings.vision_min_autofill_confidence
            and "implausible_consumption_jump" not in flags
        )
        ok, encoded = cv2.imencode(".jpg", rectified, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        return VisionResult(
            predicted_code=None,
            predicted_value=predicted_value,
            confidence=confidence,
            auto_fill_allowed=auto_fill,
            red_digits=red_digits,
            black_digits=black_digits,
            model_version=settings.vision_model_version,
            quality=asdict(quality),
            digits=[asdict(item) for item in observations],
            alternatives=alternatives,
            flags=list(dict.fromkeys(flags)),
            rectified_jpeg=encoded.tobytes() if ok else None,
        )


meter_vision_service = MeterVisionService()
