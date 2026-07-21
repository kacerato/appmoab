"""Benchmark local do motor visual de hidrometros.

Exemplo:
  python -m app.scripts.benchmark_meter_vision --case-file cases.json

Formato do arquivo:
{
  "red_digits": 3,
  "black_digits": 4,
  "cases": [
    {"id": "img1", "path": "C:/foto.jpg", "expected": "0090645"}
  ],
  "bursts": [
    {"id": "burst-office", "case_ids": ["img1", "img2"], "expected": "0090645"}
  ]
}
"""

from __future__ import annotations

import argparse
import base64
import json
import statistics
import time
from pathlib import Path
from typing import Any

from app.routers.hydrometers import _apply_burst_consensus
from app.services.meter_vision import VisionResult, meter_vision_service


def _read_image_base64(path: str) -> str:
    return base64.b64encode(Path(path).read_bytes()).decode()


def _digit_accuracy(predicted: str | None, expected: str) -> float:
    if not predicted:
        return 0.0
    width = max(len(predicted), len(expected))
    left = predicted.zfill(width)
    right = expected.zfill(width)
    return sum(a == b for a, b in zip(left, right)) / width


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return ordered[index]


def _case_result(result: VisionResult, expected: str, latency_ms: float) -> dict[str, Any]:
    exact = result.predicted_code == expected
    return {
        "predicted": result.predicted_code,
        "expected": expected,
        "exact": exact,
        "digit_accuracy": round(_digit_accuracy(result.predicted_code, expected), 6),
        "confidence": round(result.confidence, 6),
        "calibrated_confidence": result.calibrated_confidence,
        "auto_fill_allowed": result.auto_fill_allowed,
        "decision": result.decision,
        "latency_ms": round(latency_ms, 3),
        "flags": result.flags,
    }


def run_benchmark(case_file: Path, expensive_ocr: bool = True) -> dict[str, Any]:
    config = json.loads(case_file.read_text(encoding="utf-8"))
    red_digits = int(config.get("red_digits", 3))
    black_digits = int(config.get("black_digits", 4))

    raw_cases = config.get("cases") or []
    results_by_id: dict[str, VisionResult] = {}
    per_case: list[dict[str, Any]] = []
    latencies: list[float] = []

    for item in raw_cases:
        started = time.perf_counter()
        result = meter_vision_service.analyze(
            _read_image_base64(item["path"]),
            red_digits=red_digits,
            black_digits=black_digits,
            expensive_ocr=expensive_ocr,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        latencies.append(latency_ms)
        results_by_id[item["id"]] = result
        per_case.append({
            "id": item["id"],
            "path": item["path"],
            "tags": list(item.get("tags") or []),
            **_case_result(result, str(item["expected"]), latency_ms),
        })

    burst_results: list[dict[str, Any]] = []
    for burst in config.get("bursts") or []:
        burst_case_ids = list(burst.get("case_ids") or [])
        burst_items = [results_by_id[case_id] for case_id in burst_case_ids if case_id in results_by_id]
        if not burst_items:
            continue
        selected_index, selected = _apply_burst_consensus(
            burst_items,
            selected_index=0,
            red_digits=red_digits,
            black_digits=black_digits,
        )
        burst_results.append({
            "id": burst["id"],
            "case_ids": burst_case_ids,
            "selected_index": selected_index,
            **_case_result(selected, str(burst["expected"]), 0.0),
            "quality": selected.quality.get("burst_consensus"),
        })

    exact_hits = sum(1 for item in per_case if item["exact"])
    digit_scores = [float(item["digit_accuracy"]) for item in per_case]
    silent_errors = sum(
        1
        for item in per_case
        if not item["exact"] and item["predicted"] and item["auto_fill_allowed"]
    )
    transition_cases = [item for item in per_case if "transition" in item.get("tags", [])]
    auto_fill_cases = [item for item in per_case if item["auto_fill_allowed"]]
    scenario_metrics = {}
    for tag in sorted({tag for item in per_case for tag in item.get("tags", [])}):
        tagged = [item for item in per_case if tag in item.get("tags", [])]
        scenario_metrics[tag] = {
            "count": len(tagged),
            "exact_accuracy": round(sum(1 for item in tagged if item["exact"]) / len(tagged), 6),
            "digit_accuracy": round(statistics.mean(float(item["digit_accuracy"]) for item in tagged), 6),
        }
    burst_exact_accuracy = (
        sum(1 for item in burst_results if item["exact"]) / len(burst_results)
        if burst_results else 0.0
    )

    return {
        "red_digits": red_digits,
        "black_digits": black_digits,
        "count": len(per_case),
        "exact_accuracy": round(exact_hits / len(per_case), 6) if per_case else 0.0,
        "digit_accuracy": round(statistics.mean(digit_scores), 6) if digit_scores else 0.0,
        "avg_ms": round(statistics.mean(latencies), 3) if latencies else 0.0,
        "p95_ms": round(_p95(latencies), 3),
        "silent_errors": silent_errors,
        "auto_fill_precision": round(
            sum(1 for item in auto_fill_cases if item["exact"]) / len(auto_fill_cases), 6
        ) if auto_fill_cases else None,
        "transition_count": len(transition_cases),
        "transition_exact_accuracy": round(
            sum(1 for item in transition_cases if item["exact"]) / len(transition_cases), 6
        ) if transition_cases else 0.0,
        "burst_exact_accuracy": round(burst_exact_accuracy, 6),
        "review_or_recapture": sum(
            1 for item in per_case if "recapture_recommended" in item["flags"] or not item["predicted"]
        ),
        "cases": per_case,
        "bursts": burst_results,
        "scenarios": scenario_metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-file", type=Path, required=True)
    parser.add_argument("--fast", action="store_true", help="Desliga OCR caro para medir caminho rapido.")
    parser.add_argument("--output", type=Path, help="Também grava o relatório JSON neste caminho.")
    args = parser.parse_args()
    report = run_benchmark(args.case_file, expensive_ocr=not args.fast)
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
