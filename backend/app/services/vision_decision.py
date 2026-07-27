"""Decisao temporal e mecanica para leituras de hidrômetros.

Esta camada não reconhece pixels. Ela combina observações independentes dos
frames, preserva incerteza por posição e só então produz um código completo.
O objetivo é impedir que um OCR ou um único frame decida sozinho um rolete em
transição.
"""

from __future__ import annotations

import copy
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config import get_settings

if TYPE_CHECKING:
    from app.services.meter_vision import VisionResult


DECODER_VERSION = "mechanical-temporal-v2"
_EPSILON = 1e-6


@dataclass(frozen=True)
class CalibrationProfile:
    version: str
    points: tuple[tuple[float, float], ...]
    transition_points: tuple[tuple[float, float], ...]
    transition_threshold: float
    minimum_autofill: float
    allow_transition_autofill: bool

    @property
    def calibrated(self) -> bool:
        return bool(self.points)


def _profile_from_payload(payload: dict[str, Any] | None, *, version: str) -> CalibrationProfile:
    payload = payload or {}

    def points(name: str) -> tuple[tuple[float, float], ...]:
        parsed = []
        for item in payload.get(name) or []:
            if not isinstance(item, (list, tuple)) or len(item) != 2:
                continue
            parsed.append((float(item[0]), float(item[1])))
        return tuple(sorted(parsed))

    return CalibrationProfile(
        version=version,
        points=points("points"),
        transition_points=points("transition_points"),
        transition_threshold=float(payload.get("transition_threshold", 0.5)),
        minimum_autofill=float(payload.get("minimum_autofill", 0.995)),
        allow_transition_autofill=bool(payload.get("allow_transition_autofill", False)),
    )


@lru_cache(maxsize=8)
def load_calibration_profile(brand: str | None = None, model: str | None = None) -> CalibrationProfile:
    settings = get_settings()
    path = Path(settings.vision_calibration_path) if settings.vision_calibration_path else None
    if path is None or not path.exists():
        return _profile_from_payload(None, version="uncalibrated")

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return _profile_from_payload(None, version="invalid-calibration")
    if payload.get("status") != "promoted":
        return _profile_from_payload(None, version=str(payload.get("version") or "unpromoted-calibration"))

    profiles = payload.get("profiles") or {}
    normalized_brand = (brand or "").strip().lower()
    normalized_model = (model or "").strip().lower()
    keys = [
        f"{normalized_brand}/{normalized_model}" if normalized_brand and normalized_model else "",
        normalized_brand,
        "default",
    ]
    selected = next((profiles[key] for key in keys if key and key in profiles), payload.get("default"))
    return _profile_from_payload(selected, version=str(payload.get("version") or path.stem))


def _interpolate(points: tuple[tuple[float, float], ...], value: float) -> float:
    value = max(0.0, min(1.0, float(value)))
    if not points:
        return value
    if value <= points[0][0]:
        return max(0.0, min(1.0, points[0][1]))
    if value >= points[-1][0]:
        return max(0.0, min(1.0, points[-1][1]))
    for left, right in zip(points, points[1:]):
        if left[0] <= value <= right[0]:
            span = max(right[0] - left[0], _EPSILON)
            ratio = (value - left[0]) / span
            return max(0.0, min(1.0, left[1] + (right[1] - left[1]) * ratio))
    return value


def calibrate_confidence(raw: float, profile: CalibrationProfile, *, transitional: bool) -> float:
    points = profile.transition_points if transitional and profile.transition_points else profile.points
    calibrated = _interpolate(points, raw)
    if not profile.calibrated:
        # Sem conjunto de validação não existe probabilidade calibrada. Manter o
        # número útil para diagnóstico, mas conservador para decisão automática.
        calibrated *= 0.90 if transitional else 0.95
    return round(max(0.0, min(1.0, calibrated)), 4)


def _quality_weight(result: VisionResult) -> float:
    quality = result.quality or {}
    if not quality.get("usable", True):
        return 0.12
    blur = float(quality.get("blur", 0.5))
    glare = float(quality.get("glare", 0.0))
    perspective = float(quality.get("perspective", 0.0))
    evidence = 1.0 - blur * 0.38 - glare * 0.28 - perspective * 0.20
    return max(0.10, min(1.0, evidence))


def _result_code(result: VisionResult, *, total_digits: int, red_digits: int) -> str | None:
    if result.predicted_code:
        return str(result.predicted_code).zfill(total_digits)[-total_digits:]
    if result.predicted_value is None:
        return None
    raw = int(round(float(result.predicted_value) * (10 ** max(red_digits, 0))))
    return str(raw).zfill(total_digits)[-total_digits:]


