"""GPT-4o moderator — skeptical investment analyst."""

import json
from typing import Any

import openai

from src.utils.config import get_settings
from src.utils.cost_tracker import Provider, check_budget, log_cost
from src.utils.logger import get_logger

logger = get_logger("openai_moderator")

SYSTEM_PROMPT = """You are a skeptical investment analyst serving on an Investment Committee.
Your role is to challenge assumptions, identify risks the primary analyst may have missed,
and flag recency bias or overfitting to recent trends.

You have access to Finnhub sentiment data — use it to verify or challenge the thesis.

For each proposed trade, respond with ONLY valid JSON:
{
  "verdict": "AGREE|DISAGREE|MODIFY",
  "reasoning": "2-3 sentence specific reasoning",
  "risk_flags": ["list of specific risks identified"],
  "modifications": null or {"target_allocation_pct": X, "stop_loss_pct": Y}
}"""


def review_trade(
    trade_proposal: dict[str, Any],
    portfolio_context: str,
    sentiment_data: str,
    cycle_id: str | None = None,
) -> dict[str, Any]:
    """Have GPT-4o review a trade proposal.

    Args:
        trade_proposal: Strategy agent's decision for a single stock
        portfolio_context: Current portfolio state description
        sentiment_data: Finnhub/AV sentiment data for the stock

    Returns:
        Moderator verdict with reasoning.
    """
    settings = get_settings()

    if not check_budget(Provider.OPENAI.value):
        logger.warning("OpenAI budget exceeded, skipping moderation")
        return {"verdict": "SKIP", "reasoning": "Budget exceeded", "available": False}

    user_prompt = f"""Review this proposed trade:

## Trade Proposal
{json.dumps(trade_proposal, indent=2)}

## Portfolio Context
{portfolio_context}

## Sentiment Data
{sentiment_data}

Challenge the thesis. Is the conviction justified? Are there risks being ignored?
Respond with JSON only."""

    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model=settings.moderator_1_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=1024,
            temperature=0.3,
        )

        # Log cost
        usage = response.usage
        if usage:
            log_cost(
                provider=Provider.OPENAI.value,
                model=settings.moderator_1_model,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                cycle_id=cycle_id,
                purpose="moderation_gpt4o",
            )

        content = response.choices[0].message.content or ""
        # Extract JSON
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        result = json.loads(content)
        result["moderator"] = "gpt-4o"
        result["available"] = True
        return result

    except json.JSONDecodeError as e:
        logger.error(f"GPT-4o returned invalid JSON: {e}")
        return {
            "verdict": "AGREE",
            "reasoning": f"Could not parse response: {e}",
            "moderator": "gpt-4o",
            "available": True,
            "parse_error": True,
        }
    except Exception as e:
        logger.error(f"GPT-4o moderation failed: {e}")
        return {
            "verdict": "SKIP",
            "reasoning": f"API error: {e}",
            "moderator": "gpt-4o",
            "available": False,
        }
