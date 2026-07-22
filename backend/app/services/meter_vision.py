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
import re
import threading
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from itertools import combinations

from PIL import Image, ImageDraw, ImageFile, ImageFont

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

try:
    from rapidocr_onnxruntime import RapidOCR
except ImportError:  # pragma: no cover
    RapidOCR = None

_sequence_ocr_lock = threading.Lock()


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
class DisplayDetection:
    corners: object
    confidence: float
    slot_boundaries: list[float] = field(default_factory=list)
    source: str = "detector-onnx"


@dataclass
class DigitObservation:
    position: int
    value: int | None
    confidence: float
    upper_digit: int | None = None
    lower_digit: int | None = None
    transition_phase: float | None = None
    transitional: bool = False
    current_digit: int | None = None
    next_digit: int | None = None
    transition_confidence: float = 0.0
    visibility: float = 1.0
    probabilities: list[float] = field(default_factory=list)
    source: str = "field-classifier"


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
    decision: str = "confirm"
    calibrated_confidence: float | None = None
    decoder_version: str | None = "single-frame-v1"

    def public_dict(self) -> dict:
        data = asdict(self)
        data.pop("rectified_jpeg", None)
        return data


def _decode_image(data_uri: str):
    if np is None:
        raise RuntimeError("Dependencias locais de visao nao instaladas")
    if not isinstance(data_uri, str) or not data_uri.strip():
        raise ValueError("Imagem vazia")
    payload = data_uri.split(",", 1)[1] if data_uri.startswith("data:") and "," in data_uri else data_uri
    payload = re.sub(r"\s+", "", payload).replace("-", "+").replace("_", "/")
    payload += "=" * (-len(payload) % 4)
    raw = base64.b64decode(payload, validate=False)
    if len(raw) < 32:
        raise ValueError("Imagem capturada incompleta")

    # OpenCV tolera melhor pequenas variacoes de JPEG geradas por Android.
    decoded = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    if decoded is not None and decoded.size:
        return decoded

    # Fallback para metadados/orientacoes que o imdecode local nao reconheceu.
    ImageFile.LOAD_TRUNCATED_IMAGES = True
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


def _red_roller_strip_candidate(image, red_digits: int, black_digits: int):
    """Localiza a janela numerica usando os roletes vermelhos como ancora.

    Nos medidores mecanicos usados pelo AquaMoab, os tres ultimos roletes sao
    vermelhos. Essa assinatura e muito mais estavel que procurar qualquer
    retangulo na foto inteira (onde tampa, etiqueta e textos competem com o
    visor). O retangulo vermelho e expandido para a esquerda pelo numero de
    roletes pretos e ja preserva a inclinacao real do mostrador.
    """
    if red_digits <= 0:
        return None
    height, width = image.shape[:2]
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    red = cv2.inRange(hsv, np.array([0, 52, 35]), np.array([24, 255, 255]))
    red |= cv2.inRange(hsv, np.array([153, 52, 35]), np.array([179, 255, 255]))
    blue, green, red_channel = cv2.split(image)
    # Flash quente torna todo o mostrador amarelado e também cai perto do hue
    # vermelho. Exigir dominância real do canal R elimina tampa, pele, ferrugem
    # e fundo bege sem perder os glifos vermelhos desbotados.
    red_dominance = (
        red_channel.astype("int16") - np.maximum(green, blue).astype("int16") > 18
    ).astype("uint8") * 255
    red &= red_dominance

    # Exclui o ponteiro inferior e elementos das bordas antes de agrupar os
    # tres algarismos coloridos da janela.
    region = np.zeros_like(red)
    region[int(height * 0.28):int(height * 0.62), int(width * 0.18):int(width * 0.96)] = 255
    red &= region
    cleaned = cv2.morphologyEx(
        red,
        cv2.MORPH_OPEN,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    contours, _ = cv2.findContours(cleaned, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    components = []
    for contour in contours:
        x, y, component_width, component_height = cv2.boundingRect(contour)
        area = cv2.contourArea(contour)
        if component_height < height * 0.022 or component_height > height * 0.13:
            continue
        if component_width < width * 0.006 or component_width > width * 0.13:
            continue
        if area < image.shape[0] * image.shape[1] * 0.000018:
            continue
        center_x = x + component_width / 2
        center_y = y + component_height / 2
        if not (0.34 * width <= center_x <= 0.94 * width):
            continue
        components.append({
            "contour": contour,
            "x": x,
            "y": y,
            "w": component_width,
            "h": component_height,
            "cx": center_x,
            "cy": center_y,
            "area": area,
        })
    if not components:
        return None

    groups = []
    for seed in components:
        aligned = [
            item for item in components
            if abs(item["cy"] - seed["cy"]) <= max(item["h"], seed["h"]) * 1.30
            and 0.45 <= item["h"] / max(seed["h"], 1) <= 2.20
        ]
        if len(aligned) < 2:
            continue
        # Mantém a sequencia horizontal mais densa; sujeira isolada não deve
        # ampliar o visor artificialmente.
        aligned.sort(key=lambda item: item["cx"])
        dense = []
        for item in aligned:
            if not dense or item["x"] - (dense[-1]["x"] + dense[-1]["w"]) <= width * 0.085:
                dense.append(item)
            elif len(dense) < 2:
                dense = [item]
        if len(dense) < 2:
            continue
        x1 = min(item["x"] for item in dense)
        x2 = max(item["x"] + item["w"] for item in dense)
        y1 = min(item["y"] for item in dense)
        y2 = max(item["y"] + item["h"] for item in dense)
        span_aspect = (x2 - x1) / max(y2 - y1, 1)
        if not (1.15 <= span_aspect <= 7.5):
            continue
        score = min(len(dense), red_digits + 1) * 12 + sum(item["area"] for item in dense) / 250
        score -= abs(((y1 + y2) / 2 / height) - 0.42) * 8
        groups.append((score, dense))
    if not groups:
        return None

    selected = max(groups, key=lambda item: item[0])[1]
    red_points = np.vstack([item["contour"] for item in selected])
    red_box = _order_corners(cv2.boxPoints(cv2.minAreaRect(red_points)))
    tl, tr, br, bl = red_box
    horizontal = ((tr - tl) + (br - bl)) / 2
    red_width = float(np.linalg.norm(horizontal))
    if red_width < 1:
        return None
    unit_x = horizontal / red_width
    vertical = ((bl - tl) + (br - tr)) / 2
    red_height = float(np.linalg.norm(vertical))
    if red_height < 1:
        return None
    unit_y = vertical / red_height

    # A distancia entre centros e mais confiavel que a largura dos glifos — em
    # especial quando o ultimo rolete esta subindo e apenas uma faixa dele fica
    # vermelha. Se um dos tres glifos sumiu da mascara, reconstruimos sua
    # posicao nominal a direita em vez de encolher toda a janela.
    ordered_components = sorted(selected, key=lambda item: item["cx"])
    center_distances = [
        math.hypot(right["cx"] - left["cx"], right["cy"] - left["cy"])
        for left, right in zip(ordered_components, ordered_components[1:])
        if right["cx"] - left["cx"] > width * 0.025
    ]
    estimated_slot = float(np.median(center_distances)) if center_distances else 0.0
    if not (red_height * 0.55 <= estimated_slot <= red_height * 3.2):
        estimated_slot = red_width / max(min(len(selected), red_digits) * 0.84, 1)
    slot_width = estimated_slot
    missing_red_slots = max(red_digits - min(len(selected), red_digits), 0)
    left_extension = slot_width * (black_digits + 0.30)
    right_extension = slot_width * (missing_red_slots + 0.40)
    vertical_padding = red_height * 0.22
    corners = np.array([
        tl - unit_x * left_extension - unit_y * vertical_padding,
        tr + unit_x * right_extension - unit_y * vertical_padding,
        br + unit_x * right_extension + unit_y * vertical_padding,
        bl - unit_x * left_extension + unit_y * vertical_padding,
    ], dtype="float32")
    corners[:, 0] = np.clip(corners[:, 0], 0, width - 1)
    corners[:, 1] = np.clip(corners[:, 1], 0, height - 1)
    return corners


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


class _TransitionOnnxClassifier:
    """Contrato do classificador multi-head de roletes.

    Saídas esperadas, nesta ordem: logits do dígito estável (10), estado
    mecânico (11: transições 0..9 e estável=10), fase (1) e visibilidade (1).
    """

    def __init__(self, path: str):
        self.session = ort.InferenceSession(path, providers=["CPUExecutionProvider"]) if ort and path else None
        self.input_name = self.session.get_inputs()[0].name if self.session else None

    @staticmethod
    def _softmax(values):
        values = np.asarray(values, dtype="float32").reshape(-1)
        values = values - values.max()
        exp_values = np.exp(values)
        return exp_values / max(float(exp_values.sum()), 1e-8)

    @staticmethod
    def _unit_interval(value: float) -> float:
        if 0.0 <= value <= 1.0:
            return value
        return 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, value))))

    def observe(self, slot, position: int) -> DigitObservation | None:
        if not self.session or np is None:
            return None
        normalized = _normalize_slot(slot, size=(64, 96)).astype("float32") / 255.0
        outputs = self.session.run(None, {self.input_name: normalized[None, None, :, :]})
        if len(outputs) < 4:
            return None
        stable = self._softmax(outputs[0])[:10]
        transitions = self._softmax(outputs[1])[:10]
        phase = self._unit_interval(float(np.asarray(outputs[2]).reshape(-1)[0]))
        visibility = self._unit_interval(float(np.asarray(outputs[3]).reshape(-1)[0]))
        digit = int(stable.argmax())
        stable_confidence = float(stable[digit])
        current = int(transitions.argmax())
        transition_confidence = float(transitions[current])
        next_digit = (current + 1) % 10
        transitional = transition_confidence >= 0.55 and visibility >= 0.35
        if transitional:
            value = next_digit if phase >= 0.5 else current
            fused = stable * 0.55
            fused[current] += transition_confidence * max(0.05, 1.0 - phase) * 0.45
            fused[next_digit] += transition_confidence * max(0.05, phase) * 0.45
            fused = fused / max(float(fused.sum()), 1e-8)
            return DigitObservation(
                position=position,
                value=value,
                confidence=round(max(float(fused[value]), transition_confidence * 0.85), 4),
                upper_digit=current,
                lower_digit=next_digit,
                transition_phase=round(phase, 4),
                transitional=True,
                current_digit=current,
                next_digit=next_digit,
                transition_confidence=round(transition_confidence, 4),
                visibility=round(visibility, 4),
                probabilities=[round(float(item), 6) for item in fused],
                source="transition-onnx",
            )
        return DigitObservation(
            position=position,
            value=digit,
            confidence=round(stable_confidence, 4),
            visibility=round(visibility, 4),
            probabilities=[round(float(item), 6) for item in stable],
            source="transition-onnx",
        )


