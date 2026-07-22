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


def has_textual_meter_evidence(result: VisionResult, total_digits: int) -> bool:
    """Distingue leitura do visor de um palpite produzido apenas pelos slots.

    O classificador posicional sempre devolve alguma classe, mesmo quando o ROI
    contém borda, texto da carcaça ou fundo. Para um burst virar sugestão é
    necessário que pelo menos um frame também reconheça a sequência mecânica
    ou uma das recuperações de cauda com seus próprios gates de confiança.
    """

    if result.predicted_code is None and result.predicted_value is None:
        return False

    trusted_flags = {
        "sequence_exact",
        "sequence_exact_slot_guard",
        "sequence_missing_transition",
        "sequence_removed_separator",
        "sequence_removed_separators",
        "full_frame_sequence_exact",
        "full_frame_sequence_normalized",
        "ocr_missing_tail_slot",
        "ocr_meter_tail_slot",
        "meter_unit_tail_recovery",
        "ocr_transition_geometry",
        "ocr_transition_tail_recovery",
    }
    if trusted_flags.intersection(result.flags or []):
        return True

    quality = result.quality or {}
    checks = (
        ("sequence_ocr", 0.56, {total_digits - 1, total_digits, total_digits + 1}),
        ("full_frame_ocr", 0.60, {total_digits}),
        ("missing_tail_ocr", 0.66, {total_digits}),
        ("meter_tail_ocr", 0.58, {total_digits}),
    )
    for key, minimum_confidence, allowed_lengths in checks:
        evidence = quality.get(key) or {}
        digits = "".join(character for character in str(evidence.get("digits") or "") if character.isdigit())
        if len(digits) in allowed_lengths and float(evidence.get("confidence") or 0.0) >= minimum_confidence:
            return True
    return False


def _history_rejection_reason(code: str, *, red_digits: int, previous_value: float | None) -> str | None:
    """Reaplica o limite operacional depois da fusão temporal."""

    if previous_value is None:
        return None
    value = int(code) / (10 ** max(red_digits, 0))
    delta = value - float(previous_value)
    if delta >= 0:
        if delta > max(100.0, abs(float(previous_value)) * 0.5):
            return "implausible_consumption_jump"
        return None

    rollover_limit = 10 ** max(len(code) - max(red_digits, 0), 1)
    rollover_allowed = previous_value >= rollover_limit * 0.90 and value <= rollover_limit * 0.10
    return None if rollover_allowed else "below_previous_reading"


