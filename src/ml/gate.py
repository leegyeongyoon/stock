"""학습된 ML 모델 로드/저장/예측 — 라이브 진입 게이트.

auto_optimize가 만든 최적 모델을 라이브 전략이 로드해, 각 봉의 매수확률이 임계 이상일 때만 진입.
"""

import pickle
from pathlib import Path
from typing import Optional

MODEL_DIR = Path("models")
MODEL_PATH = MODEL_DIR / "ml_gate_latest.pkl"


class MLGate:
    """학습 모델 + 특징목록 + 진입 임계확률."""

    def __init__(self, model, feature_names: list[str], threshold: float):
        self.model = model
        self.feature_names = feature_names
        self.threshold = threshold

    @classmethod
    def load(cls, path: Path = MODEL_PATH) -> Optional["MLGate"]:
        p = Path(path)
        if not p.exists():
            return None
        d = pickle.loads(p.read_bytes())
        return cls(d["model"], d["features"], d["threshold"])

    def save(self, path: Path = MODEL_PATH) -> None:
        MODEL_DIR.mkdir(exist_ok=True)
        Path(path).write_bytes(pickle.dumps({
            "model": self.model, "features": self.feature_names, "threshold": self.threshold,
        }))

    def prob(self, feature_row: list[float]) -> float:
        return float(self.model.predict_proba([feature_row])[0, 1])

    def passes(self, feature_row: list[float]) -> bool:
        return self.prob(feature_row) >= self.threshold
