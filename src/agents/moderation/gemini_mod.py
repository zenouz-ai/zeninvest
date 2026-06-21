"""Gemini moderator — independent risk assessor.

Receives the full market context (indicators, fundamentals, macro, sub-strategy
scores, analyst data, news sentiment) to independently score growth potential,
risk level, and confidence for each trade proposal.
"""

import json
import re
from typing import Any

from google import genai
from google.genai import types

from src.agents.moderation.context import format_market_context
from src.utils.config import get_settings
from src.utils.cost_tracker import Provider, check_budget, log_cost
from src.utils.logger import get_logger
from src.utils.prompt_loader import get_prompt_hash, load_prompt_file

logger = get_logger("gemini_moderator")

SYSTEM_PROMPT = load_prompt_file("risk_assessor.md")


def get_risk_assessor_prompt_hash(model_name: str) -> str:
    """Return a stable hash for the Gemini risk-assessor moderator prompt."""
    return get_prompt_hash("risk_assessor.md", extra={"model": model_name})


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


def _peer_block(peer_argument: str | None) -> str:
    """Render an opposing committee member's argument for a rebuttal turn."""
    if not peer_argument:
        return ""
    return (
        "\n## Another committee analyst's assessment\n"
        f"{peer_argument}\n"
        "Engage directly with their argument: concede points that are valid, "
        "and push back where you disagree. Then give your own final assessment.\n"
    )


def review_trade(
    trade_proposal: dict[str, Any],
    portfolio_context: str,
    market_context: dict[str, Any],
    cycle_id: str | None = None,
    research_executor=None,
    peer_argument: str | None = None,
) -> dict[str, Any]:
    """Have Gemini review a trade proposal with full market context.

    Args:
        trade_proposal: Strategy agent's decision for a single stock.
        portfolio_context: Current portfolio state description.
        market_context: Rich dict containing indicators, fundamentals, macro,
                       sub-strategy scores, analyst data, and news sentiment.
        cycle_id: Optional cycle identifier for cost tracking.
        research_executor: Optional ResearchExecutor for tool-use (risk research).
    Returns:
        Moderator verdict with scores and reasoning.
    """
    settings = get_settings()
    use_tools = (
        research_executor is not None
        and settings.research_enabled
        and settings.risk_research_enabled
    )

    if use_tools:
        return _review_with_tools(
            trade_proposal, portfolio_context, market_context, cycle_id, research_executor,
            peer_argument=peer_argument,
        )
    return _review_single_turn(
        trade_proposal, portfolio_context, market_context, cycle_id, peer_argument=peer_argument,
    )


def _build_user_prompt(
    trade_proposal: dict,
    portfolio_context: str,
    market_context: dict,
    peer_argument: str | None = None,
) -> str:
    context_text = format_market_context(market_context)
    return f"""Independently assess this proposed trade:

## Trade Proposal
{json.dumps(trade_proposal, indent=2)}

## Portfolio Context
{portfolio_context}

{context_text}
{_peer_block(peer_argument)}
Score growth potential, risk level, and confidence using the data above.
Flag if risk > growth. Respond with JSON only."""


def _log_gemini_cost(response: Any, cycle_id: str | None, settings: Any):
    input_tokens = 0
    output_tokens = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
        output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
    return log_cost(
        provider=Provider.GOOGLE.value,
        model=settings.moderator_2_model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cycle_id=cycle_id,
        purpose="moderation_gemini",
    )


def _attach_gemini_usage(result: dict[str, Any], response: Any, cost_result: Any) -> None:
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        result["input_tokens"] = int(getattr(response.usage_metadata, "prompt_token_count", 0) or 0)
        result["output_tokens"] = int(getattr(response.usage_metadata, "candidates_token_count", 0) or 0)
    if cost_result is not None:
        result["cost_gbp"] = cost_result.cost_gbp


def _extract_json_from_text(content: str) -> str:
    if "```json" in content:
        content = content.split("```json")[1].split("```")[0]
    elif "```" in content:
        content = content.split("```")[1].split("```")[0]
    return content.strip()


