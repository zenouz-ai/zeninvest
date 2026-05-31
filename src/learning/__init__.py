"""ZenInvest learning pipeline.

Trade-outcome learning module that turns logged decisions, moderation, risk,
opportunity, market context, and realized outcomes into a leakage-safe ML
dataset, plus models that predict big winners, big losers, and stalls.

This package is intentionally additive and has **no live trading influence**:

- It only reads from the existing SQLite tables and writes to ``data/learning/``.
- It does not import from ``src/orchestrator/main.py`` or any agent that could
  mutate broker state.
- Promotion to shadow / live influence is a separate, gated step (Option C).

See ``docs/LEARNING_PIPELINE.md`` for the data card and ``docs/RESEARCH_NOTES.md``
for the literature references that anchor the modelling choices.
"""

from src.learning.spec import (
    DATASET_VERSION,
    DatasetSpec,
    LabelConfig,
    get_default_spec,
)

__all__ = [
    "DATASET_VERSION",
    "DatasetSpec",
    "LabelConfig",
    "get_default_spec",
]
