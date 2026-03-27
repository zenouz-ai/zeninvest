"""Specialist model wrappers for agentic conversational research."""

from __future__ import annotations

import json
import os
from typing import Any

import anthropic
import openai
from google import genai
from google.genai import types

from src.utils.config import get_settings
from src.utils.cost_tracker import Provider, check_budget, log_cost
from src.utils.logger import get_logger

logger = get_logger("conversation_specialists")


class ChatSpecialistEngine:
    """Hidden specialist calls used to enrich the single assistant voice."""

    def __init__(self) -> None:
        self.settings = get_settings()

    def build_committee_views(
        self,
        *,
        tickers: list[str],
        evidence_bundle: dict[str, Any],
        turn_mode: str,
    ) -> list[dict[str, Any]]:
        primary = tickers[0] if tickers else "general"
        bull = self._bull_view(primary, evidence_bundle)
        bear = self._bear_view(primary, evidence_bundle)
        risk = self._risk_view(primary, evidence_bundle)
        views = [view for view in (bull, bear, risk) if view]
        if views:
            return views
        return self._fallback_committee_views(primary, evidence_bundle, turn_mode)

    def _bull_view(self, ticker: str, evidence_bundle: dict[str, Any]) -> dict[str, Any] | None:
        if not self.settings.anthropic_api_key_optional or not check_budget(Provider.ANTHROPIC.value):
            return None
        if os.getenv("INVESTMENT_AGENT_USE_INMEMORY_DB") == "1":
            return None
        try:
            client = anthropic.Anthropic(api_key=self.settings.anthropic_api_key_optional)
            response = client.messages.create(
                model=self.settings.conversation_equity_specialist_model,
                max_tokens=500,
                system=(
                    "You are the bullish equity specialist in an investment operator console. "
                    "Given structured evidence, produce a concise JSON summary with no markdown."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "ticker": ticker,
                                "role": "bull",
                                "evidence_bundle": evidence_bundle,
                            }
                        ),
                    }
                ],
            )
            log_cost(
                provider=Provider.ANTHROPIC.value,
                model=self.settings.conversation_equity_specialist_model,
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
                cycle_id=f"chat-specialist-{ticker}",
                purpose="conversation_specialist_bull",
            )
            content = response.content[0].text if response.content else "{}"
            payload = json.loads(content)
            return {
                "role": "bull",
                "provider": Provider.ANTHROPIC.value,
                "model": self.settings.conversation_equity_specialist_model,
                "summary": payload.get("summary") or payload.get("thesis"),
                "stance": payload.get("stance") or "bullish",
                "confidence": payload.get("confidence"),
            }
        except Exception as exc:
            logger.warning("Bull specialist failed: %s", exc, exc_info=True)
            return None

    def _bear_view(self, ticker: str, evidence_bundle: dict[str, Any]) -> dict[str, Any] | None:
        if not self.settings.openai_api_key_optional or not check_budget(Provider.OPENAI.value):
            return None
        if os.getenv("INVESTMENT_AGENT_USE_INMEMORY_DB") == "1":
            return None
        try:
            client = openai.OpenAI(api_key=self.settings.openai_api_key_optional)
            response = client.chat.completions.create(
                model=self.settings.conversation_planner_model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are the skeptical analyst in an investment operator console. "
                            "Return JSON only with a short bearish case grounded in the provided evidence."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "ticker": ticker,
                                "role": "bear",
                                "evidence_bundle": evidence_bundle,
                            }
                        ),
                    },
                ],
                response_format={"type": "json_object"},
                temperature=0.3,
                max_tokens=400,
            )
            usage = response.usage
            if usage:
                log_cost(
                    provider=Provider.OPENAI.value,
                    model=self.settings.conversation_planner_model,
                    input_tokens=usage.prompt_tokens,
                    output_tokens=usage.completion_tokens,
                    cycle_id=f"chat-specialist-{ticker}",
                    purpose="conversation_specialist_bear",
                )
            payload = json.loads(response.choices[0].message.content or "{}")
            return {
                "role": "bear",
                "provider": Provider.OPENAI.value,
                "model": self.settings.conversation_planner_model,
                "summary": payload.get("summary") or payload.get("thesis"),
                "stance": payload.get("stance") or "skeptical",
                "confidence": payload.get("confidence"),
            }
        except Exception as exc:
            logger.warning("Bear specialist failed: %s", exc, exc_info=True)
            return None

    def _risk_view(self, ticker: str, evidence_bundle: dict[str, Any]) -> dict[str, Any] | None:
        if not self.settings.google_ai_api_key_optional or not check_budget(Provider.GOOGLE.value):
            return None
        if os.getenv("INVESTMENT_AGENT_USE_INMEMORY_DB") == "1":
            return None
        try:
            client = genai.Client(api_key=self.settings.google_ai_api_key_optional)
            response = client.models.generate_content(
                model=self.settings.conversation_risk_specialist_model,
                contents=json.dumps(
                    {
                        "ticker": ticker,
                        "role": "risk",
                        "evidence_bundle": evidence_bundle,
                    }
                ),
                config=types.GenerateContentConfig(
                    system_instruction=(
                        "You are the macro and risk specialist in an investment operator console. "
                        "Return JSON only with a short risk framing."
                    ),
                    max_output_tokens=350,
                    temperature=0.3,
                ),
            )
            input_tokens = 0
            output_tokens = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
            log_cost(
                provider=Provider.GOOGLE.value,
                model=self.settings.conversation_risk_specialist_model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cycle_id=f"chat-specialist-{ticker}",
                purpose="conversation_specialist_risk",
            )
            payload = json.loads((response.text or "{}").strip())
            return {
                "role": "risk",
                "provider": Provider.GOOGLE.value,
                "model": self.settings.conversation_risk_specialist_model,
                "summary": payload.get("summary") or payload.get("assessment"),
                "stance": payload.get("stance") or "risk-aware",
                "confidence": payload.get("confidence"),
            }
        except Exception as exc:
            logger.warning("Risk specialist failed: %s", exc, exc_info=True)
            return None

    def _fallback_committee_views(
        self,
        ticker: str,
        evidence_bundle: dict[str, Any],
        turn_mode: str,
    ) -> list[dict[str, Any]]:
        snapshot = (evidence_bundle.get("market_snapshot") or [{}])[0]
        rs = snapshot.get("relative_strength_6m")
        rsi = snapshot.get("rsi_14")
        related = evidence_bundle.get("related_tickers") or []
        return [
            {
                "role": "bull",
                "provider": "internal",
                "model": "deterministic",
                "summary": (
                    f"{ticker} still has constructive momentum signals."
                    if rs and float(rs) >= 1.0
                    else f"{ticker} may need stronger price leadership before a bullish case strengthens."
                ),
                "stance": "bullish",
            },
            {
                "role": "bear",
                "provider": "internal",
                "model": "deterministic",
                "summary": (
                    f"{ticker} looks stretched on momentum."
                    if rsi and float(rsi) >= 65
                    else f"The downside case is that {ticker} lacks a fresh catalyst in the current evidence set."
                ),
                "stance": "skeptical",
            },
            {
                "role": "risk",
                "provider": "internal",
                "model": "deterministic",
                "summary": (
                    f"Risk is tied to sector rotation and correlation with nearby names such as "
                    f"{', '.join(str(item.get('ticker')) for item in related[:2] if item.get('ticker'))}."
                    if related
                    else f"Risk should be sized carefully because the current {turn_mode} workflow is still evidence-limited."
                ),
                "stance": "risk-aware",
            },
        ]