class _OnnxDisplayDetector:
    """Detector opcional de quatro cantos e limites normalizados dos slots."""

    def __init__(self, path: str):
        self.session = ort.InferenceSession(path, providers=["CPUExecutionProvider"]) if ort and path else None
        self.input_name = self.session.get_inputs()[0].name if self.session else None

    def detect(self, image) -> DisplayDetection | None:
        if not self.session or np is None:
            return None
        height, width = image.shape[:2]
        resized = cv2.resize(image, (640, 640), interpolation=cv2.INTER_AREA)
        rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB).astype("float32") / 255.0
        outputs = self.session.run(None, {self.input_name: np.transpose(rgb, (2, 0, 1))[None, ...]})
        if not outputs:
            return None
        corners = np.asarray(outputs[0], dtype="float32").reshape(-1)[:8]
        if len(corners) != 8:
            return None
        confidence = float(np.asarray(outputs[1]).reshape(-1)[0]) if len(outputs) > 1 else 0.0
        if confidence < 0.35:
            return None
        corners = corners.reshape(4, 2)
        if float(corners.max()) <= 1.5:
            corners[:, 0] *= width
            corners[:, 1] *= height
        else:
            corners[:, 0] *= width / 640.0
            corners[:, 1] *= height / 640.0
        boundaries = []
        if len(outputs) > 2:
            boundaries = [float(value) for value in np.asarray(outputs[2]).reshape(-1)]
            boundaries = [max(0.0, min(1.0, value)) for value in boundaries]
        return DisplayDetection(
            corners=_order_corners(corners),
            confidence=_clamp(confidence),
            slot_boundaries=sorted(set(boundaries)),
        )


def hog_features(slot):
    normalized = _normalize_slot(slot, size=(28, 28))
    hog = cv2.HOGDescriptor((28, 28), (14, 14), (7, 7), (7, 7), 9)
    return hog.compute(normalized).reshape(1, -1).astype("float32")


class _PortableKnnClassifier:
    """KNN de inferencia independente do modulo opcional ``cv2.ml``.

    O artefato continua no formato OpenCV YAML, mas a leitura usa somente
    ``FileStorage`` (parte do core já exigido por todo o pipeline visual). A
    busca dos vizinhos e feita em NumPy, garantindo o mesmo caminho no
    desenvolvimento e nas imagens headless usadas em producao.
    """

    def __init__(self, path: str):
        storage = cv2.FileStorage(path, cv2.FILE_STORAGE_READ)
        try:
            if not storage.isOpened():
                raise RuntimeError("O arquivo do modelo KNN não pôde ser aberto.")
            root = storage.getNode("opencv_ml_knn")
            samples = root.getNode("samples").mat()
            responses = root.getNode("responses").mat()
        finally:
            storage.release()
        if samples is None or responses is None or samples.size == 0 or responses.size == 0:
            raise RuntimeError("O arquivo KNN foi aberto, mas não contém um modelo treinado.")
        self.samples = np.ascontiguousarray(samples, dtype=np.float32)
        self.responses = np.asarray(responses, dtype=np.float32).reshape(-1)
        if self.samples.shape[0] != self.responses.shape[0]:
            raise RuntimeError("O modelo KNN contém quantidades incompatíveis de amostras e respostas.")
        self.sample_squared_norms = np.einsum(
            "ij,ij->i",
            self.samples,
            self.samples,
            optimize=True,
        )

    def is_trained(self) -> bool:
        return bool(self.samples.size and self.responses.size)

    def classify(self, slot) -> tuple[int | None, float, list[float]]:
        features = hog_features(slot).reshape(-1)
        if features.shape[0] != self.samples.shape[1]:
            raise RuntimeError(
                f"Vetor HOG incompatível: recebido {features.shape[0]}, esperado {self.samples.shape[1]}."
            )
        # ||a-b||² = ||a||² + ||b||² - 2a.b evita materializar uma matriz de
        # diferenças em cada slot e usa a multiplicação vetorial otimizada do NumPy.
        squared_distances = (
            self.sample_squared_norms
            + float(np.dot(features, features))
            - 2.0 * np.dot(self.samples, features)
        )
        squared_distances = np.maximum(squared_distances, 0.0)
        neighbour_count = min(5, squared_distances.shape[0])
        indices = np.argpartition(squared_distances, neighbour_count - 1)[:neighbour_count]
        indices = indices[np.argsort(squared_distances[indices], kind="stable")]
        votes = [int(round(float(self.responses[index]))) for index in indices]
        labels, counts = np.unique(np.asarray(votes, dtype=np.int16), return_counts=True)
        maximum_votes = int(counts.max())
        tied = {int(label) for label, count in zip(labels, counts) if int(count) == maximum_votes}
        # OpenCV resolve empate de classes pelo menor rótulo. Reproduzir isso
        # mantém o artefato existente bit-a-bit compatível entre ambientes.
        digit = min(tied)
        vote_share = votes.count(digit) / max(len(votes), 1)
        distance_score = math.exp(-float(squared_distances[indices[0]]) / 120.0)
        confidence = _clamp(vote_share * 0.75 + distance_score * 0.25)
        scores = [votes.count(value) / max(len(votes), 1) for value in range(10)]
        return digit, confidence, scores


@lru_cache(maxsize=1)
def _trained_classifier():
    bundled_path = os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "assets", "meter-field-v3-20260622.yml")
    )
    path = settings.vision_model_path.strip() or bundled_path
    if not path or not os.path.exists(path):
        return None
    try:
        if path.lower().endswith((".yml", ".yaml", ".xml")) and cv2 is not None:
            return _PortableKnnClassifier(path)
        if ort is None:
            return None
        return _OnnxClassifier(path)
    except Exception:
        model_kind = "KNN portátil" if path.lower().endswith((".yml", ".yaml", ".xml")) else "ONNX"
        logger.exception("Nao foi possivel carregar o modelo %s de hidrometros", model_kind)
        return None


@lru_cache(maxsize=1)
def _trained_transition_classifier():
    path = settings.vision_transition_model_path.strip()
    if not path or not os.path.exists(path) or ort is None:
        return None
    try:
        return _TransitionOnnxClassifier(path)
    except Exception:
        logger.exception("Não foi possível carregar o modelo ONNX de transição")
        return None


@lru_cache(maxsize=1)
def _trained_display_detector():
    path = settings.vision_detector_model_path.strip()
    if not path or not os.path.exists(path) or ort is None:
        return None
    try:
        return _OnnxDisplayDetector(path)
    except Exception:
        logger.exception("Não foi possível carregar o detector ONNX do visor")
        return None


@lru_cache(maxsize=1)
def _sequence_ocr_engine():
    return RapidOCR() if RapidOCR is not None else None


def _ocr_detect_items(image):
    engine = _sequence_ocr_engine()
    if engine is None:
        return []
    try:
        with _sequence_ocr_lock:
            result, _ = engine(image, use_det=True, use_cls=False, use_rec=True)
    except Exception:
        logger.exception("Falha no OCR detector local")
        return []
    items = []
    for item in result or []:
        if len(item) < 3:
            continue
        items.append((
            np.asarray(item[0], dtype="float32").reshape(4, 2),
            str(item[1]),
            float(item[2]),
        ))
    return items


