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
    research_executor=None,
) -> dict[str, Any]:
    """Have GPT-4o review a trade proposal with full market context.

    Args:
        trade_proposal: Strategy agent's decision for a single stock.
        portfolio_context: Current portfolio state description.
        market_context: Rich dict containing indicators, fundamentals, macro,
                       sub-strategy scores, analyst data, and news sentiment.
        cycle_id: Optional cycle identifier for cost tracking.
        research_executor: Optional ResearchExecutor for tool-use (skeptic research).

    Returns:
        Moderator verdict with reasoning.
    """
    if research_executor:
        return _review_with_tools(
            trade_proposal, portfolio_context, market_context, cycle_id, research_executor,
        )
    return _review_single_turn(
        trade_proposal, portfolio_context, market_context, cycle_id,
    )


def _review_single_turn(
    trade_proposal: dict[str, Any],
    portfolio_context: str,
    market_context: dict[str, Any],
    cycle_id: str | None,
) -> dict[str, Any]:
    """Single-turn moderation without tools."""
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


def _review_with_tools(
    trade_proposal: dict[str, Any],
    portfolio_context: str,
    market_context: dict[str, Any],
    cycle_id: str | None,
    research_executor: Any,
) -> dict[str, Any]:
    """Moderation with tool-use loop (skeptic research)."""
    from src.agents.research.tools import get_research_tools_openai

    settings = get_settings()
    ticker = trade_proposal.get("ticker", "general")
    context_text = format_market_context(market_context)
    tools = get_research_tools_openai()
    sys_prompt = SYSTEM_PROMPT + "\n\nYou may use research tools to find bear cases or analyst downgrades. Use sparingly (1-2 searches). When done, respond with JSON only."
    user_prompt = f"""Review this proposed trade:

## Trade Proposal
{json.dumps(trade_proposal, indent=2)}

## Portfolio Context
{portfolio_context}

{context_text}

Challenge the thesis. Use tools if needed to find bear cases or downgrades. Respond with JSON only."""

    messages: list[dict] = [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": user_prompt},
    ]
    max_iter = 4

    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)
        for _ in range(max_iter):
            if not check_budget(Provider.OPENAI.value):
                return {"verdict": "SKIP", "reasoning": "Budget exceeded", "available": False}

            response = client.chat.completions.create(
                model=settings.moderator_1_model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                max_tokens=1024,
                temperature=0.4,
            )

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

            msg = response.choices[0].message
            tool_calls = getattr(msg, "tool_calls", None) or []

            if not tool_calls and msg.content:
                content = msg.content or ""
                if "```json" in content:
                    content = content.split("```json")[1].split("```")[0]
                elif "```" in content:
                    content = content.split("```")[1].split("```")[0]
                result = json.loads(content)
                result["moderator"] = "gpt-4o"
                result["available"] = True
                return result

            if not tool_calls:
                break

            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [
                    {"id": tc.id, "type": "function", "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ],
            })

            tool_result_parts = []
            for tc in tool_calls:
                fn = tc.function
                name = fn.name
                try:
                    inp = json.loads(fn.arguments or "{}")
                except json.JSONDecodeError:
                    inp = {}
                t = inp.get("ticker", ticker) or "general"
                n = inp.get("num_results", 5)

                if name == "web_search":
                    res = research_executor.web_search("skeptic", t, inp.get("query", ""), n)
                elif name == "news_search":
                    res = research_executor.news_search("skeptic", t, inp.get("query", ""), n)
                elif name == "sector_search":
                    res = research_executor.sector_search("skeptic", t, inp.get("sector", ""), inp.get("query", ""), n)
                elif name == "sec_search":
                    res = research_executor.sec_search_tool("skeptic", t, inp.get("doc_type", "10-K"), n or 3)
                elif name == "macro_search":
                    res = research_executor.macro_search("skeptic", inp.get("query", ""), n)
                else:
                    res = [{"error": f"Unknown tool: {name}"}]

                tool_result_parts.append({
                    "type": "tool_result",
                    "tool_call_id": tc.id,
                    "content": json.dumps(res)[:8000] if res else "[]",
                })

            messages.append({"role": "user", "content": tool_result_parts})

        return _review_single_turn(trade_proposal, portfolio_context, market_context, cycle_id)

    except Exception as e:
        logger.error(f"GPT-4o tool-use moderation failed: {e}")
        return _review_single_turn(trade_proposal, portfolio_context, market_context, cycle_id)