def _reject_burst_candidate(
    results: list[VisionResult],
    *,
    selected_index: int,
    reason: str,
    rejected_code: str | None,
    frame_codes: list[str],
    text_evidence_frames: int,
    text_evidence_codes: list[str] | None = None,
) -> tuple[int, VisionResult]:
    selected = copy.deepcopy(results[selected_index])
    selected.predicted_code = None
    selected.predicted_value = None
    selected.alternatives = []
    selected.confidence = 0.0
    selected.calibrated_confidence = 0.0
    selected.auto_fill_allowed = False
    selected.decision = "confirm" if selected.quality.get("usable", True) else "recapture"
    selected.flags = list(dict.fromkeys([
        "burst_candidate_rejected",
        reason,
        *selected.flags,
    ]))
    selected.quality = {
        **selected.quality,
        "temporal_fusion": {
            "decoder_version": DECODER_VERSION,
            "status": "rejected",
            "reason": reason,
            "rejected_candidate": rejected_code,
            "frame_codes": frame_codes,
            "frames_used": len(results),
            "text_evidence_frames": text_evidence_frames,
            "text_evidence_codes": text_evidence_codes or [],
        },
    }
    return selected_index, selected


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
    eligible = [result for result in results if len(result.digits or []) == total_digits]
    if len(eligible) < 2:
        selected = copy.deepcopy(results[selected_index])
        selected.decision = "recapture" if not selected.quality.get("usable", True) else "confirm"
        return selected_index, selected

    per_frame_codes = [
        code
        for result in eligible
        if (code := _result_code(result, total_digits=total_digits, red_digits=red_digits)) is not None
    ]
    text_evidence_codes = [
        code
        for result in eligible
        if has_textual_meter_evidence(result, total_digits)
        if (code := _result_code(result, total_digits=total_digits, red_digits=red_digits)) is not None
    ]
    text_evidence_frames = len(text_evidence_codes)
    text_code_groups: dict[str, list[str]] = {}
    for code in text_evidence_codes:
        text_code_groups.setdefault(code, []).append(code)
    dominant_text_codes = max(text_code_groups.values(), key=len, default=[])
    hybrid_text_slot_consensus = False
    if len(dominant_text_codes) < 2:
        single_text_code = dominant_text_codes[0] if dominant_text_codes else None
        matching_frame_count = (
            sum(code == single_text_code for code in per_frame_codes)
            if single_text_code is not None
            else 0
        )
        # Em movimento é comum somente um quadro passar pela cabeça textual,
        # enquanto o classificador por rolete repete o mesmo código em outros
        # quadros. Um texto válido + confirmação visual independente é evidência
        # temporal; um texto isolado continua sendo rejeitado.
        hybrid_text_slot_consensus = bool(single_text_code and matching_frame_count >= 2)
    if len(dominant_text_codes) < 2 and not hybrid_text_slot_consensus:
        # O valor é apenas uma sugestão para o dashboard. Quando um único
        # quadro realmente leu a sequência pelo OCR textual, preservamos essa
        # leitura com baixa evidência temporal em vez de apagar o resultado e
        # exibir "Falha no OCR". Ela jamais recebe auto-fill e continua sujeita
        # às travas de histórico; resultados produzidos somente pelos slots
        # permanecem rejeitados.
        if text_evidence_frames == 1:
            single_match = next((
                (index, result, code)
                for index, result in enumerate(results)
                if has_textual_meter_evidence(result, total_digits)
                if (code := _result_code(
                    result,
                    total_digits=total_digits,
                    red_digits=red_digits,
                )) is not None
            ), None)
            if single_match is not None:
                text_index, text_result, text_code = single_match
                history_rejection = _history_rejection_reason(
                    text_code,
                    red_digits=red_digits,
                    previous_value=previous_value,
                )
                if history_rejection is None:
                    suggestion = copy.deepcopy(text_result)
                    suggestion.predicted_code = text_code
                    suggestion.predicted_value = int(text_code) / (10 ** max(red_digits, 0))
                    suggestion.decision = "confirm"
                    suggestion.auto_fill_allowed = False
                    suggestion.flags = list(dict.fromkeys([
                        "burst_single_text_suggestion",
                        "burst_low_temporal_consensus",
                        *suggestion.flags,
                    ]))
                    suggestion.quality = {
                        **(suggestion.quality or {}),
                        "temporal_fusion": {
                            "decoder_version": DECODER_VERSION,
                            "frames_used": len(eligible),
                            "text_evidence_frames": 1,
                            "text_evidence_codes": [text_code],
                            "text_anchor_code": text_code,
                            "consensus_valid": False,
                            "suggestion_valid": True,
                            "calibrated": False,
                        },
                    }
                    return text_index, suggestion
        anchored_candidates = []
        for index, result in enumerate(results):
            quality = result.quality or {}
            detection = quality.get("display_detection") or {}
            source = detection.get("source")
            code = _result_code(result, total_digits=total_digits, red_digits=red_digits)
            if (
                code is not None
                and source in {"detector_onnx", "red_roller_anchor", "meter_unit_anchor", "ocr_window"}
                and quality.get("usable", True)
                and float(result.confidence or 0.0) >= 0.40
            ):
                anchored_candidates.append((index, result, code))
        anchored_groups: dict[str, list[tuple[int, VisionResult, str]]] = {}
        for candidate in anchored_candidates:
            anchored_groups.setdefault(candidate[2], []).append(candidate)
        anchored_group = max(anchored_groups.values(), key=len, default=[])
        if text_evidence_frames == 0 and len(anchored_group) >= 2:
            anchor_index, anchor_result, anchor_code = max(
                anchored_group,
                key=lambda candidate: candidate[1].confidence,
            )
            history_rejection = _history_rejection_reason(
                anchor_code,
                red_digits=red_digits,
                previous_value=previous_value,
            )
            if history_rejection is None:
                suggestion = copy.deepcopy(anchor_result)
                suggestion.predicted_code = anchor_code
                suggestion.predicted_value = int(anchor_code) / (10 ** max(red_digits, 0))
                suggestion.decision = "confirm"
                suggestion.auto_fill_allowed = False
                suggestion.flags = list(dict.fromkeys([
                    "burst_anchored_slot_suggestion",
                    "burst_low_temporal_consensus",
                    *suggestion.flags,
                ]))
                suggestion.quality = {
                    **(suggestion.quality or {}),
                    "temporal_fusion": {
                        "decoder_version": DECODER_VERSION,
                        "frames_used": len(eligible),
                        "text_evidence_frames": text_evidence_frames,
                        "text_evidence_codes": text_evidence_codes,
                        "text_anchor_code": None,
                        "anchored_slot_frames": len(anchored_group),
                        "anchored_slot_code": anchor_code,
                        "consensus_valid": False,
                        "suggestion_valid": True,
                        "calibrated": False,
                    },
                }
                return anchor_index, suggestion
        return _reject_burst_candidate(
            results,
            selected_index=selected_index,
            reason=(
                "burst_text_evidence_disagreement"
                if text_evidence_frames >= 2
                else "burst_insufficient_text_evidence"
            ),
            rejected_code=_result_code(
                results[selected_index],
                total_digits=total_digits,
                red_digits=red_digits,
            ),
            frame_codes=per_frame_codes,
            text_evidence_frames=text_evidence_frames,
            text_evidence_codes=text_evidence_codes,
        )
    # O prefixo igual não basta: o último rolete é justamente a posição mais
    # sujeita a transição. Escolher a mediana entre `...4` e `...0` fabricava
    # uma certeza inexistente. A sugestão só nasce quando dois OCRs
    # independentes repetem o código completo.
    text_anchor_code = dominant_text_codes[0]

    log_scores = [[0.0] * 10 for _ in range(total_digits)]
    weights = [0.0] * total_digits
    for result in eligible:
        frame_weight = _quality_weight(result)
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

    # A distribuição dos slots ajuda a desempatar, mas não pode trocar o
    # prefixo que foi efetivamente lido em dois ou mais frames independentes.
    # Isso bloqueia consensos falsos como 0000047 produzidos por ROIs errados.
    selected_code = text_anchor_code

    history_rejection = _history_rejection_reason(
        selected_code,
        red_digits=red_digits,
        previous_value=previous_value,
    )
    if history_rejection is not None:
        return _reject_burst_candidate(
            results,
            selected_index=selected_index,
            reason=history_rejection,
            rejected_code=selected_code,
            frame_codes=per_frame_codes,
            text_evidence_frames=text_evidence_frames,
            text_evidence_codes=text_evidence_codes,
        )

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
    if (
        profile.calibrated
        and calibrated >= max(profile.minimum_autofill, get_settings().vision_min_autofill_confidence)
        and (not transitional or profile.allow_transition_autofill)
    ):
        fused.decision = "accepted"
    fused.auto_fill_allowed = fused.decision == "accepted"
    fused.flags = list(dict.fromkeys([
        "burst_slot_fusion",
        *(["burst_hybrid_text_slot_consensus"] if hybrid_text_slot_consensus else []),
        *(["burst_consensus_median"] if robust_consensus_code == selected_code else []),
        *(["transitional_digit"] if transitional else []),
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
            "text_evidence_frames": text_evidence_frames,
            "text_evidence_codes": text_evidence_codes,
            "text_anchor_code": text_anchor_code,
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
            "consensus_valid": True,
        },
    }
    return best_result_index, fused
