"""Treina e exporta o classificador multi-head de roletes para ONNX.

O JSON de entrada é produzido por GET /api/hydrometers/vision-training/export.
As divisões são feitas por hidrômetro físico para impedir vazamento de bursts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch
from torch import nn
from torch.utils.data import DataLoader, Dataset


@dataclass
class SlotSample:
    image: np.ndarray
    digit: int
    state: int
    phase: float
    visibility: float
    group: str


def _read_image(source: str) -> np.ndarray | None:
    try:
        raw = urllib.request.urlopen(source, timeout=30).read() if source.startswith(("http://", "https://")) else Path(source).read_bytes()
    except (OSError, ValueError):
        return None
    return cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)


def _slot_crops(image: np.ndarray, total: int) -> list[np.ndarray]:
    margin_x = max(int(image.shape[1] * 0.025), 1)
    margin_y = max(int(image.shape[0] * 0.08), 1)
    roi = image[margin_y:image.shape[0] - margin_y, margin_x:image.shape[1] - margin_x]
    width = roi.shape[1] / total
    return [
        roi[:, max(0, int(index * width - width * 0.08)):min(roi.shape[1], int((index + 1) * width + width * 0.08))]
        for index in range(total)
    ]


def load_samples(dataset_path: Path) -> list[SlotSample]:
    payload = json.loads(dataset_path.read_text(encoding="utf-8"))
    samples = []
    for item in payload.get("samples") or []:
        source = item.get("rectified_url") or item.get("rectified_object_key")
        confirmed_code = str(item.get("confirmed_code") or "")
        if not source or not confirmed_code.isdigit():
            continue
        image = _read_image(source)
        if image is None:
            continue
        labels_by_position = {int(label["position"]): label for label in item.get("slot_labels") or [] if "position" in label}
        group = str(item.get("hydrometer_id") or item.get("id"))
        for position, (crop, digit_text) in enumerate(zip(_slot_crops(image, len(confirmed_code)), confirmed_code)):
            label = labels_by_position.get(position) or {}
            current = int(label.get("current_digit", digit_text))
            transitional = label.get("state") == "transition"
            samples.append(SlotSample(
                image=crop,
                digit=current,
                state=current if transitional else 10,
                phase=float(label.get("transition_phase") or 0.0),
                visibility=float(label.get("visibility") or 1.0),
                group=group,
            ))
    return samples


class MeterSlots(Dataset):
    def __init__(self, samples: list[SlotSample], augment: bool):
        self.samples = samples
        self.augment = augment

    def __len__(self):
        return len(self.samples)

    def __getitem__(self, index: int):
        sample = self.samples[index]
        gray = cv2.cvtColor(sample.image, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, (64, 96), interpolation=cv2.INTER_AREA)
        if self.augment:
            alpha = np.random.uniform(0.82, 1.18)
            beta = np.random.uniform(-18, 18)
            gray = np.clip(gray.astype("float32") * alpha + beta, 0, 255).astype("uint8")
            if np.random.random() < 0.20:
                gray = cv2.GaussianBlur(gray, (3, 3), np.random.uniform(0.1, 0.8))
        tensor = torch.from_numpy(gray.astype("float32") / 255.0).unsqueeze(0)
        return (
            tensor,
            torch.tensor(sample.digit, dtype=torch.long),
            torch.tensor(sample.state, dtype=torch.long),
            torch.tensor(sample.phase, dtype=torch.float32),
            torch.tensor(sample.visibility, dtype=torch.float32),
        )


class TransitionNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.features = nn.Sequential(
            nn.Conv2d(1, 32, 3, padding=1), nn.BatchNorm2d(32), nn.SiLU(), nn.MaxPool2d(2),
            nn.Conv2d(32, 64, 3, padding=1), nn.BatchNorm2d(64), nn.SiLU(), nn.MaxPool2d(2),
            nn.Conv2d(64, 128, 3, padding=1), nn.BatchNorm2d(128), nn.SiLU(),
            nn.AdaptiveAvgPool2d((3, 2)),
        )
        self.shared = nn.Sequential(nn.Flatten(), nn.Linear(128 * 3 * 2, 192), nn.SiLU(), nn.Dropout(0.15))
        self.digit = nn.Linear(192, 10)
        self.state = nn.Linear(192, 11)  # 0..9 = n→n+1; 10 = estável
        self.phase = nn.Sequential(nn.Linear(192, 1), nn.Sigmoid())
        self.visibility = nn.Sequential(nn.Linear(192, 1), nn.Sigmoid())

    def forward(self, image):
        encoded = self.shared(self.features(image))
        return self.digit(encoded), self.state(encoded), self.phase(encoded), self.visibility(encoded)


def _split(samples: list[SlotSample]) -> tuple[list[SlotSample], list[SlotSample]]:
    train, validation = [], []
    for sample in samples:
        bucket = int(hashlib.sha256(sample.group.encode()).hexdigest()[:8], 16) % 5
        (validation if bucket == 0 else train).append(sample)
    return train, validation


def train(dataset: Path, output: Path, epochs: int, batch_size: int) -> dict:
    samples = load_samples(dataset)
    train_samples, validation_samples = _split(samples)
    transition_count = sum(1 for sample in train_samples if sample.state != 10)
    if len(train_samples) < 1000 or len(validation_samples) < 200 or transition_count < 100:
        raise RuntimeError(
            f"Dataset insuficiente: treino={len(train_samples)}, validação={len(validation_samples)}, transições={transition_count}"
        )

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = TransitionNet().to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    train_loader = DataLoader(MeterSlots(train_samples, True), batch_size=batch_size, shuffle=True, num_workers=0)
    validation_loader = DataLoader(MeterSlots(validation_samples, False), batch_size=batch_size, shuffle=False, num_workers=0)

    for _ in range(epochs):
        model.train()
        for image, digit, state, phase, visibility in train_loader:
            image, digit, state, phase, visibility = [item.to(device) for item in (image, digit, state, phase, visibility)]
            digit_logits, state_logits, predicted_phase, predicted_visibility = model(image)
            transition_mask = state != 10
            phase_loss = (
                nn.functional.smooth_l1_loss(predicted_phase.squeeze(1)[transition_mask], phase[transition_mask])
                if transition_mask.any() else torch.tensor(0.0, device=device)
            )
            loss = (
                nn.functional.cross_entropy(digit_logits, digit)
                + nn.functional.cross_entropy(state_logits, state) * 1.25
                + phase_loss * 0.75
                + nn.functional.binary_cross_entropy(predicted_visibility.squeeze(1), visibility) * 0.25
            )
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

    model.eval()
    digit_hits = state_hits = transition_hits = transition_total = total = 0
    with torch.no_grad():
        for image, digit, state, _, _ in validation_loader:
            digit_logits, state_logits, _, _ = model(image.to(device))
            digit_prediction = digit_logits.argmax(1).cpu()
            state_prediction = state_logits.argmax(1).cpu()
            digit_hits += int((digit_prediction == digit).sum())
            state_hits += int((state_prediction == state).sum())
            transition_mask = state != 10
            transition_hits += int(((state_prediction == state) & transition_mask).sum())
            transition_total += int(transition_mask.sum())
            total += len(digit)

    output.parent.mkdir(parents=True, exist_ok=True)
    cpu_model = model.cpu()
    torch.onnx.export(
        cpu_model,
        torch.zeros(1, 1, 96, 64),
        output,
        input_names=["slot"],
        output_names=["digit_logits", "transition_state_logits", "phase", "visibility"],
        dynamic_axes={"slot": {0: "batch"}},
        opset_version=17,
    )
    metrics = {
        "train_slots": len(train_samples),
        "validation_slots": len(validation_samples),
        "train_transitions": transition_count,
        "digit_accuracy": round(digit_hits / max(total, 1), 6),
        "state_accuracy": round(state_hits / max(total, 1), 6),
        "transition_accuracy": round(transition_hits / max(transition_total, 1), 6),
        "device": str(device),
    }
    output.with_suffix(output.suffix + ".metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=24)
    parser.add_argument("--batch-size", type=int, default=64)
    args = parser.parse_args()
    print(json.dumps(train(args.dataset, args.output, args.epochs, args.batch_size), indent=2))


if __name__ == "__main__":
    main()
