"""Leitor KNN portátil para os artefatos YAML usados pelo OCR de hidrômetros.

Este módulo não importa configuração, banco ou componentes da aplicação. Isso
permite validar o artefato durante o build da imagem, antes de existirem os
segredos que só são injetados no runtime.
"""

from __future__ import annotations

import math

import cv2
import numpy as np


def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


class PortableKnnModel:
    """Carrega e executa um KNN OpenCV YAML sem depender de ``cv2.ml``."""

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

    def verify_runtime(self) -> None:
        """Exercita o mesmo HOG e a mesma classificação usados nas requisições."""

        probe = np.zeros((28, 28), dtype=np.uint8)
        probe[5:23, 11:17] = 255
        self.classify_features(hog_features(probe))

    def classify_features(self, features: np.ndarray) -> tuple[int, float, list[float]]:
        features = np.asarray(features, dtype=np.float32).reshape(-1)
        if features.shape[0] != self.samples.shape[1]:
            raise RuntimeError(
                f"Vetor HOG incompatível: recebido {features.shape[0]}, esperado {self.samples.shape[1]}."
            )

        # ||a-b||² = ||a||² + ||b||² - 2a.b evita materializar uma matriz de
        # diferenças e usa a multiplicação vetorial otimizada do NumPy.
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
        # OpenCV resolve empate de classes pelo menor rótulo.
        digit = min(tied)
        vote_share = votes.count(digit) / max(len(votes), 1)
        distance_score = math.exp(-float(squared_distances[indices[0]]) / 120.0)
        confidence = _clamp(vote_share * 0.75 + distance_score * 0.25)
        scores = [votes.count(value) / max(len(votes), 1) for value in range(10)]
        return digit, confidence, scores


def hog_features(normalized_slot: np.ndarray) -> np.ndarray:
    """Extrai o descritor que foi usado para treinar o artefato embarcado."""

    constructor = getattr(cv2, "HOGDescriptor", None)
    if not callable(constructor):
        raise RuntimeError(
            "OpenCV incompleto: HOGDescriptor não está disponível. "
            "Verifique se existe apenas uma distribuição OpenCV instalada."
        )
    hog = constructor((28, 28), (14, 14), (7, 7), (7, 7), 9)
    features = hog.compute(np.ascontiguousarray(normalized_slot, dtype=np.uint8))
    if features is None or features.size != 324:
        size = 0 if features is None else int(features.size)
        raise RuntimeError(f"Descritor HOG incompatível: recebido {size}, esperado 324.")
    return features.reshape(1, -1).astype("float32")
