"""Intent normalization for natural-language evolution requests."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .policy import AREA_LABELS, classify_risk, detect_touched_areas

_VAGUE_PATTERNS = (
    "make it better",
    "improve the system",
    "update the system",
    "significant changes",
    "refactor everything",
    "change the system",
)


@dataclass(slots=True)
class NormalizedIntent:
    """Structured request representation used by the planner."""

    title: str
    objective: str
    combined_request_text: str
    touched_areas: list[str]
    excluded_areas: list[str]
    assumptions: list[str]
    clarification_questions: list[str]
    confidence_score: float
    risk_class: str
    risk_reasons: list[str]


class IntentNormalizer:
    """Convert operator text into a deterministic structured change spec."""

    def normalize(self, messages: list[str]) -> NormalizedIntent:
        combined_text = "\n\n".join(message.strip() for message in messages if message and message.strip())
        latest_message = next((message.strip() for message in reversed(messages) if message and message.strip()), combined_text)
        objective = self._extract_objective(latest_message)
        title = self._build_title(objective)
        touched_areas = detect_touched_areas(combined_text)
        excluded_areas = self._extract_exclusions(combined_text)
        risk_class, risk_reasons = classify_risk(touched_areas)
        assumptions = self._build_assumptions(touched_areas, risk_class)
        clarification_questions = self._build_clarification_questions(
            combined_text=combined_text,
            objective=objective,
            touched_areas=touched_areas,
            excluded_areas=excluded_areas,
        )
        confidence_score = max(
            0.35,
            0.94 - (0.16 * len(clarification_questions)) - (0.2 if not touched_areas else 0.0),
        )

        return NormalizedIntent(
            title=title,
            objective=objective,
            combined_request_text=combined_text,
            touched_areas=touched_areas,
            excluded_areas=excluded_areas,
            assumptions=assumptions,
            clarification_questions=clarification_questions,
            confidence_score=round(confidence_score, 2),
            risk_class=risk_class,
            risk_reasons=risk_reasons,
        )

    def _extract_objective(self, text: str) -> str:
        stripped = " ".join(text.strip().split())
        if not stripped:
            return "Untitled evolution request"

        sentence = re.split(r"(?<=[.!?])\s+", stripped, maxsplit=1)[0]
        if len(sentence) <= 180:
            return sentence.rstrip(".")
        return f"{sentence[:177].rstrip()}..."

    def _build_title(self, objective: str) -> str:
        words = objective.split()
        if not words:
            return "Untitled evolution request"
        short = " ".join(words[:10]).rstrip(".")
        if len(words) > 10:
            short = f"{short}..."
        return short

    def _extract_exclusions(self, text: str) -> list[str]:
        exclusions: list[str] = []
        for match in re.finditer(r"(?:do not|don't|without|exclude|leave|avoid)\s+([^.;\n]+)", text, flags=re.IGNORECASE):
            phrase = " ".join(match.group(1).strip().split())
            if phrase and phrase not in exclusions:
                exclusions.append(phrase)
        return exclusions

    def _build_assumptions(self, touched_areas: list[str], risk_class: str) -> list[str]:
        assumptions = [
            "The operator interface is the authenticated dashboard; Slack stays out of scope for this phase.",
            "Phase 1 remains planner-only and does not grant code or deployment authority.",
        ]
        if "deployment_infra" in touched_areas:
            assumptions.append("The current production control plane remains Docker Compose on the VPS.")
        if "trading_logic" in touched_areas or risk_class == "HIGH":
            assumptions.append(
                "Financially sensitive changes remain review-only and require dry-run plus backtest evidence before promotion."
            )
        if "dashboard_ui" in touched_areas and "dashboard_backend" not in touched_areas:
            assumptions.append("The request appears limited to operator-facing UI behavior rather than API changes.")
        return assumptions

    def _build_clarification_questions(
        self,
        *,
        combined_text: str,
        objective: str,
        touched_areas: list[str],
        excluded_areas: list[str],
    ) -> list[str]:
        lowered = combined_text.lower()
        questions: list[str] = []

        if not touched_areas:
            questions.append(
                "Which subsystem should this target first: dashboard UI, dashboard backend, notifications/reporting, or trading logic?"
            )

        if len(objective.split()) < 6 or (
            any(pattern in lowered for pattern in _VAGUE_PATTERNS) and not touched_areas
        ):
            questions.append(
                "What observable outcome should confirm the change is correct once implemented?"
            )

        if len(touched_areas) > 2 and not excluded_areas:
            touched_labels = ", ".join(AREA_LABELS[area] for area in touched_areas)
            questions.append(
                f"This request spans multiple areas ({touched_labels}). Should it stay as one workflow or be split into smaller steps?"
            )

        return questions
