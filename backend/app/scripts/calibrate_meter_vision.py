"""Gera calibração monotônica a partir de um benchmark rotulado independente."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def _bins(cases: list[dict], minimum_bin_size: int) -> list[list[dict]]:
    ordered = sorted(cases, key=lambda item: float(item.get("confidence") or 0.0))
    return [ordered[index:index + minimum_bin_size] for index in range(0, len(ordered), minimum_bin_size)]


def _pava(points: list[tuple[float, float, int]]) -> list[tuple[float, float]]:
    blocks = [[x, y * weight, weight] for x, y, weight in points]
    index = 0
    while index < len(blocks) - 1:
        left_rate = blocks[index][1] / blocks[index][2]
        right_rate = blocks[index + 1][1] / blocks[index + 1][2]
        if left_rate <= right_rate:
            index += 1
            continue
        left = blocks[index]
        right = blocks.pop(index + 1)
        blocks[index] = [max(left[0], right[0]), left[1] + right[1], left[2] + right[2]]
        index = max(index - 1, 0)
    return [(round(block[0], 6), round(block[1] / block[2], 6)) for block in blocks]


def _calibration_points(cases: list[dict], minimum_bin_size: int) -> list[list[float]]:
    raw = []
    for group in _bins(cases, minimum_bin_size):
        if not group:
            continue
        raw.append((
            max(float(item.get("confidence") or 0.0) for item in group),
            sum(1 for item in group if item.get("exact")) / len(group),
            len(group),
        ))
    return [[x, y] for x, y in _pava(raw)]


def build_profile(
    report: dict,
    *,
    minimum_cases: int,
    minimum_transition_cases: int,
    minimum_bin_size: int,
    target_precision: float,
    allow_small_diagnostic: bool,
) -> dict:
    cases = list(report.get("cases") or [])
    transition_cases = [item for item in cases if "transition" in (item.get("tags") or [])]
    enough = len(cases) >= minimum_cases and len(transition_cases) >= minimum_transition_cases
    if not enough and not allow_small_diagnostic:
        raise RuntimeError(
            f"Dataset insuficiente para calibrar: {len(cases)}/{minimum_cases} casos e "
            f"{len(transition_cases)}/{minimum_transition_cases} transições"
        )

    points = _calibration_points(cases, minimum_bin_size)
    transition_points = _calibration_points(transition_cases, max(5, minimum_bin_size // 2))
    eligible_thresholds = [raw for raw, calibrated in points if calibrated >= target_precision]
    minimum_autofill = min(eligible_thresholds) if eligible_thresholds and enough else 1.0
    return {
        "version": f"meter-calibration-{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}",
        "status": "promoted" if enough else "diagnostic",
        "source_count": len(cases),
        "transition_count": len(transition_cases),
        "default": {
            "points": points,
            "transition_points": transition_points,
            "transition_threshold": 0.5,
            "minimum_autofill": round(minimum_autofill, 6),
            "allow_transition_autofill": bool(
                enough
                and report.get("transition_exact_accuracy", 0.0) >= 0.97
                and report.get("silent_errors", 1) == 0
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--minimum-cases", type=int, default=500)
    parser.add_argument("--minimum-transition-cases", type=int, default=100)
    parser.add_argument("--minimum-bin-size", type=int, default=30)
    parser.add_argument("--target-precision", type=float, default=0.998)
    parser.add_argument("--allow-small-diagnostic", action="store_true")
    args = parser.parse_args()
    report = json.loads(args.benchmark.read_text(encoding="utf-8"))
    profile = build_profile(
        report,
        minimum_cases=args.minimum_cases,
        minimum_transition_cases=args.minimum_transition_cases,
        minimum_bin_size=args.minimum_bin_size,
        target_precision=args.target_precision,
        allow_small_diagnostic=args.allow_small_diagnostic,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(profile, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
