"""Trained models for the learning pipeline.

Concrete classes live in submodules so ``import src.learning.models`` does **not**
eager-load scikit-learn / LightGBM (optional ``learning`` poetry extra).

Import explicitly, e.g.::

    from src.learning.models.calibration import ConvictionCalibrator
    from src.learning.models.gbm import train_lightgbm_walk_forward
    from src.learning.models.stall import train_stall_model
"""

__all__ = [
    "CalibrationCurve",
    "ConvictionCalibrator",
    "fit_conviction_calibrator",
    "GBMTrainingResult",
    "LightGBMTradeScorer",
    "train_lightgbm_walk_forward",
    "StallSurvivalModel",
    "StallTrainingResult",
    "train_stall_model",
]
