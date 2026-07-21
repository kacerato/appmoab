"""Promove um modelo somente quando o benchmark congelado passa nos gates.

Exemplo:
  python -m app.scripts.promote_meter_vision \
    --candidate models/meter-candidate.onnx \
    --benchmark benchmark.json \
    --promote models/meter-current.onnx \
    --registry models/registry.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_GATES = {
    "minimum_cases": 500,
    "exact_accuracy": 0.98,
    "digit_accuracy": 0.995,
    "transition_exact_accuracy": 0.97,
    "burst_exact_accuracy": 0.99,
    "maximum_silent_errors": 0,
    "p95_ms": 1200.0,
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def evaluate(report: dict, gates: dict) -> list[str]:
    failures = []
    comparisons = (
        ("count", ">=", int(gates["minimum_cases"])),
        ("exact_accuracy", ">=", float(gates["exact_accuracy"])),
        ("digit_accuracy", ">=", float(gates["digit_accuracy"])),
        ("transition_exact_accuracy", ">=", float(gates["transition_exact_accuracy"])),
        ("burst_exact_accuracy", ">=", float(gates["burst_exact_accuracy"])),
        ("p95_ms", "<=", float(gates["p95_ms"])),
        ("silent_errors", "<=", int(gates["maximum_silent_errors"])),
    )
    for key, operator, expected in comparisons:
        actual = report.get(key)
        if actual is None:
            failures.append(f"métrica ausente: {key}")
            continue
        passed = actual >= expected if operator == ">=" else actual <= expected
        if not passed:
            failures.append(f"{key}={actual} precisa ser {operator} {expected}")
    return failures


def promote(candidate: Path, benchmark: Path, destination: Path, registry: Path, gates: dict) -> dict:
    if not candidate.is_file():
        raise RuntimeError(f"Modelo candidato não encontrado: {candidate}")
    report = json.loads(benchmark.read_text(encoding="utf-8"))
    failures = evaluate(report, gates)
    if failures:
        raise RuntimeError("Promoção bloqueada: " + "; ".join(failures))

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate, destination)
    entry = {
        "promoted_at": datetime.now(timezone.utc).isoformat(),
        "candidate": str(candidate),
        "destination": str(destination),
        "sha256": _sha256(destination),
        "benchmark": str(benchmark),
        "metrics": {key: report.get(key) for key in (
            "count",
            "exact_accuracy",
            "digit_accuracy",
            "transition_exact_accuracy",
            "burst_exact_accuracy",
            "silent_errors",
            "p95_ms",
        )},
        "gates": gates,
    }
    registry.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(registry.read_text(encoding="utf-8")) if registry.exists() else {"models": []}
    payload.setdefault("models", []).append(entry)
    registry.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return entry


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--promote", type=Path, required=True)
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--gates", type=Path)
    args = parser.parse_args()
    gates = dict(DEFAULT_GATES)
    if args.gates:
        gates.update(json.loads(args.gates.read_text(encoding="utf-8")))
    print(json.dumps(promote(args.candidate, args.benchmark, args.promote, args.registry, gates), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
