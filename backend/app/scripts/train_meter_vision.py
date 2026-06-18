"""Treina um classificador de digitos com amostras aprovadas e promove com gate.

Uso:
  python -m app.scripts.train_meter_vision --candidate /app/models/meter-candidate.yml
  python -m app.scripts.train_meter_vision --candidate ... --promote /app/models/meter-current.yml
"""

import argparse
import asyncio
import hashlib
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
from sqlalchemy import select

from app.database import async_session_factory
from app.models.vision_inference import VisionInference
from app.services.meter_vision import hog_features
from app.utils.storage import read_binary


def _confirmed_digits(sample: VisionInference) -> list[int] | None:
    if sample.confirmed_value is None:
        return None
    red = sample.red_digits or 0
    total = (sample.black_digits or 4) + red
    raw = int(round(float(sample.confirmed_value) * (10 ** red)))
    text = str(raw).zfill(total)
    if len(text) > total:
        return None
    return [int(char) for char in text]


def _slots(image, total: int):
    margin_x = max(int(image.shape[1] * 0.025), 1)
    margin_y = max(int(image.shape[0] * 0.08), 1)
    roi = image[margin_y:image.shape[0] - margin_y, margin_x:image.shape[1] - margin_x]
    width = roi.shape[1] / total
    for index in range(total):
        start = max(0, int(index * width - width * 0.08))
        end = min(roi.shape[1], int((index + 1) * width + width * 0.08))
        yield roi[:, start:end]


async def load_dataset():
    train_x, train_y, test_x, test_y = [], [], [], []
    async with async_session_factory() as db:
        samples = (await db.execute(
            select(VisionInference).where(
                VisionInference.approved_for_training.is_(True),
                VisionInference.confirmed_value.is_not(None),
                VisionInference.rectified_object_key.is_not(None),
            )
        )).scalars().all()
        for sample in samples:
            labels = _confirmed_digits(sample)
            raw = read_binary(sample.rectified_object_key or "")
            if not labels or not raw:
                continue
            image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                continue
            split_key = str(sample.hydrometer_id or sample.id).encode()
            is_test = int(hashlib.sha256(split_key).hexdigest()[:4], 16) % 5 == 0
            for slot, label in zip(_slots(image, len(labels)), labels):
                (test_x if is_test else train_x).append(hog_features(slot).reshape(-1))
                (test_y if is_test else train_y).append(label)
    return train_x, train_y, test_x, test_y


async def train(candidate: Path, promote: Path | None, minimum_accuracy: float) -> dict:
    train_x, train_y, test_x, test_y = await load_dataset()
    if len(train_x) < 100 or len(set(train_y)) < 8:
        raise RuntimeError("Dataset insuficiente: são necessários ao menos 100 slots e 8 dígitos distintos")
    model = cv2.ml.KNearest_create()
    model.train(np.asarray(train_x, dtype=np.float32), cv2.ml.ROW_SAMPLE, np.asarray(train_y, dtype=np.float32))
    candidate.parent.mkdir(parents=True, exist_ok=True)
    model.save(str(candidate))

    accuracy = 0.0
    if test_x:
        _, result, _, _ = model.findNearest(np.asarray(test_x, dtype=np.float32), k=5)
        predicted = result.reshape(-1).round().astype(int)
        accuracy = float((predicted == np.asarray(test_y)).mean())
    metrics = {
        "train_slots": len(train_x),
        "test_slots": len(test_x),
        "digit_accuracy": round(accuracy, 6),
        "promoted": False,
    }
    if promote and test_x and accuracy >= minimum_accuracy:
        promote.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, promote)
        metrics["promoted"] = True
    candidate.with_suffix(candidate.suffix + ".metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--promote", type=Path)
    parser.add_argument("--minimum-accuracy", type=float, default=0.98)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(train(args.candidate, args.promote, args.minimum_accuracy)), indent=2))


if __name__ == "__main__":
    main()
