"""Conviction -> win-rate calibrator (US-2.1).

Tiny, 1-D model that turns Claude's ``conviction`` score into a calibrated
``predicted_win_rate``. Two flavours are exposed:

- Histogram per-bin (the curve the dashboard renders).
- Isotonic regression (monotone, used as the predictive output).

The Platt sigmoid is fitted as a fallback when the dataset is too small for
isotonic regression to be useful (< 30 rows per bin).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

try:  # pragma: no cover - import gate
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
except ImportError as exc:  # pragma: no cover - import gate
    raise RuntimeError(
        "scikit-learn is required for the conviction calibrator. "
        "Install it with `poetry install --with learning`."
    ) from exc


# Default conviction bin edges from US-2.1.
DEFAULT_BIN_EDGES: tuple[float, ...] = (0.0, 50.0, 60.0, 70.0, 80.0, 100.001)


@dataclass
class CalibrationCurve:
    """Calibration curve as bin -> empirical win rate."""

    bin_edges: list[float]
    bin_labels: list[str]
    bin_counts: list[int]
    bin_win_rates: list[float]
    min_samples_for_activation: int = 30

    def to_dict(self) -> dict:
        return {
            "bin_edges": self.bin_edges,
            "bin_labels": self.bin_labels,
            "bin_counts": self.bin_counts,
            "bin_win_rates": self.bin_win_rates,
            "min_samples_for_activation": self.min_samples_for_activation,
        }

    @property
    def active_bins(self) -> list[str]:
        """Bins that meet the US-2.1 activation threshold (>= 30 samples)."""
        return [
            label
            for label, count in zip(self.bin_labels, self.bin_counts)
            if count >= self.min_samples_for_activation
        ]


@dataclass
class ConvictionCalibrator:
    """Calibrator that maps conviction -> predicted win-rate."""

    curve: CalibrationCurve
    isotonic: IsotonicRegression | None = None
    platt: LogisticRegression | None = None
    fallback_rate: float = 0.5
    metadata: dict = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------

    def predict_win_rate(self, conviction: Iterable[float] | np.ndarray) -> np.ndarray:
        x = np.asarray(list(conviction), dtype=float)
        if self.isotonic is not None and len(self.isotonic.X_thresholds_) >= 2:
            return self.isotonic.predict(x).astype(float)
        if self.platt is not None:
            return self.platt.predict_proba(x.reshape(-1, 1))[:, 1].astype(float)
        return np.full(len(x), self.fallback_rate, dtype=float)

    def predict_one(self, conviction: float) -> float:
        return float(self.predict_win_rate([conviction])[0])

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.mkdir(parents=True, exist_ok=True)
        with open(path / "curve.json", "w") as fh:
            json.dump(self.curve.to_dict(), fh, indent=2)
        if self.isotonic is not None:
            # IsotonicRegression has no native JSON serialisation; persist the
            # learned breakpoints so we can rebuild on load.
            np.savez(
                path / "isotonic.npz",
                X=self.isotonic.X_thresholds_,
                Y=self.isotonic.y_thresholds_,
            )
        if self.platt is not None:
            np.savez(
                path / "platt.npz",
                coef=self.platt.coef_,
                intercept=self.platt.intercept_,
            )
        with open(path / "meta.json", "w") as fh:
            json.dump({"fallback_rate": self.fallback_rate, "metadata": self.metadata}, fh, indent=2)

    @classmethod
    def load(cls, path: str | Path) -> "ConvictionCalibrator":
        path = Path(path)
        with open(path / "curve.json") as fh:
            curve = CalibrationCurve(**json.load(fh))
        isotonic: IsotonicRegression | None = None
        platt: LogisticRegression | None = None
        iso_path = path / "isotonic.npz"
        if iso_path.exists():
            data = np.load(iso_path)
            isotonic = IsotonicRegression(out_of_bounds="clip")
            isotonic.X_thresholds_ = data["X"]
            isotonic.y_thresholds_ = data["Y"]
            isotonic.X_min_ = float(data["X"].min())
            isotonic.X_max_ = float(data["X"].max())
            isotonic.f_ = None  # rebuilt lazily on first predict
            isotonic._build_f(data["X"], data["Y"])  # type: ignore[attr-defined]
        platt_path = path / "platt.npz"
        if platt_path.exists():
            data = np.load(platt_path)
            platt = LogisticRegression()
            platt.coef_ = data["coef"]
            platt.intercept_ = data["intercept"]
            platt.classes_ = np.array([0, 1])
        meta = {}
        meta_path = path / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
        return cls(
            curve=curve,
            isotonic=isotonic,
            platt=platt,
            fallback_rate=float(meta.get("fallback_rate", 0.5)),
            metadata=meta.get("metadata", {}),
        )


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------


def _binarise(labels: Sequence[str]) -> np.ndarray:
    """Convert 3-class labels to win/not-win for the calibrator."""
    return np.asarray([1 if str(l) == "big_winner" else 0 for l in labels], dtype=int)


def fit_conviction_calibrator(
    df: pd.DataFrame,
    *,
    conviction_col: str = "conviction",
    label_col: str = "label_3class",
    bin_edges: Sequence[float] | None = None,
    min_samples_for_activation: int = 30,
) -> ConvictionCalibrator:
    """Fit a 1-D calibrator from a feature/label DataFrame."""
    if conviction_col not in df.columns or label_col not in df.columns:
        raise ValueError(f"Missing required columns: {conviction_col}, {label_col}")

    work = df[[conviction_col, label_col]].copy()
    work = work.dropna(subset=[conviction_col, label_col])
    if work.empty:
        return ConvictionCalibrator(
            curve=CalibrationCurve(
                bin_edges=list(bin_edges or DEFAULT_BIN_EDGES),
                bin_labels=[],
                bin_counts=[],
                bin_win_rates=[],
                min_samples_for_activation=min_samples_for_activation,
            )
        )

    edges = list(bin_edges or DEFAULT_BIN_EDGES)
    work["bin"] = pd.cut(
        work[conviction_col].astype(float),
        bins=edges,
        right=False,
        include_lowest=True,
    )
    work["win"] = _binarise(work[label_col].tolist())

    grouped = work.groupby("bin", observed=False)["win"].agg(["mean", "size"]).reset_index()
    bin_labels = [str(b) for b in grouped["bin"]]
    bin_counts = [int(c) for c in grouped["size"]]
    bin_win_rates = [float(r) if not pd.isna(r) else 0.0 for r in grouped["mean"]]

    curve = CalibrationCurve(
        bin_edges=edges,
        bin_labels=bin_labels,
        bin_counts=bin_counts,
        bin_win_rates=bin_win_rates,
        min_samples_for_activation=min_samples_for_activation,
    )

    isotonic: IsotonicRegression | None = None
    platt: LogisticRegression | None = None
    x = work[conviction_col].to_numpy(dtype=float)
    y = work["win"].to_numpy(dtype=float)
    fallback_rate = float(y.mean()) if len(y) else 0.5

    # Need at least a few distinct conviction values and both classes to fit
    # isotonic regression sensibly.
    distinct = np.unique(x).size
    classes = np.unique(y).size
    if distinct >= 3 and classes == 2 and len(y) >= 20:
        isotonic = IsotonicRegression(y_min=0.0, y_max=1.0, out_of_bounds="clip")
        isotonic.fit(x, y)
    elif classes == 2 and len(y) >= 10:
        platt = LogisticRegression()
        platt.fit(x.reshape(-1, 1), y)

    return ConvictionCalibrator(
        curve=curve,
        isotonic=isotonic,
        platt=platt,
        fallback_rate=fallback_rate,
        metadata={"n_rows": int(len(y)), "win_rate": fallback_rate},
    )
