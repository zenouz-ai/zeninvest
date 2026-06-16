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
from src.utils.prompt_loader import get_prompt_hash, load_prompt_file

logger = get_logger("openai_moderator")

SYSTEM_PROMPT = load_prompt_file("skeptic.md")


def get_skeptic_prompt_hash(model_name: str) -> str:
    """Return a stable hash for the GPT-4o skeptic moderator prompt."""
    return get_prompt_hash("skeptic.md", extra={"model": model_name})


def _normalize_modifications_payload(
    modifications: Any,
    *,
    moderator: str,
    ticker: str,
    cycle_id: str | None,
) -> dict[str, float] | None:
    """Coerce moderator modifications into a safe dict shape."""
    if modifications is None:
        return None

    parsed = modifications
    if isinstance(parsed, str):
        stripped = parsed.strip()
        if not stripped:
            return None
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            logger.warning(
                "Ignoring malformed %s modifications for %s in %s: type=str",
                moderator,
                ticker,
                cycle_id or "manual",
            )
            return None

    if not isinstance(parsed, dict):
        logger.warning(
            "Ignoring malformed %s modifications for %s in %s: type=%s",
            moderator,
            ticker,
            cycle_id or "manual",
            type(parsed).__name__,
        )
        return None

    normalized: dict[str, float] = {}
    for key in ("target_allocation_pct", "stop_loss_pct"):
        value = parsed.get(key)
        if value in (None, ""):
            continue
        try:
            normalized[key] = float(value)
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring invalid %s.%s for %s in %s: type=%s",
                moderator,
                key,
                ticker,
                cycle_id or "manual",
                type(value).__name__,
            )
    return normalized or None


def _normalize_openai_result(
    result: Any,
    *,
    ticker: str,
    cycle_id: str | None,
) -> dict[str, Any]:
    """Normalize GPT moderator output into a stable dict schema."""
    if not isinstance(result, dict):
        raise ValueError(f"GPT-4o returned non-object JSON ({type(result).__name__})")

    normalized = dict(result)
    normalized["verdict"] = str(normalized.get("verdict", "")).upper()
    normalized["modifications"] = _normalize_modifications_payload(
        normalized.get("modifications"),
        moderator="gpt-4o",
        ticker=ticker,
        cycle_id=cycle_id,
    )
    return normalized


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
            cost_result = log_cost(
                provider=Provider.OPENAI.value,
                model=settings.moderator_1_model,
                input_tokens=usage.prompt_tokens,
                output_tokens=usage.completion_tokens,
                cycle_id=cycle_id,
                purpose="moderation_gpt4o",
            )
        else:
            cost_result = None

        content = response.choices[0].message.content or ""
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]

        result = _normalize_openai_result(
            json.loads(content),
            ticker=str(trade_proposal.get("ticker", "UNKNOWN")),
            cycle_id=cycle_id,
        )
        result["moderator"] = "gpt-4o"
        result["available"] = True
        if usage:
            result["input_tokens"] = int(usage.prompt_tokens or 0)
            result["output_tokens"] = int(usage.completion_tokens or 0)
        if cost_result is not None:
            result["cost_gbp"] = cost_result.cost_gbp
        return result

    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"GPT-4o returned invalid JSON: {e}")
        # Default to DISAGREE on parse failure — a garbage response should not
        # silently approve trades. (Audit fix H-5.)
        return {
            "verdict": "DISAGREE",
            "reasoning": f"Could not parse response (defaulting to DISAGREE for safety): {e}",
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
                result = _normalize_openai_result(
                    json.loads(content),
                    ticker=str(trade_proposal.get("ticker", "UNKNOWN")),
                    cycle_id=cycle_id,
                )
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
