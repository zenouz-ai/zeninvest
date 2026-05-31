"""Purged + embargoed walk-forward splits.

Implements the leakage-safe CV scheme from Lopez de Prado, *Advances in
Financial Machine Learning* ch. 7. Given an event timestamp index and a
label horizon, we:

1. Partition the timeline into N contiguous test windows.
2. For each test window, the training set is everything strictly before the
   window minus an ``embargo_days`` buffer to remove rows whose forward
   horizon would overlap the test period.

This is the only CV scheme that survives overlapping-horizon labels.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Iterable

import pandas as pd


@dataclass
class WalkForwardFold:
    """One walk-forward CV fold."""

    fold_id: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    train_indices: list[int]
    test_indices: list[int]


@dataclass
class WalkForwardSplits:
    """Full set of folds + metadata."""

    embargo_days: int
    n_folds: int
    test_window_days: int
    folds: list[WalkForwardFold]

    def to_dict(self) -> dict:
        return {
            "embargo_days": self.embargo_days,
            "n_folds": self.n_folds,
            "test_window_days": self.test_window_days,
            "folds": [
                {
                    **{k: v for k, v in asdict(f).items() if k not in {"train_start", "train_end", "test_start", "test_end"}},
                    "train_start": f.train_start.isoformat(),
                    "train_end": f.train_end.isoformat(),
                    "test_start": f.test_start.isoformat(),
                    "test_end": f.test_end.isoformat(),
                }
                for f in self.folds
            ],
        }

    def dump(self, path: str) -> None:
        with open(path, "w") as fh:
            json.dump(self.to_dict(), fh, indent=2, default=str)


class WalkForwardSplitter:
    """Build purged + embargoed walk-forward folds over a timestamp series."""

    def __init__(
        self,
        *,
        embargo_days: int,
        test_window_days: int = 14,
        n_folds: int | None = None,
        min_train_days: int = 14,
    ) -> None:
        if embargo_days < 0:
            raise ValueError("embargo_days must be non-negative")
        if test_window_days <= 0:
            raise ValueError("test_window_days must be positive")
        self.embargo_days = int(embargo_days)
        self.test_window_days = int(test_window_days)
        self.n_folds = n_folds
        self.min_train_days = int(min_train_days)

    def split(self, timestamps: Iterable[datetime]) -> WalkForwardSplits:
        ts = pd.to_datetime(list(timestamps))
        if len(ts) < 4:
            return WalkForwardSplits(self.embargo_days, 0, self.test_window_days, [])
        ts_sorted = ts.sort_values()
        first = ts_sorted.min().to_pydatetime()
        last = ts_sorted.max().to_pydatetime()
        span_days = max((last - first).days, 1)

        if self.n_folds:
            n = int(self.n_folds)
        else:
            n = max(1, span_days // self.test_window_days - 1)
        n = max(n, 1)
        total_test_days = n * self.test_window_days
        if total_test_days + self.min_train_days > span_days:
            n = max(1, (span_days - self.min_train_days) // self.test_window_days)
            n = max(n, 1)

        # Build folds backward from the end so the most recent slice is always tested.
        folds: list[WalkForwardFold] = []
        cursor_end = last
        idx_array = pd.Series(range(len(ts_sorted)), index=ts_sorted)

        for fold_id in range(n):
            test_end = cursor_end
            test_start = test_end - timedelta(days=self.test_window_days)
            train_end = test_start - timedelta(days=self.embargo_days)
            train_start = first
            if (train_end - train_start).days < self.min_train_days:
                break
            train_mask = (ts_sorted >= train_start) & (ts_sorted <= train_end)
            test_mask = (ts_sorted > test_start) & (ts_sorted <= test_end)
            train_indices = idx_array[train_mask].tolist()
            test_indices = idx_array[test_mask].tolist()
            if not train_indices or not test_indices:
                cursor_end = test_start
                continue
            folds.append(
                WalkForwardFold(
                    fold_id=fold_id,
                    train_start=train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    train_indices=[int(i) for i in train_indices],
                    test_indices=[int(i) for i in test_indices],
                )
            )
            cursor_end = test_start
        # Reverse so fold_id ascends in time.
        folds.sort(key=lambda f: f.test_start)
        for idx, fold in enumerate(folds):
            fold.fold_id = idx
        return WalkForwardSplits(
            embargo_days=self.embargo_days,
            n_folds=len(folds),
            test_window_days=self.test_window_days,
            folds=folds,
        )
