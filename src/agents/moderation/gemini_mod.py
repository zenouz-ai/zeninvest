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

logger = get_logger("gemini_moderator")

SYSTEM_PROMPT = """You are an independent risk assessor on an Investment Committee.
You receive the full data context: technical indicators, fundamentals, market conditions,
sub-strategy scores, analyst recommendations, and news sentiment.

Score each proposed trade on three dimensions using ALL available data:
- Growth potential: 1-10 (based on momentum scores, earnings growth, analyst consensus, news catalysts)
- Risk level: 1-10 (based on VIX, debt, P/E, conflicting signals, bearish news, regime)
- Confidence in thesis: 1-10 (based on signal agreement, data quality, news confirmation)

Scoring guidelines:
- RSI >70 or negative MACD histogram increases risk. RSI <30 with sound fundamentals increases growth.
- Debt/Equity >2.0, negative earnings, or P/E >40 raise risk by 2-3 points.
- VIX >25 adds 1-2 risk points. VIX >35 adds 3+ risk points.
- When sub-strategies disagree (momentum says BUY, factor says LOW), lower confidence by 2-3.
- Bullish news + positive analyst consensus increases confidence. Bearish news decreases it.
- Only flag high_risk_flag when risk exceeds growth potential by 3+ points.

IMPORTANT: Keep your assessment under 100 words. Respond with ONLY valid JSON:
{
  "verdict": "AGREE|DISAGREE|MODIFY",
  "growth_score": 7,
  "risk_score": 4,
  "confidence_score": 6,
  "assessment": "2-sentence independent assessment referencing specific data points",
  "high_risk_flag": false,
  "modifications": null
}"""


def review_trade(
    trade_proposal: dict[str, Any],
    portfolio_context: str,
    market_context: dict[str, Any],
    cycle_id: str | None = None,
    research_executor=None,
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
        return _review_with_tools(trade_proposal, portfolio_context, market_context, cycle_id, research_executor)
    return _review_single_turn(trade_proposal, portfolio_context, market_context, cycle_id)


def _build_user_prompt(trade_proposal: dict, portfolio_context: str, market_context: dict) -> str:
    context_text = format_market_context(market_context)
    return f"""Independently assess this proposed trade:

## Trade Proposal
{json.dumps(trade_proposal, indent=2)}

## Portfolio Context
{portfolio_context}

{context_text}

Score growth potential, risk level, and confidence using the data above.
Flag if risk > growth. Respond with JSON only."""


def _log_gemini_cost(response: Any, cycle_id: str | None, settings: Any) -> None:
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
) -> dict[str, Any]:
    """Single-turn Gemini moderation (no research tools)."""
    settings = get_settings()

    if not check_budget(Provider.GOOGLE.value):
        logger.warning("Google budget exceeded, skipping Gemini moderation")
        return {"verdict": "SKIP", "reasoning": "Budget exceeded", "available": False}

    user_prompt = _build_user_prompt(trade_proposal, portfolio_context, market_context)

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
        _log_gemini_cost(response, cycle_id, settings)

        content = _extract_json_from_text(response.text or "")
        result = _parse_json_with_repair(content)
        result["moderator"] = settings.moderator_2_model
        result["available"] = True
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
) -> dict[str, Any]:
    """Gemini moderation with tool-use loop for risk research."""
    settings = get_settings()
    ticker = trade_proposal.get("ticker", "general")

    if not check_budget(Provider.GOOGLE.value):
        return {"verdict": "SKIP", "reasoning": "Budget exceeded", "available": False}

    user_prompt = _build_user_prompt(trade_proposal, portfolio_context, market_context)
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
            _log_gemini_cost(response, cycle_id, settings)

            candidate = response.candidates[0] if response.candidates else None
            if not candidate or not candidate.content or not candidate.content.parts:
                break

            parts = candidate.content.parts
            func_calls = [p for p in parts if hasattr(p, "function_call") and p.function_call]
            text_parts = [p for p in parts if hasattr(p, "text") and p.text]

            if not func_calls:
                text = "".join(p.text for p in text_parts if p.text)
                content_str = _extract_json_from_text(text)
                result = _parse_json_with_repair(content_str)
                result["moderator"] = settings.moderator_2_model
                result["available"] = True
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

        return _review_single_turn(trade_proposal, portfolio_context, market_context, cycle_id)

    except Exception as e:
        logger.error(f"Gemini tool-use moderation failed: {e}")
        return _review_single_turn(trade_proposal, portfolio_context, market_context, cycle_id)


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

    # Nothing worked — return a safe default instead of raising.
    # Default to DISAGREE — unparseable output should not silently approve trades.
    # (Audit fix H-5.)
    logger.warning("Could not repair Gemini JSON output — returning DISAGREE default")
    return {
        "verdict": "DISAGREE",
        "growth_score": 3,
        "risk_score": 7,
        "confidence_score": 1,
        "assessment": "Could not parse Gemini response (defaulting to DISAGREE for safety)",
        "high_risk_flag": False,
        "modifications": None,
    }
