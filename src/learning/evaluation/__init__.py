"""Champion/challenger decision quality evaluation (shadow-only)."""

from src.learning.evaluation.counterfactual import run_counterfactual_evaluation
from src.learning.evaluation.gates import check_promotion_gates
from src.learning.evaluation.policies import ALL_POLICIES, PolicyId

__all__ = [
    "ALL_POLICIES",
    "PolicyId",
    "check_promotion_gates",
    "run_counterfactual_evaluation",
]