def _is_fusion_eligible(result: VisionResult, *, total_digits: int) -> bool:
    """Aceita apenas quadros que realmente localizaram e leram o visor."""

    if len(result.digits or []) != total_digits:
        return False
    if result.predicted_code is None and result.predicted_value is None:
        return False
    if {
        "insufficient_text_evidence",
        "unsafe_prediction_rejected",
    }.intersection(result.flags or []):
        return False
    display_detection = (result.quality or {}).get("display_detection") or {}
    if display_detection and not display_detection.get("localization_valid", False):
        return False
    return True


def _normalize_distribution(values: list[float]) -> list[float]:
    safe = [max(float(value), 0.0) for value in values[:10]]
    safe.extend([0.0] * (10 - len(safe)))
    total = sum(safe)
    if total <= _EPSILON:
        return [0.1] * 10
    return [value / total for value in safe]


def _observation_distribution(observation: dict[str, Any]) -> list[float]:
    raw = observation.get("probabilities") or []
    if len(raw) >= 10 and sum(max(float(value), 0.0) for value in raw[:10]) > _EPSILON:
        distribution = _normalize_distribution(list(raw))
    else:
        distribution = [0.02 / 9] * 10
        value = observation.get("value")
        if value is not None:
            confidence = max(0.10, min(0.98, float(observation.get("confidence") or 0.0)))
            distribution = [(1.0 - confidence) / 9] * 10
            distribution[int(value) % 10] = confidence

    if observation.get("transitional"):
        current = observation.get("current_digit", observation.get("upper_digit"))
        next_digit = observation.get("next_digit", observation.get("lower_digit"))
        phase = float(observation.get("transition_phase") or 0.5)
        transition_confidence = float(observation.get("transition_confidence") or observation.get("confidence") or 0.0)
        if current is not None and next_digit is not None and (int(current) + 1) % 10 == int(next_digit):
            # A fase modifica a distribuição, sem apagar a evidência produzida
            # pelo classificador do slot completo e da linha central.
            current_share = max(0.05, 1.0 - phase)
            next_share = max(0.05, phase)
            strength = min(0.82, max(0.20, transition_confidence))
            distribution[int(current)] += strength * current_share
            distribution[int(next_digit)] += strength * next_share
    value = observation.get("value")
    if value is not None:
        # O valor do slot pode ter sido corrigido por uma cabeça sequencial ou
        # pelo detector de cauda após a classificação visual original.
        distribution[int(value) % 10] += max(0.20, float(observation.get("confidence") or 0.0)) * 1.25
    return _normalize_distribution(distribution)


def _transition_map(results: list[VisionResult], total_digits: int) -> dict[int, tuple[int, int, float]]:
    evidence: dict[tuple[int, int, int], list[tuple[float, float]]] = {}
    for result in results:
        weight = _quality_weight(result)
        for position, observation in enumerate((result.digits or [])[:total_digits]):
            if not observation.get("transitional"):
                continue
            current = observation.get("current_digit", observation.get("upper_digit"))
            next_digit = observation.get("next_digit", observation.get("lower_digit"))
            if current is None or next_digit is None or (int(current) + 1) % 10 != int(next_digit):
                continue
            phase = float(observation.get("transition_phase") or 0.5)
            confidence = float(observation.get("transition_confidence") or observation.get("confidence") or 0.0)
            evidence.setdefault((position, int(current), int(next_digit)), []).append((phase, weight * confidence))

    selected: dict[int, tuple[int, int, float]] = {}
    grouped: dict[int, list[tuple[float, int, int, float]]] = {}
    for (position, current, next_digit), values in evidence.items():
        strength = sum(weight for _, weight in values)
        phase = sum(value * weight for value, weight in values) / max(strength, _EPSILON)
        grouped.setdefault(position, []).append((strength, current, next_digit, phase))
    for position, candidates in grouped.items():
        strength, current, next_digit, phase = max(candidates)
        if strength >= 0.25:
            selected[position] = (current, next_digit, max(0.0, min(1.0, phase)))
    return selected


def _mechanical_bonus(code: str, transitions: dict[int, tuple[int, int, float]]) -> float:
    bonus = 0.0
    for position, (current, next_digit, phase) in transitions.items():
        if position >= len(code):
            continue
        chosen = int(code[position])
        if chosen not in (current, next_digit):
            bonus -= 2.0
            continue
        expected = next_digit if phase >= 0.5 else current
        bonus += 0.35 if chosen == expected else -0.18

        # Quando uma casa à esquerda começa a subir, a casa imediatamente à
        # direita deve estar em 9→0 ou já ter cruzado para zero. É um reforço,
        # não uma substituição da imagem.
        if position + 1 < len(code) and chosen == next_digit:
            right = int(code[position + 1])
            right_transition = transitions.get(position + 1)
            carry_supported = right == 0 or (
                right_transition is not None
                and right_transition[0] == 9
                and right_transition[1] == 0
                and right_transition[2] >= 0.45
            )
            bonus += 0.22 if carry_supported else -0.30
    return bonus


