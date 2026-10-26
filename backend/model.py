from pathlib import Path
import time

import joblib


class EmotionModel:
    """Adapter boundary: replace this baseline with a trained transformer later."""

    def __init__(self, path: Path):
        self.bundle = joblib.load(path) if path.is_file() else None

    @property
    def ready(self) -> bool:
        return self.bundle is not None

    def predict(self, text: str) -> dict:
        if not self.bundle:
            return {"status": "unavailable", "emotions": [], "model_version": None}
        started = time.perf_counter()
        features = self.bundle["vectorizer"].transform([text])
        if features.nnz == 0:
            return {
                "status": "uncertain", "emotions": [],
                "model_version": self.bundle["version"],
                "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            }
        scores = self.bundle["classifier"].predict_proba(features)[0]
        labels = self.bundle["labels"]
        threshold = self.bundle["threshold"]
        selected = sorted(
            [{"label": label, "score": round(float(score), 4)}
             for label, score in zip(labels, scores) if score >= threshold],
            key=lambda item: item["score"], reverse=True,
        )
        # Neutral and an emotional label should not be presented simultaneously.
        if any(item["label"] != "neutral" for item in selected):
            selected = [item for item in selected if item["label"] != "neutral"]
        return {
            "status": "complete" if selected else "uncertain",
            "emotions": selected,
            "model_version": self.bundle["version"],
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

