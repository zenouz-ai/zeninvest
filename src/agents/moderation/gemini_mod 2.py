"""Gemini moderator — independent risk assessor."""

import json
import re
from typing import Any

from google import genai
from google.genai import types

from src.utils.config import get_settings
from src.utils.cost_tracker import Provider, check_budget, log_cost
from src.utils.logger import get_logger

logger = get_logger("gemini_moderator")

SYSTEM_PROMPT = """You are an independent risk assessor on an Investment Committee.
Score each proposed trade on three dimensions:
- Growth potential: 1-10
- Risk level: 1-10
- Confidence in thesis: 1-10

Flag any trade where risk > growth potential.
Consider news sentiment data in your scoring.

IMPORTANT: Keep your assessment under 100 words. Respond with ONLY valid JSON:
{
  "verdict": "AGREE|DISAGREE|MODIFY",
  "growth_score": 7,
  "risk_score": 4,
  "confidence_score": 6,
  "assessment": "2-sentence independent assessment",
  "high_risk_flag": false,
  "modifications": null
}"""


def review_trade(
    trade_proposal: dict[str, Any],
    portfolio_context: str,
    sentiment_data: str,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    """Have Gemini review a trade proposal.

    Args:
        trade_proposal: Strategy agent's decision for a single stock
        portfolio_context: Current portfolio state description
        sentiment_data: Finnhub/AV sentiment data for the stock

    Returns:
        Moderator verdict with scores and reasoning.
    """
    settings = get_settings()

    if not check_budget(Provider.GOOGLE.value):
        logger.warning("Google budget exceeded, skipping Gemini moderation")
        return {"verdict": "SKIP", "reasoning": "Budget exceeded", "available": False}

    user_prompt = f"""Independently assess this proposed trade:

## Trade Proposal
{json.dumps(trade_proposal, indent=2)}

## Portfolio Context
{portfolio_context}

## Sentiment Data
{sentiment_data}

Score growth potential, risk level, and confidence. Flag if risk > growth.
Respond with JSON only."""

    try:
        client = genai.Client(api_key=settings.google_ai_api_key)

        response = client.models.generate_content(
            model=settings.moderator_2_model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=2048,
                temperature=0.3,
            ),
        )

        # Log cost
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0

        log_cost(
            provider=Provider.GOOGLE.value,
            model=settings.moderator_2_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cycle_id=cycle_id,
            purpose="moderation_gemini",
        )

        content = response.text or ""
        # Extract JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        content = content.strip()
        result = _parse_json_with_repair(content)
        result["moderator"] = settings.moderator_2_model
        result["available"] = True
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Gemini returned invalid JSON: {e}")
        return {
            "verdict": "AGREE",
            "reasoning": f"Could not parse response: {e}",
            "moderator": settings.moderator_2_model,
            "available": True,
            "parse_error": True,
        }
    except Exception as e:
        logger.error(f"Gemini moderation failed: {e}")
        return {
            "verdict": "SKIP",
            "reasoning": f"API error: {e}",
            "moderator": settings.moderator_2_model,
            "available": False,
        }


def _parse_json_with_repair(text: str) -> dict[str, Any]:
    """Parse JSON with repair for common LLM output issues.

    Handles truncated strings, missing closing braces, trailing commas, etc.
    Raises json.JSONDecodeError if repair is not possible.
    """
    # First try normal parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Repair: fix unterminated strings by closing them
    repaired = text
    # Remove trailing comma before closing brace
    repaired = re.sub(r",\s*}", "}", repaired)
    repaired = re.sub(r",\s*$", "", repaired)

    # Count open/close braces to detect truncation
    open_braces = repaired.count("{") - repaired.count("}")
    open_quotes = repaired.count('"') % 2

    # Close any unterminated string
    if open_quotes:
        repaired += '"'

    # Close any open braces
    repaired += "}" * open_braces

    # Remove trailing comma before closing brace (again after repair)
    repaired = re.sub(r",\s*}", "}", repaired)

    try:
        result = json.loads(repaired)
        logger.info("Gemini JSON repaired successfully")
        return result
    except json.JSONDecodeError:
        pass

    # Last resort: try to extract key fields with regex
    verdict_match = re.search(r'"verdict"\s*:\s*"(AGREE|DISAGREE|MODIFY)"', text)
    growth_match = re.search(r'"growth_score"\s*:\s*(\d+)', text)
    risk_match = re.search(r'"risk_score"\s*:\s*(\d+)', text)
    confidence_match = re.search(r'"confidence_score"\s*:\s*(\d+)', text)

    if verdict_match:
        logger.info("Gemini JSON extracted via regex fallback")
        growth = int(growth_match.group(1)) if growth_match else 5
        risk = int(risk_match.group(1)) if risk_match else 5
        return {
            "verdict": verdict_match.group(1),
            "growth_score": growth,
            "risk_score": risk,
            "confidence_score": int(confidence_match.group(1)) if confidence_match else 5,
            "assessment": "Extracted from malformed response",
            "high_risk_flag": risk > growth,
            "modifications": None,
        }

    # Nothing worked — raise the original error
    raise json.JSONDecodeError("Could not repair Gemini JSON output", text, 0)