def _sequence_ocr(rectified) -> tuple[list[int], float]:
    """Reconhece a faixa completa sem detector de texto externo.

    O reconhecedor sequencial e forte nos digitos estaveis, mas pode omitir um
    rolete que mostra dois numeros. A fusao posterior preserva o classificador
    mecanico por slot justamente nessa posicao.
    """
    engine = _sequence_ocr_engine()
    if engine is None:
        return [], 0.0
    enlarged = cv2.resize(rectified, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
    try:
        with _sequence_ocr_lock:
            result, _ = engine(enlarged, use_det=False, use_cls=False, use_rec=True)
    except Exception:
        logger.exception("Falha no reconhecedor sequencial local")
        return [], 0.0
    if not result:
        return [], 0.0
    candidates = []
    for item in result:
        if not item:
            continue
        text = "".join(re.findall(r"\d", str(item[0])))
        score = float(item[1]) if len(item) > 1 else 0.0
        if text:
            candidates.append((text, score))
    if not candidates:
        return [], 0.0
    text, score = max(candidates, key=lambda item: (len(item[0]), item[1]))
    return [int(char) for char in text], _clamp(score)


def _candidate_sequences_from_digits(raw_digits: list[int], total_digits: int) -> list[tuple[list[int], float, bool]]:
    if len(raw_digits) == total_digits:
        return [(raw_digits, 0.0, True)]
    excess = len(raw_digits) - total_digits
    if excess <= 0 or excess > 3:
        return []
    candidates = []
    for drop_positions in combinations(range(len(raw_digits)), excess):
        sequence = [digit for index, digit in enumerate(raw_digits) if index not in drop_positions]
        # Divisórias verticais são frequentemente reconhecidas como "1".
        # Dar preferência a remover esses falsos uns conserva leituras como
        # 00251748 -> 0025748 e 002151748 -> 0025748.
        penalty = excess * 0.035 + sum(0.025 for index in drop_positions if raw_digits[index] != 1)
        candidates.append((sequence, penalty, False))
    return candidates


def _candidate_prefixes_from_digits(raw_digits: list[int], target_digits: int) -> list[tuple[list[int], float]]:
    if len(raw_digits) == target_digits:
        return [(raw_digits, 0.0)]
    excess = len(raw_digits) - target_digits
    if excess <= 0 or excess > 8:
        return []
    candidates = []
    for drop_positions in combinations(range(len(raw_digits)), excess):
        sequence = [digit for index, digit in enumerate(raw_digits) if index not in drop_positions]
        penalty = excess * 0.035
        for index in drop_positions:
            if raw_digits[index] == 1:
                continue
            # Quando a linha vem como `0090649m`, o ultimo caractere antes da
            # unidade costuma ser o rolete/unidade colados. Remover pela cauda
            # preserva o prefixo mecanico.
            penalty += 0.012 + 0.006 * (len(raw_digits) - 1 - index)
        candidates.append((sequence, penalty))
    return candidates


def _full_frame_ocr_sequences(
    image,
    total_digits: int,
    slot_digits: list[int],
    ocr_items=None,
) -> tuple[list[int], float, str | None]:
    """Busca a leitura no quadro inteiro como camada de resgate.

    Esse detector é propositalmente secundário. Ele é mais caro e pode ler
    textos como Qn, DN20, INMETRO e ponteiros; por isso só retorna sequências
    que parecem a linha do hidrômetro e, quando possível, concordam com os
    slots já recortados.
    """
    max_side = max(image.shape[:2])
    frame = image
    if ocr_items is None and max_side < 1500:
        scale = 1500 / max_side
        frame = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    items = ocr_items if ocr_items is not None else _ocr_detect_items(frame)
    best: tuple[float, list[int], str] | None = None
    for box, text, score in items:
        lowered = text.lower()
        if any(
            token in lowered
            for token in (
                "pma",
                "dn",
                "q",
                "classe",
                "inmetro",
                "ml",
                "t50",
                "r80",
                "v-r",
                "uj",
            )
        ):
            continue
        digits = [int(char) for char in re.findall(r"\d", text)]
        if len(digits) < total_digits or len(digits) > total_digits + 3:
            continue
        has_meter_hint = any(token in lowered for token in ("m", "b", "h", "）", ")"))
        if not has_meter_hint and len(digits) != total_digits:
            continue
        geometry_bonus = 0.0
        if box is not None and box.size:
            center_y = float(box[:, 1].mean()) / max(frame.shape[0], 1)
            center_x = float(box[:, 0].mean()) / max(frame.shape[1], 1)
            # A leitura principal normalmente fica na metade superior do
            # mostrador e ocupa uma linha horizontal comprida. Penaliza textos
            # técnicos mais baixos sem matar enquadramentos inclinados.
            geometry_bonus += max(0.0, 0.58 - center_y) * 0.18
            geometry_bonus -= max(0.0, center_y - 0.64) * 0.24
            geometry_bonus -= max(0.0, 0.10 - center_x) * 0.16
        for sequence, penalty, exact_length in _candidate_sequences_from_digits(digits, total_digits):
            agreement = 0
            if len(slot_digits) == total_digits:
                agreement = sum(left == right for left, right in zip(sequence, slot_digits))
            # Score composto: texto do OCR + concordância com os slots, punindo
            # deleções extras. O limiar fica no chamador.
            candidate_score = _clamp(score * 0.78 + (agreement / total_digits) * 0.22 + geometry_bonus - penalty)
            if best is None or candidate_score > best[0]:
                mode = "full_frame_sequence_exact" if exact_length else "full_frame_sequence_normalized"
                best = (candidate_score, sequence, mode)
    if best is None:
        return [], 0.0, None
    return best[1], best[0], best[2]


def _ocr_missing_tail_sequence(image, total_digits: int, ocr_items=None) -> tuple[list[int], float, str | None]:
    """Recupera ultimo rolete quando OCR le prefixo e confunde o fim com `m3`.

    Fotos inclinadas podem sair como `009064m2`: o texto sequencial tem seis
    digitos confiaveis, mas o ultimo rolete vermelho fica colado na unidade.
    Neste caso isolamos a cauda da mesma linha OCR e classificamos como slot.
    """
    items = ocr_items if ocr_items is not None else _ocr_detect_items(image)
    best: tuple[float, list[int]] | None = None
    height, width = image.shape[:2]
    for box, text, score in items:
        lowered = text.lower()
        if not any(token in lowered for token in ("m", "b", "h", "）", ")")):
            continue
        digit_source = re.split(r"[mMhHbB）)]", text, maxsplit=1)[0]
        digits = [int(char) for char in re.findall(r"[0-9]", digit_source)]
        if len(digits) != total_digits - 1:
            continue
        ordered = _order_corners(box)
        tl, tr, br, bl = ordered
        horizontal = ((tr - tl) + (br - bl)) / 2
        vertical = ((bl - tl) + (br - tr)) / 2
        box_width = float(np.linalg.norm(horizontal))
        box_height = float(np.linalg.norm(vertical))
        if box_width < width * 0.08 or box_height < height * 0.010:
            continue
        unit_x = horizontal / max(box_width, 1.0)
        unit_y = vertical / max(box_height, 1.0)
        slot_width = box_width / max(len(digits) + 1, 1)
        tail_start = slot_width * (len(digits) - 0.65)
        tail_end = box_width + slot_width * 0.10
        corners = np.array([
            tl + unit_x * tail_start - unit_y * box_height * 0.55,
            tl + unit_x * tail_end - unit_y * box_height * 0.55,
            bl + unit_x * tail_end + unit_y * box_height * 1.35,
            bl + unit_x * tail_start + unit_y * box_height * 1.35,
        ], dtype="float32")
        corners[:, 0] = np.clip(corners[:, 0], 0, width - 1)
        corners[:, 1] = np.clip(corners[:, 1], 0, height - 1)
        tail, _ = _rectify(image, corners)
        observation = _slot_observation(tail, total_digits - 1)
        if observation.value is None or observation.confidence < 0.62:
            continue
        sequence = [*digits, int(observation.value)]
        candidate_score = _clamp(score * 0.72 + observation.confidence * 0.28)
        if best is None or candidate_score > best[0]:
            best = (candidate_score, sequence)
    if best is None:
        return [], 0.0, None
    return best[1], best[0], "ocr_missing_tail_slot"


def _ocr_meter_tail_sequence(image, total_digits: int, ocr_items=None) -> tuple[list[int], float, str | None]:
    """Le linha do contador e reclassifica a cauda antes da unidade.

    Em fotos de longe/lado, OCR costuma ler `0101910164m` ou `0090649m`:
    prefixo tem separadores falsos e o ultimo rolete gruda na unidade. Aqui
    normalizamos prefixo para N-1 digitos e usamos crop fisico da cauda.
    """
    items = ocr_items if ocr_items is not None else _ocr_detect_items(image)
    meter_hints = [
        box for box, text, _ in items
        if re.fullmatch(r"\s*[mMhHbB][\d³²]?\s*", text)
        or text.strip().lower() in {"m", "m3", "m³", "m2", "m²"}
    ]

    best: tuple[float, list[int]] | None = None
    height, width = image.shape[:2]
    for box, text, score in items:
        lowered = text.lower()
        if any(token in lowered for token in ("pma", "dn", "classe", "inmetro", "ml", "t50", "r80", "uj", "akvo")):
            continue
        ordered = _order_corners(box)
        tl, tr, br, bl = ordered
        horizontal = ((tr - tl) + (br - bl)) / 2
        vertical = ((bl - tl) + (br - tr)) / 2
        box_width = float(np.linalg.norm(horizontal))
        box_height = float(np.linalg.norm(vertical))
        if box_width < width * 0.08 or box_height < height * 0.010:
            continue

        has_meter_hint = any(token in lowered for token in ("m", "h", "b", "）", ")"))
        if not has_meter_hint:
            center_y = float(box[:, 1].mean())
            right_x = float(box[:, 0].max())
            for hint_box in meter_hints:
                hint_center_y = float(hint_box[:, 1].mean())
                hint_left_x = float(hint_box[:, 0].min())
                if abs(hint_center_y - center_y) <= box_height * 1.7 and 0 <= hint_left_x - right_x <= box_width * 0.22:
                    has_meter_hint = True
                    hint_width = float(hint_box[:, 0].max() - hint_box[:, 0].min())
                    extra = max(0.0, hint_left_x + hint_width - right_x)
                    tr = tr + horizontal / max(box_width, 1.0) * extra
                    br = br + horizontal / max(box_width, 1.0) * extra
                    horizontal = ((tr - tl) + (br - bl)) / 2
                    box_width = float(np.linalg.norm(horizontal))
                    break
        if not has_meter_hint:
            continue

        digit_source = re.split(r"[mMhHbB）)]", text, maxsplit=1)[0]
        raw_digits = [int(char) for char in re.findall(r"[0-9]", digit_source)]
        if len(raw_digits) < total_digits - 1 or len(raw_digits) > total_digits + 8:
            continue
        prefixes = _candidate_prefixes_from_digits(raw_digits, total_digits - 1)
        if not prefixes:
            continue
        prefix, prefix_penalty = min(
            prefixes,
            key=lambda item: (
                item[1],
                abs((item[0][0] if item[0] else 0) - (raw_digits[0] if raw_digits else 0)),
            ),
        )

        unit_x = horizontal / max(box_width, 1.0)
        unit_y = vertical / max(box_height, 1.0)
        slot_width = box_width / max(total_digits + 0.75, 1)
        tail_start = slot_width * (total_digits - 1 - 0.72)
        tail_end = slot_width * (total_digits + 0.28)
        corners = np.array([
            tl + unit_x * tail_start - unit_y * box_height * 0.55,
            tl + unit_x * tail_end - unit_y * box_height * 0.55,
            bl + unit_x * tail_end + unit_y * box_height * 1.35,
            bl + unit_x * tail_start + unit_y * box_height * 1.35,
        ], dtype="float32")
        corners[:, 0] = np.clip(corners[:, 0], 0, width - 1)
        corners[:, 1] = np.clip(corners[:, 1], 0, height - 1)
        tail, _ = _rectify(image, corners)
        observation = _slot_observation(tail, total_digits - 1)
        if observation.value is None or observation.confidence < 0.52:
            continue
        sequence = [*prefix, int(observation.value)]
        candidate_score = _clamp(score * 0.68 + observation.confidence * 0.32 - prefix_penalty)
        if best is None or candidate_score > best[0]:
            best = (candidate_score, sequence)
    if best is None:
        return [], 0.0, None
    return best[1], best[0], "ocr_meter_tail_slot"


def _ocr_counter_window_candidate(image, total_digits: int, ocr_items=None):
    """Usa detector OCR como localizador da janela quando a ancora vermelha falha.

    Em fotos de longe, os glifos vermelhos ficam pequenos demais para a mascara
    HSV, mas o detector de texto ainda encontra a linha `009064m`. O texto pode
    perder o ultimo rolete; por isso expandimos a caixa para a direita e para
    baixo antes da retificacao.
    """
    items = ocr_items if ocr_items is not None else _ocr_detect_items(image)
    best: tuple[float, np.ndarray] | None = None
    height, width = image.shape[:2]
    meter_hints = [
        box for box, text, _ in items
        if re.fullmatch(r"\s*[mM][\d³²]?\s*", text)
    ]
    for box, text, score in items:
        lowered = text.lower()
        if any(token in lowered for token in ("pma", "dn", "q", "classe", "inmetro", "ml", "t50", "r80", "uj")):
            continue
        digits = re.findall(r"\d", text)
        if not (total_digits - 1 <= len(digits) <= total_digits + 8):
            continue
        has_meter_hint = any(token in lowered for token in ("m", "b", "h", "）", ")"))
        ordered = _order_corners(box)
        tl, tr, br, bl = ordered
        horizontal = ((tr - tl) + (br - bl)) / 2
        vertical = ((bl - tl) + (br - tr)) / 2
        box_width = float(np.linalg.norm(horizontal))
        box_height = float(np.linalg.norm(vertical))
        if box_width < width * 0.08 or box_height < height * 0.010:
            continue
        if has_meter_hint:
            # O detector às vezes inclui `m3` dentro da mesma caixa. Retira a
            # unidade antes de dividir a faixa em sete slots.
            unit_match = re.search(r"[mMhHbB）)]", text)
            if unit_match and unit_match.start() > 0:
                content_ratio = max(0.55, min(1.0, (unit_match.start() + 0.28) / max(len(text), 1)))
                tr = tl + (tr - tl) * content_ratio
                br = bl + (br - bl) * content_ratio
                horizontal = ((tr - tl) + (br - bl)) / 2
                box_width = float(np.linalg.norm(horizontal))
        else:
            center_y = float(box[:, 1].mean())
            right_x = float(box[:, 0].max())
            for hint_box in meter_hints:
                hint_center_y = float(hint_box[:, 1].mean())
                hint_left_x = float(hint_box[:, 0].min())
                if abs(hint_center_y - center_y) <= box_height * 1.8 and 0 <= hint_left_x - right_x <= box_width * 0.28:
                    has_meter_hint = True
                    break
        if not has_meter_hint and len(digits) != total_digits:
            continue
        unit_x = horizontal / max(box_width, 1.0)
        unit_y = vertical / max(box_height, 1.0)
        # Separadores do visor aparecem como vários algarismos `1`; eles não
        # podem encolher a largura nominal de cada rolete.
        slot_width = box_width / max(total_digits if len(digits) >= total_digits else total_digits - 1, 1)
        missing = max(total_digits - len(digits), 0)
        left_extension = slot_width * 0.20
        # Quando o OCR reconhece a unidade `m3`, a caixa ja inclui o texto
        # depois dos roletes. Se ainda expandirmos, a unidade vira um slot.
        right_extension = slot_width * (
            0.12 if len(digits) == total_digits
            else 0.72 + missing
        )
        vertical_padding = max(box_height * 0.38, slot_width * 0.14)
        corners = np.array([
            tl - unit_x * left_extension - unit_y * vertical_padding,
            tr + unit_x * right_extension - unit_y * vertical_padding,
            br + unit_x * right_extension + unit_y * vertical_padding,
            bl - unit_x * left_extension + unit_y * vertical_padding,
        ], dtype="float32")
        corners[:, 0] = np.clip(corners[:, 0], 0, width - 1)
        corners[:, 1] = np.clip(corners[:, 1], 0, height - 1)
        center_y = float(box[:, 1].mean()) / max(height, 1)
        score = score + min(len(digits), total_digits) * 0.05 - max(0.0, center_y - 0.66) * 0.3
        if best is None or score > best[0]:
            best = (score, corners)
    return best[1] if best else None


def _meter_unit_window_candidate(image, total_digits: int, ocr_items=None):
    """Reconstrói a janela a partir do `m³` quando os dígitos somem no reflexo."""
    items = ocr_items if ocr_items is not None else _ocr_detect_items(image)
    height, width = image.shape[:2]
    best: tuple[float, np.ndarray] | None = None
    for box, text, score in items:
        if not re.fullmatch(r"\s*[mM][\d³²]?\s*", text):
            continue
        center_x = float(box[:, 0].mean()) / max(width, 1)
        center_y = float(box[:, 1].mean()) / max(height, 1)
        if not (0.45 <= center_x <= 0.94 and 0.24 <= center_y <= 0.60):
            continue
        tl, tr, br, bl = _order_corners(box)
        horizontal = ((tr - tl) + (br - bl)) / 2
        vertical = ((bl - tl) + (br - tr)) / 2
        unit_width = float(np.linalg.norm(horizontal))
        unit_height = float(np.linalg.norm(vertical))
        if unit_width < 2 or unit_height < height * 0.008:
            continue
        unit_x = horizontal / unit_width
        unit_y = vertical / unit_height
        slot_width = max(unit_height * 1.90, width * 0.026)
        strip_height = max(unit_height * 2.15, slot_width * 0.88)
        unit_left = (tl + bl) / 2
        strip_right = unit_left - unit_x * slot_width * 0.10 - unit_y * unit_height * 0.38
        strip_left = strip_right - unit_x * slot_width * total_digits
        corners = np.array([
            strip_left - unit_y * strip_height / 2,
            strip_right - unit_y * strip_height / 2,
            strip_right + unit_y * strip_height / 2,
            strip_left + unit_y * strip_height / 2,
        ], dtype="float32")
        corners[:, 0] = np.clip(corners[:, 0], 0, width - 1)
        corners[:, 1] = np.clip(corners[:, 1], 0, height - 1)
        candidate_score = score + center_x * 0.08 - abs(center_y - 0.41) * 0.20
        if best is None or candidate_score > best[0]:
            best = (candidate_score, corners)
    return best[1] if best else None


def _observations_from_counter_strip(rectified, total_digits: int) -> list[DigitObservation]:
    """Classifica uma faixa candidata mantendo o mesmo recorte do decoder principal."""
    if rectified is None or rectified.size == 0:
        return []
    height, width = rectified.shape[:2]
    margin_x = max(int(width * 0.025), 1)
    margin_y = max(int(height * 0.08), 1)
    usable = rectified[margin_y:height - margin_y, margin_x:width - margin_x]
    if usable.size == 0:
        return []
    slot_width = usable.shape[1] / total_digits
    observations = []
    for index in range(total_digits):
        start = max(0, int(index / total_digits * usable.shape[1] - slot_width * 0.08))
        end = min(usable.shape[1], int((index + 1) / total_digits * usable.shape[1] + slot_width * 0.08))
        if end <= start:
            return []
        observations.append(_slot_observation(usable[:, start:end], index))
    return observations


def _ocr_transition_sequence_candidate(
    image,
    total_digits: int,
    ocr_items=None,
) -> tuple[list[int], float, DigitObservation | None]:
    """Confirma a cauda por geometria quando o OCR achata um rolete em transicao.

    Em vez de confiar em um unico recorte, testa dois alinhamentos pequenos e
    previamente definidos. A sequencia completa so e aceita quando os slots do
    prefixo sao fortes e o ultimo slot reconhece um par mecanico consecutivo.
    Um recorte direto antes da unidade preserva a evidencia da cauda mesmo
    quando a perspectiva impede classificar os seis slots anteriores.
    """
    items = ocr_items if ocr_items is not None else _ocr_detect_items(image)
    height, width = image.shape[:2]
    sequence_candidates: list[tuple[float, list[int], DigitObservation]] = []
    tail_candidates: list[DigitObservation] = []

    for box, text, score in items:
        lowered = text.lower()
        if any(token in lowered for token in ("pma", "dn", "q", "classe", "inmetro", "ml", "t50", "r80", "uj")):
            continue
        raw_digits = re.findall(r"\d", text)
        if not (total_digits - 1 <= len(raw_digits) <= total_digits + 8):
            continue
        ordered = _order_corners(box)
        original_tl, original_tr, original_br, original_bl = ordered
        original_horizontal = ((original_tr - original_tl) + (original_br - original_bl)) / 2
        original_width = float(np.linalg.norm(original_horizontal))
        original_vertical = ((original_bl - original_tl) + (original_br - original_tr)) / 2
        original_height = float(np.linalg.norm(original_vertical))
        if original_width < width * 0.08 or original_height < height * 0.010:
            continue

        # Perfis conservadores: um para linha completa/separada da unidade e
        # outro para a caixa em que `m3` ficou grudado ao ultimo rolete.
        profiles = (
            (1.00, 0.20, 0.15, 0.35, "slot"),
            (0.90, 0.10, 0.35, 0.35, "box"),
        )
        for ratio, left_slots, right_slots, vertical_factor, vertical_base in profiles:
            tl = original_tl
            bl = original_bl
            tr = tl + (original_tr - tl) * ratio
            br = bl + (original_br - bl) * ratio
            horizontal = ((tr - tl) + (br - bl)) / 2
            vertical = ((bl - tl) + (br - tr)) / 2
            box_width = float(np.linalg.norm(horizontal))
            box_height = float(np.linalg.norm(vertical))
            if box_width < 1 or box_height < 1:
                continue
            unit_x = horizontal / box_width
            unit_y = vertical / box_height
            slot_width = box_width / total_digits
            vertical_size = slot_width if vertical_base == "slot" else box_height
            corners = np.array([
                tl - unit_x * slot_width * left_slots - unit_y * vertical_size * vertical_factor,
                tr + unit_x * slot_width * right_slots - unit_y * vertical_size * vertical_factor,
                br + unit_x * slot_width * right_slots + unit_y * vertical_size * vertical_factor,
                bl - unit_x * slot_width * left_slots + unit_y * vertical_size * vertical_factor,
            ], dtype="float32")
            corners[:, 0] = np.clip(corners[:, 0], 0, width - 1)
            corners[:, 1] = np.clip(corners[:, 1], 0, height - 1)
            try:
                rectified, _ = _rectify(image, corners)
                observations = _observations_from_counter_strip(rectified, total_digits)
            except Exception:
                continue
            if len(observations) != total_digits or any(item.value is None for item in observations):
                continue
            tail = observations[-1]
            if not tail.transitional or tail.current_digit is None or tail.next_digit is None:
                continue
            prefix_confidence = float(np.mean([item.confidence for item in observations[:-1]]))
            if prefix_confidence < 0.86 or tail.confidence < 0.56:
                continue
            sequence = [int(item.value) for item in observations]
            candidate_score = _clamp(prefix_confidence * 0.62 + tail.confidence * 0.30 + score * 0.08)
            sequence_candidates.append((candidate_score, sequence, tail))

        # Caixa com unidade embutida: o ultimo rolete ocupa aproximadamente uma
        # altura da propria linha e termina uma altura antes da borda do `m`.
        if re.search(r"[mMhHbB）)]", text):
            unit_x = original_horizontal / max(original_width, 1.0)
            unit_y = original_vertical / max(original_height, 1.0)
            right_center = (original_tr + original_br) / 2 - unit_x * original_height
            left_center = right_center - unit_x * original_height
            corners = np.array([
                left_center - unit_y * original_height * 1.5,
                right_center - unit_y * original_height * 1.5,
                right_center + unit_y * original_height * 1.5,
                left_center + unit_y * original_height * 1.5,
            ], dtype="float32")
            corners[:, 0] = np.clip(corners[:, 0], 0, width - 1)
            corners[:, 1] = np.clip(corners[:, 1], 0, height - 1)
            try:
                tail_crop, _ = _rectify(image, corners)
                tail = _slot_observation(tail_crop, total_digits - 1)
            except Exception:
                tail = None
            if (
                tail is not None
                and tail.value is not None
                and tail.transitional
                and tail.current_digit is not None
                and tail.next_digit is not None
                and tail.confidence >= 0.56
            ):
                tail_candidates.append(tail)

    if sequence_candidates:
        best = max(sequence_candidates, key=lambda item: item[0])
        return best[1], best[0], best[2]
    if tail_candidates:
        best_tail = max(tail_candidates, key=lambda item: item.confidence)
        return [], best_tail.confidence, best_tail
    return [], 0.0, None


def _meter_unit_tail_observation(image, total_digits: int, ocr_items=None) -> DigitObservation | None:
    """Le o ultimo slot numa faixa alinhada pela base da unidade `m3`."""
    items = ocr_items if ocr_items is not None else _ocr_detect_items(image)
    height, width = image.shape[:2]
    candidates: list[tuple[float, DigitObservation]] = []
    for box, text, score in items:
        if not re.fullmatch(r"\s*[mM][\d³²]?\s*", text):
            continue
        tl, tr, br, bl = _order_corners(box)
        horizontal = ((tr - tl) + (br - bl)) / 2
        vertical = ((bl - tl) + (br - tr)) / 2
        unit_width = float(np.linalg.norm(horizontal))
        unit_height = float(np.linalg.norm(vertical))
        if unit_width < 2 or unit_height < height * 0.008:
            continue
        unit_x = horizontal / unit_width
        unit_y = vertical / unit_height
        slot_width = max(unit_height * 1.90, width * 0.026)
        unit_left = (tl + bl) / 2
        strip_right = unit_left - unit_x * slot_width * 0.08
        strip_left = strip_right - unit_x * slot_width * total_digits
        bottom_left = strip_left + unit_y * unit_height * 0.12
        bottom_right = strip_right + unit_y * unit_height * 0.12
        corners = np.array([
            bottom_left - unit_y * unit_height * 2.80,
            bottom_right - unit_y * unit_height * 2.80,
            bottom_right,
            bottom_left,
        ], dtype="float32")
        corners[:, 0] = np.clip(corners[:, 0], 0, width - 1)
        corners[:, 1] = np.clip(corners[:, 1], 0, height - 1)
        try:
            rectified, _ = _rectify(image, corners)
            rectified_height, rectified_width = rectified.shape[:2]
            margin_x = max(int(rectified_width * 0.015), 1)
            margin_y = max(int(rectified_height * 0.05), 1)
            usable = rectified[
                margin_y:rectified_height - margin_y,
                margin_x:rectified_width - margin_x,
            ]
            slot_width = usable.shape[1] / total_digits
            start = max(0, int((total_digits - 1) / total_digits * usable.shape[1] - slot_width * 0.05))
            end = min(usable.shape[1], int(usable.shape[1] + slot_width * 0.05))
            tail = _slot_observation(usable[:, start:end], total_digits - 1)
        except Exception:
            continue
        if tail.value is not None:
            candidates.append((_clamp(score * 0.18 + tail.confidence * 0.82), tail))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _fuse_digit_sequences(
    slot_digits: list[int],
    ocr_digits: list[int],
    ocr_confidence: float,
) -> tuple[list[int], str | None]:
    """Alinha OCR de faixa e slots, tolerando uma omissao ou insercao."""
    total = len(slot_digits)
    if ocr_confidence < 0.78 or not slot_digits:
        return slot_digits, None
    if len(ocr_digits) == total:
        return ocr_digits, "sequence_exact"
    if len(ocr_digits) == total - 1:
        # O rolete em transicao costuma ser omitido. Encontra a posicao cuja
        # retirada do resultado por slots melhor explica a sequencia OCR.
        position = max(
            range(total),
            key=lambda missing: sum(
                left == right
                for left, right in zip(
                    slot_digits[:missing] + slot_digits[missing + 1:],
                    ocr_digits,
                )
            ),
        )
        fused = list(ocr_digits)
        fused.insert(position, slot_digits[position])
        return fused, "sequence_missing_transition"
    if len(ocr_digits) == total + 1:
        # Uma divisoria vertical pode virar o algarismo 1. Remove o caractere
        # que maximiza a concordancia com os sete classificadores posicionais.
        position = max(
            range(len(ocr_digits)),
            key=lambda extra: sum(
                left == right
                for left, right in zip(
                    ocr_digits[:extra] + ocr_digits[extra + 1:],
                    slot_digits,
                )
            ),
        )
        return ocr_digits[:position] + ocr_digits[position + 1:], "sequence_removed_separator"
    if total + 1 < len(ocr_digits) <= total + 3:
        candidates = _candidate_sequences_from_digits(ocr_digits, total)
        if candidates:
            sequence, _, exact_length = min(
                candidates,
                key=lambda item: (
                    -sum(left == right for left, right in zip(item[0], slot_digits)),
                    item[1],
                ),
            )
            if not exact_length:
                return sequence, "sequence_removed_separators"
    return slot_digits, None


def _normalize_slot(slot, size=(64, 96)):
    gray = cv2.cvtColor(slot, cv2.COLOR_BGR2GRAY) if slot.ndim == 3 else slot
    # Remove as barras verticais e as bordas superior/inferior da janela. Elas
    # eram maiores que o proprio glifo e faziam todos os slots parecerem 3/8/9.
    crop_x = max(int(gray.shape[1] * 0.16), 1)
    crop_y = max(int(gray.shape[0] * 0.07), 1)
    if gray.shape[1] > crop_x * 2 + 4 and gray.shape[0] > crop_y * 2 + 4:
        gray = gray[crop_y:gray.shape[0] - crop_y, crop_x:gray.shape[1] - crop_x]
    gray = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(gray)
    gray = cv2.GaussianBlur(gray, (3, 3), 0)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

    count, labels, stats, centroids = cv2.connectedComponentsWithStats(binary, 8)
    selected_label = None
    selected_score = -1.0
    image_height, image_width = binary.shape
    for label in range(1, count):
        x, y, component_width, component_height, area = stats[label]
        if component_height < image_height * 0.32 or component_width < max(2, image_width * 0.055):
            continue
        if component_width > image_width * 0.96:
            continue
        center_x, center_y = centroids[label]
        center_penalty = abs(center_x - image_width / 2) / max(image_width, 1)
        vertical_penalty = abs(center_y - image_height / 2) / max(image_height, 1)
        score = area * (1.25 - min(center_penalty + vertical_penalty * 0.35, 1.0))
        if score > selected_score:
            selected_score = score
            selected_label = label
    if selected_label is not None:
        binary = np.where(labels == selected_label, 255, 0).astype("uint8")

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
    return None, 0.0, [0.0] * 10


def _slot_observation(slot, position: int) -> DigitObservation:
    transition_classifier = _trained_transition_classifier()
    if transition_classifier is not None:
        learned = transition_classifier.observe(slot, position)
        if learned is not None:
            return learned
    value, confidence, probabilities = _classify(slot)
    height = slot.shape[0]
    upper, upper_conf, upper_probabilities = _classify(slot[: max(int(height * 0.62), 1)])
    lower, lower_conf, lower_probabilities = _classify(slot[min(int(height * 0.38), height - 1):])
    center_start = max(int(height * 0.27), 0)
    center_end = max(center_start + 1, min(int(height * 0.73), height))
    center, center_conf, center_probabilities = _classify(slot[center_start:center_end])
    normalized_probabilities = list(probabilities[:10])
    normalized_probabilities.extend([0.0] * (10 - len(normalized_probabilities)))
    contrast = float(cv2.cvtColor(slot, cv2.COLOR_BGR2GRAY).std()) if slot.ndim == 3 else float(slot.std())
    visibility = _clamp(contrast / 58.0)
    transitional = (
        upper is not None
        and lower is not None
        and upper != lower
        and ((upper + 1) % 10 == lower or (lower + 1) % 10 == upper)
        and min(upper_conf, lower_conf) >= 0.32
        and (confidence < 0.88 or value in (upper, lower))
    )
    if transitional:
        current = upper if (upper + 1) % 10 == lower else lower
        next_digit = (current + 1) % 10

        def support(scores: list[float], digit: int) -> float:
            return float(scores[digit]) if len(scores) > digit else 0.0

        # A fase agora é sustentada pela identidade visual nas regiões do
        # rolete, sobretudo pela faixa central que representa a linha de leitura.
        # Isso elimina o antigo uso da luminosidade como aproximação da fase.
        phase = _clamp(
            support(probabilities, next_digit) * 0.15
            + support(center_probabilities, next_digit) * 0.55
            + support(lower_probabilities, next_digit) * 0.20
            + support(upper_probabilities, next_digit) * 0.10
        )
        center_choice = center if center in (current, next_digit) and center_conf >= 0.34 else None
        chosen = center_choice if center_choice is not None else (next_digit if phase >= 0.5 else current)
        transition_confidence = _clamp(
            min(upper_conf, lower_conf) * 0.45
            + center_conf * 0.35
            + confidence * 0.20
        )
        normalized_probabilities[current] += max(0.05, 1.0 - phase) * transition_confidence
        normalized_probabilities[next_digit] += max(0.05, phase) * transition_confidence
        probability_total = sum(normalized_probabilities) or 1.0
        return DigitObservation(
            position=position,
            value=chosen,
            confidence=round(max(confidence * 0.65, transition_confidence * 0.88), 4),
            upper_digit=upper,
            lower_digit=lower,
            transition_phase=phase,
            transitional=True,
            current_digit=current,
            next_digit=next_digit,
            transition_confidence=transition_confidence,
            visibility=visibility,
            probabilities=[round(item / probability_total, 6) for item in normalized_probabilities],
        )
    return DigitObservation(
        position=position,
        value=value,
        confidence=round(confidence, 4),
        visibility=visibility,
        probabilities=[round(item, 6) for item in normalized_probabilities],
    )


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


def _prediction_anomaly(predicted_value: float | None, previous_value: float | None) -> str | None:
    """Rejeita uma sugestão mecanicamente possível, mas operacionalmente absurda."""
    if predicted_value is None or previous_value is None:
        return None
    delta = predicted_value - previous_value
    if delta < -0.001:
        return "below_previous_reading"
    if delta > max(100.0, previous_value * 0.5):
        return "implausible_consumption_jump"
    return None


class MeterVisionService:
    def inspect_capture(
        self,
        image_base64: str,
        *,
        red_digits: int | None = 3,
        black_digits: int | None = None,
    ) -> dict:
        """Quality gate rápido, sem OCR, usado antes de enviar o burst."""

        try:
            image = _decode_image(image_base64)
        except Exception:
            return {
                "usable": False,
                "recapture_reason": "Não foi possível abrir a imagem. Refaça a captura.",
                "guidance_code": "decode_failed",
            }

        original_height, original_width = image.shape[:2]
        # O preflight roda antes de cada frame do burst. Processar uma foto de
        # 5-12 MP inteira não melhora foco/perspectiva, mas multiplica CPU no
        # container. Mantemos a proporção e 1200 px no maior lado, resolução
        # suficiente para a âncora vermelha e para o contorno do visor.
        inspection_image = image
        maximum_side = max(original_height, original_width)
        if maximum_side > 1200:
            scale = 1200.0 / maximum_side
            inspection_image = cv2.resize(
                image,
                (max(1, int(original_width * scale)), max(1, int(original_height * scale))),
                interpolation=cv2.INTER_AREA,
            )

        resolved_red = red_digits if red_digits is not None and red_digits >= 0 else 3
        resolved_black = black_digits or 4
        detector = _trained_display_detector()
        learned_detection = detector.detect(inspection_image) if detector is not None else None
        corners = learned_detection.corners if learned_detection is not None else None
        if corners is None:
            corners = _red_roller_strip_candidate(inspection_image, resolved_red, resolved_black)
        used_fallback = corners is None
        if corners is None:
            corners, _ = _display_candidate(inspection_image)
        rectified, perspective = _rectify(inspection_image, corners)
        quality = _quality(rectified)
        quality.perspective = perspective
        # O preflight deve barrar somente defeitos inequívocos. O motor completo
        # ainda possui detector OCR e caminhos de resgate que recuperam fotos
        # que o detector geométrico rápido não localiza sozinho.
        quality.usable = True
        quality.recapture_reason = None

        height, width = inspection_image.shape[:2]
        ordered = _order_corners(corners)
        display_width = max(
            float(np.linalg.norm(ordered[1] - ordered[0])),
            float(np.linalg.norm(ordered[2] - ordered[3])),
        )
        display_height = max(
            float(np.linalg.norm(ordered[3] - ordered[0])),
            float(np.linalg.norm(ordered[2] - ordered[1])),
        )
        display_area_ratio = (display_width * display_height) / max(float(width * height), 1.0)

        guidance_code = None
        if display_area_ratio < 0.008:
            quality.usable = False
            quality.recapture_reason = "O visor está pequeno na foto. Aproxime a câmera dos números."
            guidance_code = "move_closer"
        elif perspective > 0.86:
            quality.usable = False
            quality.recapture_reason = "Ângulo muito lateral. Posicione a câmera de frente para o visor."
            guidance_code = "align_front"
        elif quality.blur > 0.92:
            quality.usable = False
            quality.recapture_reason = "A imagem ficou muito desfocada. Firme o aparelho e toque novamente."
            guidance_code = "hold_steady"
        elif quality.glare > 0.82:
            quality.usable = False
            quality.recapture_reason = "O reflexo encobriu os números. Mude levemente o ângulo ou desligue a luz."
            guidance_code = "reduce_glare"
        elif quality.darkness > 0.86:
            quality.usable = False
            quality.recapture_reason = "O visor ficou escuro demais. Ilumine sem apontar a luz diretamente."
            guidance_code = "increase_light"
        elif quality.contrast < 0.10:
            quality.usable = False
            quality.recapture_reason = "Os números ficaram sem contraste suficiente. Aproxime e ajuste a iluminação."
            guidance_code = "improve_contrast"

        return {
            **asdict(quality),
            "guidance_code": guidance_code,
            "display_found": not used_fallback,
            "display_area_ratio": round(display_area_ratio, 6),
            "image_width": original_width,
            "image_height": original_height,
            "inspection_width": width,
            "inspection_height": height,
        }

    def analyze(
        self,
        image_base64: str,
        *,
        red_digits: int | None = 3,
        black_digits: int | None = None,
        previous_value: float | None = None,
        expensive_ocr: bool = True,
        hydrometer_brand: str | None = None,
        hydrometer_model: str | None = None,
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

        frame_quality = _quality(image)
        resolved_black_digits = black_digits or 4
        total_digits = resolved_black_digits + red_digits
        total_digits = max(3, min(total_digits, 10))
        detector = _trained_display_detector()
        learned_detection = detector.detect(image) if detector is not None else None
        corners = learned_detection.corners if learned_detection is not None else None
        display_source = "detector_onnx" if learned_detection is not None else "red_roller_anchor"
        if corners is None:
            corners = _red_roller_strip_candidate(image, red_digits, resolved_black_digits)
        used_fallback_roi = corners is None
        used_ocr_window = False
        ocr_items = None
        if corners is None and expensive_ocr:
            ocr_items = _ocr_detect_items(image)
            corners = _ocr_counter_window_candidate(image, total_digits, ocr_items)
            unit_anchored = False
            if corners is None:
                corners = _meter_unit_window_candidate(image, total_digits, ocr_items)
                unit_anchored = corners is not None
            used_ocr_window = corners is not None
            if used_ocr_window:
                display_source = "meter_unit_anchor" if unit_anchored else "ocr_window"
            used_fallback_roi = corners is None
        if corners is None:
            corners, used_fallback_roi = _display_candidate(image)
            display_source = "geometric_fallback" if not used_fallback_roi else "guide_fallback"
        rectified, perspective = _rectify(image, corners)
        # Nitidez do cenário inteiro (tampa, chão, tubos) não representa a
        # legibilidade dos roletes. A decisão deve usar a faixa retificada.
        quality = _quality(rectified)
        quality.perspective = perspective
        if perspective > 0.72 and quality.recapture_reason is None:
            quality.usable = False
            quality.recapture_reason = "Angulo muito lateral. Posicione a camera mais de frente para o visor."

        # O modelo de campo é obrigatório. Quando ele falha, continuar apenas
        # com fontes sintéticas/OCR genérico gera números convincentes e errados.
        if _trained_classifier() is None:
            ok, encoded = cv2.imencode(".jpg", rectified, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
            quality_payload = asdict(quality)
            quality_payload["model_ready"] = False
            quality_payload["recapture_reason"] = "Leitura automática temporariamente indisponível. Confirme os números pela foto no dashboard."
            return VisionResult(
                predicted_code=None,
                predicted_value=None,
                confidence=0.0,
                auto_fill_allowed=False,
                red_digits=red_digits,
                black_digits=black_digits,
                model_version=settings.vision_model_version,
                quality=quality_payload,
                digits=[],
                alternatives=[],
                flags=["trained_model_unavailable"],
                rectified_jpeg=encoded.tobytes() if ok else None,
                decision="confirm",
                calibrated_confidence=0.0,
                decoder_version=None,
            )

        margin_x = max(int(rectified.shape[1] * 0.025), 1)
        margin_y = max(int(rectified.shape[0] * 0.08), 1)
        usable_roi = rectified[margin_y:rectified.shape[0] - margin_y, margin_x:rectified.shape[1] - margin_x]
        learned_boundaries = learned_detection.slot_boundaries if learned_detection is not None else []
        if len(learned_boundaries) == total_digits + 1:
            boundaries = learned_boundaries
        else:
            boundaries = [index / total_digits for index in range(total_digits + 1)]
        slot_width = usable_roi.shape[1] / total_digits
        observations = []
        slots = []
        for index in range(total_digits):
            start = max(0, int(boundaries[index] * usable_roi.shape[1] - slot_width * 0.08))
            end = min(usable_roi.shape[1], int(boundaries[index + 1] * usable_roi.shape[1] + slot_width * 0.08))
            slot = usable_roi[:, start:end]
            slots.append(slot)
            observations.append(_slot_observation(slot, index))

        slot_digits = [int(item.value) for item in observations if item.value is not None]
        original_slot_values = [item.value for item in observations]
        original_slot_confidences = [item.confidence for item in observations]
        ocr_digits, ocr_confidence = _sequence_ocr(rectified) if expensive_ocr else ([], 0.0)
        fused_digits, fusion_mode = _fuse_digit_sequences(slot_digits, ocr_digits, ocr_confidence)
        if fusion_mode == "sequence_exact" and len(fused_digits) == total_digits and len(slot_digits) == total_digits:
            guarded_digits = list(fused_digits)
            guarded_positions = []
            for index, (observation, ocr_digit) in enumerate(zip(observations, fused_digits)):
                if observation.value is None or int(observation.value) == int(ocr_digit):
                    continue
                # Quando o rolete está subindo, o OCR sequencial enxerga uma
                # "foto inteira" do caractere e frequentemente escolhe o número
                # errado (ex.: metade de 5 parecendo 0). O classificador por slot
                # olha a janela física daquele rolete e preserva a hipótese
                # mecânica nas posições instáveis.
                if ocr_confidence < 0.94 and not observation.transitional and observation.confidence >= 0.88:
                    guarded_digits[index] = int(observation.value)
                    guarded_positions.append(index)
            if guarded_positions:
                fused_digits = guarded_digits
                fusion_mode = "sequence_exact_slot_guard"
        if fusion_mode and len(fused_digits) == total_digits:
            for observation, digit in zip(observations, fused_digits):
                observation.value = digit
            predicted_value = int("".join(map(str, fused_digits))) / (10 ** max(red_digits, 0))
            alternatives = [predicted_value]
            flags = [fusion_mode]
        else:
            predicted_value, alternatives, flags = _temporal_candidates(observations, red_digits, previous_value)
        full_frame_digits: list[int] = []
        full_frame_confidence = 0.0
        full_frame_mode = None
        missing_tail_digits: list[int] = []
        missing_tail_confidence = 0.0
        missing_tail_mode = None
        meter_tail_digits: list[int] = []
        meter_tail_confidence = 0.0
        meter_tail_mode = None
        transition_digits: list[int] = []
        transition_confidence = 0.0
        transition_tail: DigitObservation | None = None
        unit_tail: DigitObservation | None = None
        if expensive_ocr and (fusion_mode is None or used_fallback_roi or used_ocr_window):
            if ocr_items is None:
                ocr_items = _ocr_detect_items(image)
            full_frame_digits, full_frame_confidence, full_frame_mode = _full_frame_ocr_sequences(
                image,
                total_digits,
                slot_digits,
                ocr_items,
            )
            missing_tail_digits, missing_tail_confidence, missing_tail_mode = _ocr_missing_tail_sequence(
                image,
                total_digits,
                ocr_items,
            )
            meter_tail_digits, meter_tail_confidence, meter_tail_mode = _ocr_meter_tail_sequence(
                image,
                total_digits,
                ocr_items,
            )
            transition_digits, transition_confidence, transition_tail = _ocr_transition_sequence_candidate(
                image,
                total_digits,
                ocr_items,
            )
            if display_source == "meter_unit_anchor":
                unit_tail = _meter_unit_tail_observation(image, total_digits, ocr_items)
        full_frame_applied = False
        if (
            full_frame_mode
            and len(full_frame_digits) == total_digits
            and (fusion_mode is None or used_fallback_roi)
            and full_frame_confidence >= (0.60 if full_frame_mode == "full_frame_sequence_exact" else 0.68)
        ):
            for observation, digit in zip(observations, full_frame_digits):
                observation.value = digit
            predicted_value = int("".join(map(str, full_frame_digits))) / (10 ** max(red_digits, 0))
            alternatives = [predicted_value]
            flags = [full_frame_mode] + flags
            full_frame_applied = True
        missing_tail_applied = False
        if (
            missing_tail_mode
            and len(missing_tail_digits) == total_digits
            and missing_tail_confidence >= 0.66
            and (predicted_value is None or used_ocr_window)
        ):
            for observation, digit in zip(observations, missing_tail_digits):
                observation.value = digit
            predicted_value = int("".join(map(str, missing_tail_digits))) / (10 ** max(red_digits, 0))
            alternatives = sorted({*(alternatives or []), predicted_value})[:8]
            flags = [missing_tail_mode] + flags
            missing_tail_applied = True
        meter_tail_applied = False
        if (
            meter_tail_mode
            and len(meter_tail_digits) == total_digits
            and meter_tail_confidence >= 0.58
            and (predicted_value is None or used_fallback_roi or used_ocr_window or "full_frame_sequence_exact" in flags)
            and (not missing_tail_applied or meter_tail_confidence >= missing_tail_confidence + 0.06)
        ):
            for observation, digit in zip(observations, meter_tail_digits):
                observation.value = digit
            predicted_value = int("".join(map(str, meter_tail_digits))) / (10 ** max(red_digits, 0))
            alternatives = sorted({*(alternatives or []), predicted_value})[:8]
            flags = [meter_tail_mode] + flags
            meter_tail_applied = True
        transition_applied = False
        current_code = None
        if predicted_value is not None:
            current_code = str(
                int(round(float(predicted_value) * (10 ** max(red_digits, 0))))
            ).zfill(total_digits)[-total_digits:]
        if (
            len(transition_digits) == total_digits
            and transition_tail is not None
            and transition_tail.current_digit is not None
            and transition_tail.next_digit is not None
            and transition_confidence >= 0.88
        ):
            candidate_code = "".join(map(str, transition_digits))
            current_last = int(current_code[-1]) if current_code else None
            transition_pair = {int(transition_tail.current_digit), int(transition_tail.next_digit)}
            prefix_is_consistent = bool(current_code and current_code[:-1] == candidate_code[:-1])
            weak_current_window = predicted_value is None or not quality.usable
            if current_last not in transition_pair and (prefix_is_consistent or weak_current_window):
                for observation, digit in zip(observations, transition_digits):
                    observation.value = int(digit)
                observations[-1] = transition_tail
                predicted_value = int(candidate_code) / (10 ** max(red_digits, 0))
                alternatives = sorted({*(alternatives or []), predicted_value})[:8]
                flags = ["ocr_transition_geometry"] + flags
                transition_applied = True
                current_code = candidate_code
        if (
            not transition_applied
            and (
                predicted_value is None
                or (
                    fusion_mode is None
                    and not full_frame_applied
                    and not missing_tail_applied
                    and not meter_tail_applied
                    and (used_fallback_roi or used_ocr_window)
                )
            )
            and transition_tail is not None
            and transition_tail.current_digit is not None
            and transition_tail.next_digit is not None
            and transition_tail.confidence >= 0.56
            and len(meter_tail_digits) == total_digits
            and meter_tail_confidence >= 0.50
        ):
            recovered_digits = [*meter_tail_digits[:-1], int(transition_tail.current_digit)]
            for observation, digit in zip(observations, recovered_digits):
                observation.value = int(digit)
            observations[-1] = transition_tail
            predicted_value = int("".join(map(str, recovered_digits))) / (10 ** max(red_digits, 0))
            alternatives = [predicted_value]
            flags = ["ocr_transition_tail_recovery"] + flags
            transition_applied = True
        unit_tail_applied = False
        if (
            (
                predicted_value is None
                or (
                    fusion_mode is None
                    and not full_frame_applied
                    and not missing_tail_applied
                    and not meter_tail_applied
                    and used_ocr_window
                )
            )
            and display_source == "meter_unit_anchor"
            and unit_tail is not None
            and unit_tail.value is not None
            and unit_tail.confidence >= 0.85
            and len(ocr_digits) == total_digits - 1
            and ocr_confidence >= 0.58
        ):
            recovered_digits = [*ocr_digits, int(unit_tail.value)]
            for observation, digit in zip(observations, recovered_digits):
                observation.value = int(digit)
            observations[-1] = unit_tail
            predicted_value = int("".join(map(str, recovered_digits))) / (10 ** max(red_digits, 0))
            alternatives = [predicted_value]
            flags = ["meter_unit_tail_recovery"] + flags
            unit_tail_applied = True
        if (
            fusion_mode is None
            and not full_frame_applied
            and not missing_tail_applied
            and not meter_tail_applied
            and not transition_applied
            and not unit_tail_applied
            and (used_fallback_roi or used_ocr_window)
            and (
                used_fallback_roi
                or ocr_confidence < 0.72
                or (len(ocr_digits) != total_digits and ocr_confidence < 0.80)
            )
        ):
            predicted_value = None
            alternatives = []
            flags.append("insufficient_text_evidence")
        if (
            predicted_value is not None
            and slots
            and total_digits >= 2
            and not transition_applied
            and not unit_tail_applied
        ):
            total_scale = 10 ** max(red_digits, 0)
            predicted_code = str(int(round(float(predicted_value) * total_scale))).zfill(total_digits)[-total_digits:]
            last_index = total_digits - 1
            last_slot = slots[last_index]
            top_digit, top_confidence, _ = _classify(last_slot[: max(int(last_slot.shape[0] * 0.72), 1)])
            slot_digit = original_slot_values[last_index]
            slot_confidence = original_slot_confidences[last_index]
            current_last_digit = int(predicted_code[-1])
            corrected_last_digit = None
            if (
                slot_digit is not None
                and int(slot_digit) != current_last_digit
                and int(slot_digit) == top_digit
                and slot_confidence >= 0.94
                and top_confidence >= 0.94
                and ocr_confidence < 0.88
                and fusion_mode is None
            ):
                corrected_last_digit = int(slot_digit)
            elif (
                top_digit is not None
                and int(top_digit) != current_last_digit
                and top_confidence >= 0.94
                and slot_confidence < 0.90
                and ocr_confidence < 0.88
                and fusion_mode is None
            ):
                corrected_last_digit = int(top_digit)
            if corrected_last_digit is not None:
                corrected_code = predicted_code[:-1] + str(corrected_last_digit)
                predicted_value = int(corrected_code) / total_scale
                alternatives = sorted({*(alternatives or []), int(predicted_code) / total_scale, predicted_value})[:8]
                observations[last_index].value = corrected_last_digit
                observations[last_index].confidence = round(max(observations[last_index].confidence, top_confidence), 4)
                flags.append("roller_top_digit_correction")
        rejected_prediction = None
        anomaly = _prediction_anomaly(predicted_value, previous_value)
        if anomaly is not None:
            rejected_prediction = predicted_value
            predicted_value = None
            alternatives = []
            flags.append(anomaly)
            flags.append("unsafe_prediction_rejected")
        confidences = [item.confidence for item in observations if item.value is not None]
        confidence = float(math.prod(confidences) ** (1 / len(confidences))) if len(confidences) == total_digits else 0.0
        confidence *= max(0.0, 1 - quality.blur * 0.35 - quality.glare * 0.25 - perspective * 0.2)
        if used_fallback_roi:
            confidence *= 0.72
            flags.append("fallback_roi")
        if used_ocr_window:
            confidence *= 0.92
            flags.append("ocr_window")
        if not quality.usable:
            confidence *= 0.25
            flags.append("recapture_recommended")
        if predicted_value is None:
            confidence = 0.0
        confidence = round(_clamp(confidence), 4)
        raw_auto_fill = bool(
            predicted_value is not None
            and quality.usable
            and confidence >= settings.vision_min_autofill_confidence
            and "implausible_consumption_jump" not in flags
        )
        from app.services.vision_decision import (
            DECODER_VERSION,
            calibrate_confidence,
            load_calibration_profile,
        )

        profile = load_calibration_profile(hydrometer_brand, hydrometer_model)
        has_transition = any(item.transitional for item in observations)
        calibrated_confidence = calibrate_confidence(confidence, profile, transitional=has_transition)
        decision = "confirm"
        if "unsafe_prediction_rejected" in flags and quality.usable:
            decision = "confirm"
        elif predicted_value is None or not quality.usable:
            decision = "recapture"
        elif (
            raw_auto_fill
            and profile.calibrated
            and calibrated_confidence >= profile.minimum_autofill
            and (not has_transition or profile.allow_transition_autofill)
        ):
            decision = "accepted"
        if not profile.calibrated:
            flags.append("uncalibrated_confidence")
        auto_fill = decision == "accepted"
        ok, encoded = cv2.imencode(".jpg", rectified, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        quality_payload = asdict(quality)
        quality_payload["display_detection"] = {
            "source": display_source,
            "confidence": learned_detection.confidence if learned_detection is not None else None,
            "learned_slot_boundaries": learned_boundaries if len(learned_boundaries) == total_digits + 1 else None,
        }
        quality_payload["source_frame"] = asdict(frame_quality)
        quality_payload["sequence_ocr"] = {
            "digits": "".join(map(str, ocr_digits)) if ocr_digits else None,
            "confidence": ocr_confidence,
            "fusion": fusion_mode,
        }
        quality_payload["full_frame_ocr"] = {
            "digits": "".join(map(str, full_frame_digits)) if full_frame_digits else None,
            "confidence": full_frame_confidence,
            "fusion": full_frame_mode if full_frame_applied else None,
        }
        quality_payload["missing_tail_ocr"] = {
            "digits": "".join(map(str, missing_tail_digits)) if missing_tail_digits else None,
            "confidence": missing_tail_confidence,
            "fusion": missing_tail_mode if missing_tail_applied else None,
        }
        quality_payload["meter_tail_ocr"] = {
            "digits": "".join(map(str, meter_tail_digits)) if meter_tail_digits else None,
            "confidence": meter_tail_confidence,
            "fusion": meter_tail_mode if meter_tail_applied else None,
        }
        quality_payload["decision"] = {
            "status": decision,
            "raw_confidence": confidence,
            "calibrated_confidence": calibrated_confidence,
            "calibration_version": profile.version,
            "calibrated": profile.calibrated,
            "rejected_prediction": rejected_prediction,
        }
        quality_payload["model_ready"] = True
        predicted_code_result = None
        if predicted_value is not None:
            predicted_code_result = str(
                int(round(float(predicted_value) * (10 ** max(red_digits, 0))))
            ).zfill(total_digits)[-total_digits:]
        return VisionResult(
            predicted_code=predicted_code_result,
            predicted_value=predicted_value,
            confidence=confidence,
            auto_fill_allowed=auto_fill,
            red_digits=red_digits,
            black_digits=black_digits,
            model_version=settings.vision_model_version,
            quality=quality_payload,
            digits=[asdict(item) for item in observations],
            alternatives=alternatives,
            flags=list(dict.fromkeys(flags)),
            rectified_jpeg=encoded.tobytes() if ok else None,
            decision=decision,
            calibrated_confidence=calibrated_confidence,
            decoder_version=DECODER_VERSION,
        )


meter_vision_service = MeterVisionService()
