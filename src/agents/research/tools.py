"""Research tool definitions for LLM tool-use (Anthropic/OpenAI formats)."""


def _to_openai_format(tools: list[dict]) -> list[dict]:
    """Convert Anthropic input_schema format to OpenAI function-calling format."""
    out = []
    for t in tools:
        out.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t.get("input_schema", t.get("parameters", {"type": "object", "properties": {}})),
            },
        })
    return out


def get_research_tools_openai() -> list[dict]:
    """Return tool definitions in OpenAI function-calling format."""
    return _to_openai_format(get_research_tool_definitions())


def get_research_tool_definitions() -> list[dict]:
    """Return tool definitions for Strategy and Moderation LLMs (Anthropic format)."""
    return [
        {
            "name": "web_search",
            "description": "General-purpose web search for news, analysis, company information. Use sparingly to verify thesis or find bear/bull cases.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "ticker": {"type": "string", "description": "Optional ticker for cache (e.g. AAPL) when search is ticker-specific"},
                    "num_results": {"type": "integer", "description": "Max results", "default": 5},
                },
                "required": ["query"],
            },
        },
        {
            "name": "news_search",
            "description": "Financial news search (earnings, upgrades, insider activity). Use for recent news on a specific ticker.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker symbol (e.g. AAPL)"},
                    "query": {"type": "string", "description": "News search query (e.g. 'earnings Q4 2025')"},
                    "num_results": {"type": "integer", "description": "Max results", "default": 5},
                },
                "required": ["ticker", "query"],
            },
        },
        {
            "name": "sector_search",
            "description": "Search sector/industry trends, peer performance, competitive dynamics.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "sector": {"type": "string", "description": "Sector or industry name"},
                    "query": {"type": "string", "description": "What to search for"},
                    "ticker": {"type": "string", "description": "Optional ticker for cache"},
                    "num_results": {"type": "integer", "description": "Max results", "default": 5},
                },
                "required": ["sector", "query"],
            },
        },
        {
            "name": "sec_search",
            "description": "Search SEC filings (10-K, 10-Q, 8-K, proxy). Free, institutional-grade. Use to verify risk factors or filings.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Ticker symbol (e.g. AAPL)"},
                    "doc_type": {
                        "type": "string",
                        "description": "Filing type",
                        "enum": ["10-K", "10-Q", "8-K", "proxy", "all"],
                    },
                    "num_results": {"type": "integer", "description": "Max filings", "default": 3},
                },
                "required": ["ticker"],
            },
        },
        {
            "name": "macro_search",
            "description": "Search macro-economic topics: Fed policy, interest rates, GDP, inflation, employment. Use to assess macro backdrop for risk assessment.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Macro search query (e.g. 'Fed rate decision March 2026')"},
                    "num_results": {"type": "integer", "description": "Max results", "default": 5},
                },
                "required": ["query"],
            },
        },
    ]