def _review_single_turn(
    trade_proposal: dict[str, Any],
    portfolio_context: str,
    market_context: dict[str, Any],
    cycle_id: str | None,
    peer_argument: str | None = None,
) -> dict[str, Any]:
    """Single-turn Gemini moderation (no research tools)."""
    settings = get_settings()

    if not check_budget(Provider.GOOGLE.value):
        logger.warning("Google budget exceeded, skipping Gemini moderation")
        return {"verdict": "SKIP", "reasoning": "Budget exceeded", "available": False}

    user_prompt = _build_user_prompt(trade_proposal, portfolio_context, market_context, peer_argument)

    try:
        client = genai.Client(api_key=settings.google_ai_api_key)
        response = client.models.generate_content(
            model=settings.moderator_2_model,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                max_output_tokens=2048,
                temperature=0.4,
            ),
        )
        cost_result = _log_gemini_cost(response, cycle_id, settings)

        content = _extract_json_from_text(response.text or "")
        result = _parse_json_with_repair(
            content,
            ticker=str(trade_proposal.get("ticker", "UNKNOWN")),
            cycle_id=cycle_id,
            moderator=settings.moderator_2_model,
        )
        result["moderator"] = settings.moderator_2_model
        result["available"] = True
        _attach_gemini_usage(result, response, cost_result)
        return result

    except json.JSONDecodeError as e:
        logger.error(f"Gemini returned invalid JSON: {e}")
        # Default to DISAGREE on parse failure — a garbage response should not
        # silently approve trades. (Audit fix H-5.)
        return {
            "verdict": "DISAGREE",
            "reasoning": f"Could not parse response (defaulting to DISAGREE for safety): {e}",
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


def _gemini_tool_declarations() -> list[types.Tool]:
    """Build Gemini function declarations for research tools."""
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name="web_search",
            description="General web search for news, analysis, or company info.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(type=types.Type.STRING, description="Search query"),
                    "ticker": types.Schema(type=types.Type.STRING, description="Ticker symbol"),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="news_search",
            description="Financial news search for recent events, earnings, upgrades.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "ticker": types.Schema(type=types.Type.STRING, description="Ticker symbol"),
                    "query": types.Schema(type=types.Type.STRING, description="News search query"),
                },
                required=["ticker", "query"],
            ),
        ),
        types.FunctionDeclaration(
            name="macro_search",
            description="Search macro-economic topics: Fed policy, rates, GDP, inflation.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(type=types.Type.STRING, description="Macro search query"),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="sector_search",
            description="Search sector/industry trends, peer performance, competitive dynamics.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "sector": types.Schema(type=types.Type.STRING, description="Sector or industry name"),
                    "query": types.Schema(type=types.Type.STRING, description="What to search for"),
                    "ticker": types.Schema(type=types.Type.STRING, description="Optional ticker for cache"),
                },
                required=["sector", "query"],
            ),
        ),
        types.FunctionDeclaration(
            name="sec_search",
            description="Search SEC filings (10-K, 10-Q, 8-K, proxy). Free and institutional-grade.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "ticker": types.Schema(type=types.Type.STRING, description="Ticker symbol"),
                    "doc_type": types.Schema(type=types.Type.STRING, description="Filing type: 10-K, 10-Q, 8-K, proxy, all"),
                },
                required=["ticker"],
            ),
        ),
    ])]


def _dispatch_tool_call(name: str, args: dict, ticker_hint: str, research_executor: Any) -> list[dict]:
    """Route a Gemini function call to the research executor."""
    t = args.get("ticker", ticker_hint) or "general"
    n = args.get("num_results", 5)

    if name == "web_search":
        return research_executor.web_search("risk", t, args.get("query", ""), n)
    elif name == "news_search":
        return research_executor.news_search("risk", t, args.get("query", ""), n)
    elif name == "sector_search":
        return research_executor.sector_search("risk", t, args.get("sector", ""), args.get("query", ""), n)
    elif name == "macro_search":
        return research_executor.macro_search("risk", args.get("query", ""), n)
    elif name == "sec_search":
        return research_executor.sec_search_tool("risk", t, args.get("doc_type", "10-K"), n or 3)
    else:
        return [{"error": f"Unknown tool: {name}"}]