def _history_bonus(code: str, *, red_digits: int, previous_value: float | None) -> float:
    if previous_value is None:
        return 0.0
    value = int(code) / (10 ** max(red_digits, 0))
    delta = value - float(previous_value)
    if delta >= 0:
        return 0.18 - min(delta / max(abs(previous_value), 1.0), 2.0) * 0.08
    rollover_limit = 10 ** max(len(code) - max(red_digits, 0), 1)
    if previous_value >= rollover_limit * 0.90 and value <= rollover_limit * 0.10:
        return 0.08
    return -0.45


def fuse_burst_results(
    results: list[VisionResult],
    *,
    selected_index: int,
    red_digits: int,
    black_digits: int,
    previous_value: float | None = None,
    hydrometer_brand: str | None = None,
    hydrometer_model: str | None = None,
) -> tuple[int, VisionResult]:
    """Funde evidência por slot e executa o decodificador mecânico."""

    if not results:
        raise ValueError("Burst sem resultados")
    selected_index = max(0, min(selected_index, len(results) - 1))
    total_digits = max(3, min(int(black_digits) + int(red_digits), 10))
    eligible_pairs = [
        (index, result)
        for index, result in enumerate(results)
        if _is_fusion_eligible(result, total_digits=total_digits)
    ]
    eligible = [result for _, result in eligible_pairs]
    if len(eligible) < 2:
        if eligible_pairs:
            eligible_index, eligible_result = max(
                eligible_pairs,
                key=lambda item: (_quality_weight(item[1]), item[1].confidence),
            )
            selected = copy.deepcopy(eligible_result)
            selected.decision = "confirm" if selected.quality.get("usable", True) else "recapture"
            selected.auto_fill_allowed = False
            return eligible_index, selected

        selected = copy.deepcopy(results[selected_index])
        selected.predicted_code = None
        selected.predicted_value = None
        selected.alternatives = []
        selected.confidence = 0.0
        selected.calibrated_confidence = 0.0
        selected.decision = "recapture"
        selected.auto_fill_allowed = False
        selected.flags = list(dict.fromkeys([
            *selected.flags,
            "burst_without_valid_display_evidence",
        ]))
        selected.quality = {
            **(selected.quality or {}),
            "recapture_reason": (
                (selected.quality or {}).get("recapture_reason")
                or "O visor não foi localizado com segurança. Refaca a foto."
            ),
        }
        return selected_index, selected

    log_scores = [[0.0] * 10 for _ in range(total_digits)]
    weights = [0.0] * total_digits
    per_frame_codes: list[str] = []
    for result in eligible:
        frame_weight = _quality_weight(result)
        result_code = _result_code(result, total_digits=total_digits, red_digits=red_digits)
        if result_code:
            per_frame_codes.append(result_code)
        for position, observation in enumerate(result.digits[:total_digits]):
            observation_weight = frame_weight * max(0.15, float(observation.get("visibility") or 1.0))
            distribution = _observation_distribution(observation)
            for digit, probability in enumerate(distribution):
                log_scores[position][digit] += observation_weight * math.log(max(probability, _EPSILON))
            weights[position] += observation_weight

    probabilities: list[list[float]] = []
    for position in range(total_digits):
        normalized_logits = [score / max(weights[position], _EPSILON) for score in log_scores[position]]
        maximum = max(normalized_logits)
        exp_values = [math.exp(value - maximum) for value in normalized_logits]
        probabilities.append([value / max(sum(exp_values), _EPSILON) for value in exp_values])

    transitions = _transition_map(eligible, total_digits)
    beam: list[tuple[str, float]] = [("", 0.0)]
    for position, distribution in enumerate(probabilities):
        options = sorted(range(10), key=lambda digit: distribution[digit], reverse=True)[:2]
        if position in transitions:
            current, next_digit, _ = transitions[position]
            options = list(dict.fromkeys([*options, current, next_digit]))
        beam = sorted(
            (
                (prefix + str(digit), score + math.log(max(distribution[digit], _EPSILON)))
                for prefix, score in beam
                for digit in options
            ),
            key=lambda item: item[1],
            reverse=True,
        )[:64]

    candidates: dict[str, float] = {code: score for code, score in beam}
    for code in per_frame_codes:
        visual_score = sum(math.log(max(probabilities[index][int(digit)], _EPSILON)) for index, digit in enumerate(code))
        candidates[code] = max(candidates.get(code, -math.inf), visual_score)

    robust_consensus_code = None
    robust_group_size = 0
    prefix_groups: dict[str, list[str]] = {}
    for code in per_frame_codes:
        prefix_groups.setdefault(code[:-1], []).append(code)
    if prefix_groups:
        _, dominant_codes = max(prefix_groups.items(), key=lambda item: len(item[1]))
        if len(dominant_codes) >= 3:
            robust_group_size = len(dominant_codes)
            robust_consensus_code = sorted(dominant_codes)[len(dominant_codes) // 2]
            visual_score = sum(
                math.log(max(probabilities[index][int(digit)], _EPSILON))
                for index, digit in enumerate(robust_consensus_code)
            )
            candidates[robust_consensus_code] = max(candidates.get(robust_consensus_code, -math.inf), visual_score)

    def consensus_bonus(code: str) -> float:
        return 0.72 if robust_consensus_code is not None and code == robust_consensus_code else 0.0

    ranked = sorted(
        candidates.items(),
        key=lambda item: (
            item[1]
            + _mechanical_bonus(item[0], transitions)
            + _history_bonus(item[0], red_digits=red_digits, previous_value=previous_value)
            + consensus_bonus(item[0])
        ),
        reverse=True,
    )
    selected_code, _ = ranked[0]
    if robust_consensus_code is not None and robust_group_size >= 3:
        # Caso mecânico clássico: prefixo estável e somente o rolete final
        # oscila entre frames. A mediana ordinal é mais resistente a um frame
        # excessivamente confiante do que uma votação ponderada isolada.
        selected_code = robust_consensus_code

    best_result_index, best_result = max(
        enumerate(results),
        key=lambda item: (
            _result_code(item[1], total_digits=total_digits, red_digits=red_digits) == selected_code,
            _quality_weight(item[1]),
            item[1].confidence,
        ),
    )
    fused = copy.deepcopy(best_result)
    fused.predicted_code = selected_code
    fused.predicted_value = int(selected_code) / (10 ** max(red_digits, 0))
    fused.alternatives = [
        int(code) / (10 ** max(red_digits, 0))
        for code, _ in ranked[:8]
    ]

    position_confidences = [probabilities[index][int(digit)] for index, digit in enumerate(selected_code)]
    raw_confidence = math.prod(max(value, _EPSILON) for value in position_confidences) ** (1 / total_digits)
    agreement = sum(code == selected_code for code in per_frame_codes) / max(len(per_frame_codes), 1)
    raw_confidence *= 0.72 + 0.28 * agreement
    transitional = bool(transitions)
    profile = load_calibration_profile(hydrometer_brand, hydrometer_model)
    calibrated = calibrate_confidence(raw_confidence, profile, transitional=transitional)

    fused.confidence = round(max(0.0, min(1.0, raw_confidence)), 4)
    fused.calibrated_confidence = calibrated
    fused.decoder_version = DECODER_VERSION
    fused.decision = "confirm"
    if not any(result.quality.get("usable", True) for result in eligible):
        fused.decision = "recapture"
    elif (
        profile.calibrated
        and calibrated >= max(profile.minimum_autofill, get_settings().vision_min_autofill_confidence)
        and (not transitional or profile.allow_transition_autofill)
    ):
        fused.decision = "accepted"
    fused.auto_fill_allowed = fused.decision == "accepted"
    fused.flags = list(dict.fromkeys([
        "burst_slot_fusion",
        *( ["burst_consensus_median"] if robust_consensus_code == selected_code else []),
        *( ["transitional_digit"] if transitional else []),
        *fused.flags,
    ]))

    for position, digit in enumerate(selected_code):
        if position >= len(fused.digits):
            break
        fused.digits[position]["value"] = int(digit)
        fused.digits[position]["probabilities"] = [round(value, 6) for value in probabilities[position]]
        fused.digits[position]["confidence"] = round(position_confidences[position], 4)
        if position in transitions:
            current, next_digit, phase = transitions[position]
            fused.digits[position].update({
                "current_digit": current,
                "next_digit": next_digit,
                "transition_phase": round(phase, 4),
                "transitional": True,
            })

    fused.quality = {
        **fused.quality,
        **({
            "burst_consensus": {
                "prefix": selected_code[:-1],
                "votes": per_frame_codes,
                "selected": selected_code,
            }
        } if robust_consensus_code == selected_code else {}),
        "temporal_fusion": {
            "decoder_version": DECODER_VERSION,
            "frames_used": len(eligible),
            "selected": selected_code,
            "frame_codes": per_frame_codes,
            "transitions": {
                str(position): {"current": current, "next": next_digit, "phase": round(phase, 4)}
                for position, (current, next_digit, phase) in transitions.items()
            },
            "raw_confidence": round(raw_confidence, 4),
            "calibrated_confidence": calibrated,
            "calibration_version": profile.version,
            "calibrated": profile.calibrated,
        },
    }
    return best_result_index, fused
