"""GPT-4o moderator — skeptical investment analyst.

Receives the full market context (indicators, fundamentals, macro, sub-strategy
scores, analyst data, news sentiment) to independently challenge the strategy
agent's trade proposals.
"""

import json
from typing import Any

import openai

from src.agents.moderation.context import format_market_context
from src.utils.config import get_settings
from src.utils.cost_tracker import Provider, check_budget, log_cost
from src.utils.logger import get_logger

logger = get_logger("openai_moderator")

SYSTEM_PROMPT = """You are a skeptical investment analyst serving on an Investment Committee.
Your role is to challenge assumptions, identify risks the primary analyst may have missed,
and flag recency bias or overfitting to recent trends.

You receive the full data context: technical indicators, fundamentals, market conditions,
sub-strategy scores, analyst recommendations, and news sentiment. Use ALL of this data
to independently verify whether the proposed trade is justified.

Key responsibilities:
- Verify the technical picture supports the action (RSI trend, MACD, Bollinger Bands, MAs)
- Confirm fundamentals are sound (P/E reasonable, ROE healthy, debt manageable, earnings growing)
- Check if news sentiment confirms or contradicts the thesis
- Assess whether the market regime (VIX, regime label) is appropriate for this trade type
- Identify conflicting signals across sub-strategies — disagreement = lower confidence
- Challenge the proposed allocation relative to the risk profile

Scoring guidelines:
- RSI 30-70 is neutral. <30 = oversold (mean reversion). >70 = overbought (caution).
- P/E <15 = value. >40 = expensive unless high-growth sector.
- Debt/Equity >2.0 is a red flag. <0.5 is strong.
- VIX >25 = elevated volatility, warrant smaller positions.
- When sub-strategies disagree (e.g. momentum BUY but factor LOW), consider MODIFY with reduced allocation rather than outright DISAGREE, unless the signals are clearly contradictory.

For each proposed trade, respond with ONLY valid JSON:
{
  "verdict": "AGREE|DISAGREE|MODIFY",
  "reasoning": "2-3 sentence specific reasoning referencing actual data points",
  "risk_flags": ["list of specific risks identified"],
  "modifications": null or {"target_allocation_pct": X, "stop_loss_pct": Y}
}"""


def review_trade(
    trade_proposal: dict[str, Any],
    portfolio_context: str,
    market_context: dict[str, Any],
    cycle_id: str | None = None,
) -> dict[str, Any]:
    """Have GPT-4o review a trade proposal with full market context.

    Args:
        trade_proposal: Strategy agent's decision for a single stock.
        portfolio_context: Current portfolio state description.
        market_context: Rich dict containing indicators, fundamentals, macro,
                       sub-strategy scores, analyst data, and news sentiment.
        cycle_id: Optional cycle identifier for cost tracking.

    Returns:
        Moderator verdict with reasoning.
    """
    settings = get_settings()

    if not check_budget(Provider.OPENAI.value):
        logger.warning("OpenAI budget exceeded, skipping moderation")
        return {"verdict": "SKIP", "reasoning": "Budget exceeded", "available": False}

    context_text = format_market_context(market_context)

    user_prompt = f"""Review this proposed trade:

## Trade Proposal
{json.dumps(trade_proposal, indent=2)}

## Portfolio Context
{portfolio_context}

{context_text}

Challenge the thesis. Is the conviction justified? Are there risks being ignored?
Do the technicals, fundamentals, and sentiment all support this trade?
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
            temperature=0.4,
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