def _review_with_tools(
    trade_proposal: dict[str, Any],
    portfolio_context: str,
    market_context: dict[str, Any],
    cycle_id: str | None,
    research_executor: Any,
    peer_argument: str | None = None,
) -> dict[str, Any]:
    """Gemini moderation with tool-use loop for risk research."""
    settings = get_settings()
    ticker = trade_proposal.get("ticker", "general")

    if not check_budget(Provider.GOOGLE.value):
        return {"verdict": "SKIP", "reasoning": "Budget exceeded", "available": False}

    user_prompt = _build_user_prompt(trade_proposal, portfolio_context, market_context, peer_argument)
    sys_prompt = SYSTEM_PROMPT + "\n\nYou may use research tools to check risk factors, macro headwinds, or SEC filings. Use sparingly (1-2 searches). When done, respond with JSON only."

    tools = _gemini_tool_declarations()
    max_iter = 4

    try:
        client = genai.Client(api_key=settings.google_ai_api_key)
        contents: list[Any] = [types.Content(parts=[types.Part.from_text(text=user_prompt)], role="user")]

        for _ in range(max_iter):
            if not check_budget(Provider.GOOGLE.value):
                break

            response = client.models.generate_content(
                model=settings.moderator_2_model,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=sys_prompt,
                    max_output_tokens=2048,
                    temperature=0.4,
                    tools=tools,
                ),
            )
            cost_result = _log_gemini_cost(response, cycle_id, settings)

            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content or not candidate.content.parts:
                break

            parts = candidate.content.parts
            func_calls = [p for p in parts if hasattr(p, "function_call") and p.function_call]
            text_parts = [p for p in parts if hasattr(p, "text") and p.text]

            if not func_calls:
                text = "".join(p.text for p in text_parts if p.text)
                content_str = _extract_json_from_text(text)
                result = _parse_json_with_repair(
                    content_str,
                    ticker=str(trade_proposal.get("ticker", "UNKNOWN")),
                    cycle_id=cycle_id,
                    moderator=settings.moderator_2_model,
                )
                result["moderator"] = settings.moderator_2_model
                result["available"] = True
                _attach_gemini_usage(result, response, cost_result)
                return result

            contents.append(candidate.content)

            tool_response_parts = []
            for fc_part in func_calls:
                fc = fc_part.function_call
                args = dict(fc.args) if fc.args else {}
                res = _dispatch_tool_call(fc.name, args, ticker, research_executor)
                tool_response_parts.append(
                    types.Part.from_function_response(
                        name=fc.name,
                        response={"results": json.dumps(res)[:8000] if res else "[]"},
                    )
                )

            contents.append(types.Content(parts=tool_response_parts, role="user"))

        return _review_single_turn(trade_proposal, portfolio_context, market_context, cycle_id, peer_argument=peer_argument)

    except Exception as e:
        logger.error(f"Gemini tool-use moderation failed: {e}")
        return _review_single_turn(trade_proposal, portfolio_context, market_context, cycle_id, peer_argument=peer_argument)


def _clamp_gemini_scores(result: dict[str, Any]) -> dict[str, Any]:
    """Clamp Gemini scores to valid [1, 10] range (audit fix C-4)."""
    for key in ("growth_score", "risk_score", "confidence_score"):
        val = result.get(key)
        if val is not None:
            try:
                clamped = max(1, min(10, int(val)))
                if clamped != val:
                    logger.warning(f"Clamped Gemini {key}: {val} -> {clamped}")
                result[key] = clamped
            except (TypeError, ValueError):
                result[key] = 5  # Safe default
    return result


