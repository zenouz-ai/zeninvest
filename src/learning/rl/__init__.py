"""Offline-RL research surface for the trade-outcome learning pipeline.

The modules here are **research-only** and never wired into autonomous trading.
The promotion criteria are documented in ``docs/RL_RESEARCH.md``.

Imports are lazy so callers without the ``rl`` poetry extra
(``gymnasium`` / ``d3rlpy``) can still import the rest of ``src.learning``.
"""