def _normalize_gemini_result(
    result: Any,
    *,
    ticker: str = "UNKNOWN",
    cycle_id: str | None = None,
    moderator: str = "gemini",
) -> dict[str, Any]:
    """Make Gemini output easier to understand when scores and wording diverge."""
    if not isinstance(result, dict):
        logger.warning(
            "Gemini returned non-object JSON for %s in %s: type=%s",
            ticker,
            cycle_id or "manual",
            type(result).__name__,
        )
        result = {
            "verdict": "DISAGREE",
            "growth_score": 3,
            "risk_score": 7,
            "confidence_score": 1,
            "assessment": "Could not parse Gemini response (defaulting to DISAGREE for safety)",
            "high_risk_flag": False,
            "modifications": None,
        }

    result = dict(result)
    result = _clamp_gemini_scores(result)
    result["verdict"] = str(result.get("verdict", "")).upper()
    result["modifications"] = _normalize_modifications_payload(
        result.get("modifications"),
        moderator=moderator,
        ticker=ticker,
        cycle_id=cycle_id,
    )

    assessment = str(result.get("assessment") or result.get("reasoning") or "").strip()
    verdict = str(result.get("verdict", "")).upper()
    growth = result.get("growth_score")
    risk = result.get("risk_score")
    confidence = result.get("confidence_score")

    if verdict == "DISAGREE":
        clarifiers: list[str] = []
        if growth is not None and risk is not None and risk >= growth:
            clarifiers.append(f"risk is {risk}/10 versus growth at {growth}/10")
        if confidence is not None and confidence <= 3:
            clarifiers.append(f"confidence is only {confidence}/10")

        if clarifiers:
            note = "Despite the growth positives, " + " and ".join(clarifiers) + ", so the trade is not supported."
            if note not in assessment:
                assessment = f"{assessment} {note}".strip() if assessment else note

    result["assessment"] = assessment
    return result


def _parse_json_with_repair(
    text: str,
    *,
    ticker: str = "UNKNOWN",
    cycle_id: str | None = None,
    moderator: str = "gemini",
) -> dict[str, Any]:
    """Parse JSON with repair for common LLM output issues.

    Handles truncated strings, missing closing braces, trailing commas, etc.
    Raises json.JSONDecodeError if repair is not possible.
    """
    # First try normal parse
    try:
        return _normalize_gemini_result(
            json.loads(text),
            ticker=ticker,
            cycle_id=cycle_id,
            moderator=moderator,
        )
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
        return _normalize_gemini_result(
            result,
            ticker=ticker,
            cycle_id=cycle_id,
            moderator=moderator,
        )
    except json.JSONDecodeError:
        pass

    # Last resort: try to extract key fields with regex
    verdict_match = re.search(r'"verdict"\s*:\s*"(AGREE|DISAGREE|MODIFY)"', text)
    growth_match = re.search(r'"growth_score"\s*:\s*(\d+)', text)
    risk_match = re.search(r'"risk_score"\s*:\s*(\d+)', text)
    confidence_match = re.search(r'"confidence_score"\s*:\s*(\d+)', text)

    if verdict_match:
        logger.info("Gemini JSON extracted via regex fallback")
        # Clamp scores to [1, 10] (audit fix C-4)
        growth = max(1, min(10, int(growth_match.group(1)))) if growth_match else 5
        risk = max(1, min(10, int(risk_match.group(1)))) if risk_match else 5
        confidence = max(1, min(10, int(confidence_match.group(1)))) if confidence_match else 5
        return _normalize_gemini_result({
            "verdict": verdict_match.group(1),
            "growth_score": growth,
            "risk_score": risk,
            "confidence_score": confidence,
            "assessment": "Extracted from malformed response",
            "high_risk_flag": risk > growth,
            "modifications": None,
        }, ticker=ticker, cycle_id=cycle_id, moderator=moderator)

    # Nothing worked — return a safe default instead of raising.
    # Default to DISAGREE — unparseable output should not silently approve trades.
    # (Audit fix H-5.)
    logger.warning("Could not repair Gemini JSON output — returning DISAGREE default")
    return _normalize_gemini_result({
        "verdict": "DISAGREE",
        "growth_score": 3,
        "risk_score": 7,
        "confidence_score": 1,
        "assessment": "Could not parse Gemini response (defaulting to DISAGREE for safety)",
        "high_risk_flag": False,
        "modifications": None,
    }, ticker=ticker, cycle_id=cycle_id, moderator=moderator)
