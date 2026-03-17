"""Configuration loader for the investment agent."""

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


# Load .env from project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


def load_settings(path: str | None = None) -> dict[str, Any]:
    """Load settings from YAML config file."""
    if path is None:
        path = str(_PROJECT_ROOT / "config" / "settings.yaml")
    with open(path) as f:
        return yaml.safe_load(f)


class Settings:
    """Typed access to configuration settings."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        if config is None:
            config = load_settings()
        self._config = config

    # --- Trading ---
    @property
    def trading(self) -> dict[str, Any]:
        return self._config["trading"]

    @property
    def t212_base_url(self) -> str:
        return self.trading["base_url"]

    @property
    def account_type(self) -> str:
        """practice = relaxed state machine (always ACTIVE); live = full CAUTIOUS/HALTED."""
        return self.trading.get("account_type", "practice")

    @property
    def is_practice_account(self) -> bool:
        """True when account_type is practice; state machine stays ACTIVE."""
        return self.account_type == "practice"

    @property
    def cycle_frequency(self) -> str:
        """standard = 2 cycles/day, intraday = 3 cycles/day during market hours."""
        return self.trading.get("cycle_frequency", "standard")

    @property
    def cycle_hours(self) -> int:
        if self.cycle_frequency == "standard":
            return 12
        return self.trading.get("cycle_hours", 4)

    @property
    def cycle_times_utc(self) -> list[str]:
        if self.cycle_frequency == "standard":
            return ["07:00", "19:00"]
        return self.trading.get("cycle_times_utc", ["08:00", "12:00", "16:00"])

    @property
    def market_days(self) -> list[int]:
        return self.trading["market_days"]

    @property
    def skip_market_holidays(self) -> bool:
        """Skip analysis cycles on NYSE holidays (default: True)."""
        return bool(self.trading.get("skip_market_holidays", True))

    @property
    def max_positions(self) -> int:
        return self.trading["max_positions"]

    @property
    def min_position_pct(self) -> float:
        return float(self.trading["min_position_pct"])

    @property
    def max_position_pct(self) -> float:
        return float(self.trading["max_position_pct"])

    @property
    def cash_floor_pct(self) -> float:
        return float(self.trading["cash_floor_pct"])

    @property
    def benchmark_ticker(self) -> str:
        return self.trading["benchmark_ticker"]

    @property
    def min_order_value_gbp(self) -> float:
        """Minimum order value floor; full market SELLs are exempt."""
        return float(self.trading.get("min_order_value_gbp", 500))

    @property
    def min_reduce_pct_of_position(self) -> float:
        """Skip REDUCE when reduction is below this % of position."""
        return float(self.trading.get("min_reduce_pct_of_position", 25))

    @property
    def reduce_tiers_pct(self) -> list[float]:
        """Round REDUCE to nearest tier (25, 50, 70, 100)."""
        val = self.trading.get("reduce_tiers_pct", [25, 50, 70, 100])
        return [float(x) for x in val] if isinstance(val, list) else [25.0, 50.0, 70.0, 100.0]

    # --- Risk ---
    @property
    def risk(self) -> dict[str, Any]:
        return self._config["risk"]

    @property
    def max_single_stock_pct(self) -> float:
        return float(self.risk["max_single_stock_pct"])

    @property
    def max_sector_pct(self) -> float:
        return float(self.risk["max_sector_pct"])

    @property
    def max_correlation(self) -> float:
        return float(self.risk["max_correlation"])

    @property
    def cautious_drawdown_pct(self) -> float:
        return float(self.risk["cautious_drawdown_pct"])

    @property
    def halt_drawdown_pct(self) -> float:
        return float(self.risk["halt_drawdown_pct"])

    @property
    def daily_loss_halt_pct(self) -> float:
        return float(self.risk["daily_loss_halt_pct"])

    @property
    def vix_high(self) -> float:
        return float(self.risk["vix_high"])

    @property
    def vix_extreme(self) -> float:
        return float(self.risk["vix_extreme"])

    @property
    def min_positions(self) -> int:
        return int(self.risk.get("min_positions", 5))

    @property
    def min_holding_hours_before_reduce(self) -> int:
        """Block REDUCE/SELL on positions held less than this many hours unless risk limit exceeded."""
        return int(self.risk.get("min_holding_hours_before_reduce", 24))

    # --- Strategy ---
    @property
    def strategy(self) -> dict[str, Any]:
        return self._config["strategy"]

    @property
    def momentum_weight(self) -> float:
        return float(self.strategy["momentum_weight"])

    @property
    def mean_reversion_weight(self) -> float:
        return float(self.strategy["mean_reversion_weight"])

    @property
    def factor_weight(self) -> float:
        return float(self.strategy["factor_weight"])

    @property
    def min_conviction(self) -> int:
        return int(self.strategy["min_conviction"])

    @property
    def min_conviction_no_moderators(self) -> int:
        return int(self.strategy["min_conviction_no_moderators"])

    @property
    def min_conviction_one_moderator(self) -> int:
        return int(self.strategy["min_conviction_one_moderator"])

    # --- Moderation ---
    @property
    def moderation(self) -> dict[str, Any]:
        return self._config["moderation"]

    # --- Models ---
    @property
    def models(self) -> dict[str, str]:
        return self._config["models"]

    @property
    def strategy_model(self) -> str:
        return self.models["strategy"]

    @property
    def moderator_1_model(self) -> str:
        return self.models["moderator_1"]

    @property
    def moderator_2_model(self) -> str:
        return self.models["moderator_2"]

    # --- Data Providers ---
    @property
    def data_providers(self) -> dict[str, str]:
        return self._config["data_providers"]

    @property
    def finnhub_base_url(self) -> str:
        return self.data_providers["finnhub_base_url"]

    @property
    def alpha_vantage_base_url(self) -> str:
        return self.data_providers["alpha_vantage_base_url"]

    @property
    def macro_intelligence_enabled(self) -> bool:
        """Whether to fetch sector performance and economic headlines for committee context."""
        return bool(self.data_providers.get("macro_intelligence_enabled", True))

    def cache_ttl_hours(self, data_type: str) -> int:
        """Cache TTL in hours for a data type (ohlcv_indicators, fundamentals, etc.)."""
        defaults = {
            "ohlcv_indicators": 4,
            "fundamentals": 12,
            "finnhub_analyst": 6,
            "alpha_vantage_broad": 4,
            "alpha_vantage_ticker": 4,
            "macro_intelligence": 4,
            "lite_analysis": 4,
            "full_analysis": 4,
        }
        ttls = self.data_providers.get("cache_ttl_hours", {})
        return ttls.get(data_type, defaults.get(data_type, 4))

    # --- Universe Screening ---
    @property
    def universe(self) -> dict[str, Any]:
        return self._config.get("universe", {})

    @property
    def max_candidates(self) -> int:
        return int(self.universe.get("max_candidates", 30))

    @property
    def candidates_per_sector(self) -> int:
        return int(self.universe.get("candidates_per_sector", 3))

    @property
    def large_cap_pct(self) -> float:
        return float(self.universe.get("large_cap_pct", 0.40))

    @property
    def mid_cap_pct(self) -> float:
        return float(self.universe.get("mid_cap_pct", 0.35))

    @property
    def small_cap_pct(self) -> float:
        return float(self.universe.get("small_cap_pct", 0.25))

    @property
    def large_cap_min(self) -> float:
        return float(self.universe.get("large_cap_min", 10_000_000_000))

    @property
    def mid_cap_min(self) -> float:
        return float(self.universe.get("mid_cap_min", 2_000_000_000))

    @property
    def small_cap_min(self) -> float:
        return float(self.universe.get("small_cap_min", 300_000_000))

    @property
    def screening_cooldown_hours(self) -> int:
        return int(self.universe.get("screening_cooldown_hours", 72))

    @property
    def effective_screening_cooldown_hours(self) -> int:
        """Screening cooldown in hours. If effective_screening_cooldown_override is set, use it.
        Otherwise: for intraday, cap at cycle_hours so each cycle gets fresh pool.
        With 3 cycles at 08/12/16, 4h cooldown ensures cycle 2 and 3 see instruments from cycle 1 as eligible."""
        override = self.universe.get("effective_screening_cooldown_override")
        if override is not None:
            return int(override)
        base = self.screening_cooldown_hours
        if self.cycle_frequency == "intraday":
            return min(base, self.cycle_hours)
        return base

    @property
    def review_window_hours(self) -> list[int]:
        """Review = investigated in this window [min_h, max_h]. E.g. [24, 48] = 24-48h ago."""
        val = self.universe.get("review_window_hours", [24, 48])
        if isinstance(val, list) and len(val) >= 2:
            return [int(val[0]), int(val[1])]
        return [24, 48]

    @property
    def data_fallback_web_search_enabled(self) -> bool:
        """Use Brave/Tavily when Finnhub/Alpha Vantage fail for analyst/news."""
        return bool(self.universe.get("data_fallback_web_search_enabled", False))

    @property
    def uninvestigated_target_pct(self) -> float:
        """Share of per-cycle candidates from "new" pool (never investigated or >48h ago). Maps to new_share."""
        return float(self.universe.get("uninvestigated_target_pct", 0.5))

    @property
    def batch_enrichment_enabled(self) -> bool:
        """Whether the batch enrichment scheduler job is enabled."""
        return bool(self.universe.get("batch_enrichment_enabled", False))

    @property
    def batch_enrichment_per_run(self) -> int:
        """Max instruments to enrich per batch enrichment run."""
        return int(self.universe.get("batch_enrichment_per_run", 50))

    # --- Opportunity Scoring / Optimizer ---
    @property
    def opportunity(self) -> dict[str, Any]:
        return self._config.get("opportunity", {})

    @property
    def opportunity_enabled(self) -> bool:
        return bool(self.opportunity.get("enabled", False))

    @property
    def opportunity_mode(self) -> str:
        return str(self.opportunity.get("mode", "shadow"))

    @property
    def opportunity_immediate_threshold_z(self) -> float:
        return float(self.opportunity.get("immediate_threshold_z", 1.0))

    @property
    def opportunity_queue_threshold_z(self) -> float:
        return float(self.opportunity.get("queue_threshold_z", 0.2))

    @property
    def opportunity_queue_ttl_cycles(self) -> int:
        return int(self.opportunity.get("queue_ttl_cycles", 3))

    @property
    def opportunity_swap_delta_z(self) -> float:
        return float(self.opportunity.get("swap_delta_z", 1.0))

    @property
    def opportunity_ewma_half_life_cycles(self) -> float:
        return float(self.opportunity.get("ewma_half_life_cycles", 6))

    @property
    def opportunity_weights(self) -> dict[str, float]:
        defaults = {
            "momentum": 0.12,
            "mean_reversion": 0.10,
            "factor_composite": 0.20,
            "factor_quality": 0.08,
            "factor_value": 0.05,
            "conviction": 0.15,
            "expected_holding_period": 0.05,
            "gpt_verdict": 0.05,
            "gemini_growth_vs_risk": 0.08,
            "gemini_confidence": 0.04,
            "news_sentiment": 0.05,
            "market_cap": 0.03,
        }
        config_weights = self.opportunity.get("weights", {})
        return {k: float(config_weights.get(k, v)) for k, v in defaults.items()}

    @property
    def opportunity_penalties(self) -> dict[str, float]:
        defaults = {
            "strategy_hold": -0.8,
            "strategy_queued": -0.6,
            "moderation_blocked": -1.2,
            "risk_reject": -1.6,
            "risk_resize": -0.35,
            "unrated": -0.6,
        }
        config_penalties = self.opportunity.get("penalties", {})
        return {k: float(config_penalties.get(k, v)) for k, v in defaults.items()}

    # --- Cost Limits ---
    @property
    def cost_limits(self) -> dict[str, Any]:
        return self._config["cost_limits"]

    @property
    def anthropic_daily_gbp(self) -> float:
        return float(self.cost_limits["anthropic_daily_gbp"])

    @property
    def openai_daily_gbp(self) -> float:
        return float(self.cost_limits["openai_daily_gbp"])

    @property
    def google_daily_gbp(self) -> float:
        return float(self.cost_limits["google_daily_gbp"])

    @property
    def total_monthly_gbp(self) -> float:
        return float(self.cost_limits["total_monthly_gbp"])

    @property
    def alert_threshold_pct(self) -> float:
        return float(self.cost_limits["alert_threshold_pct"])

    # --- Search API Limits (Brave, Tavily — monthly call budgets) ---
    @property
    def search_api_limits(self) -> dict[str, Any]:
        return self._config.get("search_api_limits", {})

    @property
    def brave_search_monthly_calls(self) -> int:
        return int(self.search_api_limits.get("brave_search_monthly_calls", 2000))

    @property
    def brave_answer_monthly_calls(self) -> int:
        return int(self.search_api_limits.get("brave_answer_monthly_calls", 2000))

    @property
    def tavily_monthly_calls(self) -> int:
        return int(self.search_api_limits.get("tavily_monthly_calls", 1000))

    # --- Research (Agentic Research US-4.4) ---
    @property
    def research(self) -> dict[str, Any]:
        return self._config.get("research", {})

    @property
    def research_enabled(self) -> bool:
        return bool(self.research.get("enabled", False))

    @property
    def strategy_research_enabled(self) -> bool:
        return bool(self.research.get("strategy_research_enabled", False))

    @property
    def skeptic_research_enabled(self) -> bool:
        return bool(self.research.get("skeptic_research_enabled", False))

    @property
    def risk_research_enabled(self) -> bool:
        return bool(self.research.get("risk_research_enabled", False))

    @property
    def research_max_calls_per_member_per_cycle(self) -> dict[str, int]:
        caps = self.research.get("max_calls_per_member_per_cycle") or {}
        return {
            "strategy": int(caps.get("strategy", 20)),
            "skeptic": int(caps.get("skeptic", 8)),
            "risk": int(caps.get("risk", 7)),
        }

    @property
    def research_max_total_calls_per_cycle(self) -> int:
        return int(self.research.get("max_total_research_calls_per_cycle", 35))

    # --- Order Management ---
    @property
    def order_management(self) -> dict[str, Any]:
        return self._config.get("order_management", {})

    @property
    def order_management_enabled(self) -> bool:
        return bool(self.order_management.get("enabled", False))

    @property
    def default_stop_loss_pct(self) -> float:
        """Default stop-loss % when placing missing stops (no ATR or no decision)."""
        return float(self.order_management.get("default_stop_loss_pct", -8.0))

    @property
    def reassess_stops_enabled(self) -> bool:
        return bool(self.order_management.get("reassess_stops", False))

    @property
    def trailing_stops_enabled(self) -> bool:
        ts = self.order_management.get("trailing_stops", {})
        return bool(ts.get("enabled", False)) if isinstance(ts, dict) else False

    @property
    def trailing_stop_default_trail_pct(self) -> float:
        ts = self.order_management.get("trailing_stops", {})
        return float(ts.get("default_trail_pct", 5.0)) if isinstance(ts, dict) else 5.0

    @property
    def limit_orders_enabled(self) -> bool:
        lo = self.order_management.get("limit_orders", {})
        return bool(lo.get("enabled", False)) if isinstance(lo, dict) else False

    @property
    def limit_order_default_offset_pct(self) -> float:
        lo = self.order_management.get("limit_orders", {})
        return float(lo.get("default_offset_pct", 2.0)) if isinstance(lo, dict) else 2.0

    @property
    def limit_order_time_validity(self) -> str:
        lo = self.order_management.get("limit_orders", {})
        return str(lo.get("time_validity", "GTC")) if isinstance(lo, dict) else "GTC"

    @property
    def atr_multiplier(self) -> float:
        return float(self.order_management.get("atr_multiplier", 2.0))

    @property
    def min_stop_distance_pct(self) -> float:
        return float(self.order_management.get("min_stop_distance_pct", 3.0))

    @property
    def max_stop_distance_pct(self) -> float:
        return float(self.order_management.get("max_stop_distance_pct", 15.0))

    @property
    def only_tighten_stops(self) -> bool:
        return bool(self.order_management.get("only_tighten_stops", True))

    # --- Notifications ---
    @property
    def notifications(self) -> dict[str, Any]:
        return self._config.get("notifications", {})

    @property
    def notification_enabled(self) -> bool:
        return bool(self.notifications.get("enabled", False))

    @property
    def notification_channels(self) -> list[str]:
        channels = self.notifications.get("channels", [])
        if not isinstance(channels, list):
            return []
        return [str(c).lower() for c in channels]

    @property
    def notification_routes(self) -> dict[str, list[str]]:
        routes = self.notifications.get("routes", {})
        if not isinstance(routes, dict):
            return {}
        normalized: dict[str, list[str]] = {}
        for event_type, channels in routes.items():
            if isinstance(channels, list):
                normalized[str(event_type)] = [str(c).lower() for c in channels]
        return normalized

    @property
    def notification_timeout_seconds(self) -> float:
        return float(self.notifications.get("timeout_seconds", 5))

    @property
    def notification_max_retries(self) -> int:
        return int(self.notifications.get("max_retries", 2))

    @property
    def notification_dedup_window_seconds(self) -> int:
        return int(self.notifications.get("dedup_window_seconds", 300))

    @property
    def notification_include_dry_run_alerts(self) -> bool:
        return bool(self.notifications.get("include_dry_run_alerts", True))

    @property
    def notification_command_gateway_enabled(self) -> bool:
        command_gateway = self.notifications.get("command_gateway", {})
        if not isinstance(command_gateway, dict):
            return False
        return bool(command_gateway.get("enabled", False))

    # --- Environment variables ---
    @staticmethod
    def get_env(key: str) -> str:
        """Get required environment variable."""
        val = os.getenv(key)
        if val is None:
            raise EnvironmentError(f"Missing required environment variable: {key}")
        return val

    @staticmethod
    def get_env_optional(key: str, default: str | None = None) -> str | None:
        """Get optional environment variable."""
        val = os.getenv(key)
        if val is None or val == "":
            return default
        return val

    @property
    def t212_api_key(self) -> str:
        return self.get_env("T212_API_KEY")

    @property
    def t212_api_secret(self) -> str:
        return self.get_env("T212_API_SECRET")

    @property
    def anthropic_api_key(self) -> str:
        return self.get_env("ANTHROPIC_API_KEY")

    @property
    def openai_api_key(self) -> str:
        return self.get_env("OPENAI_API_KEY")

    @property
    def google_ai_api_key(self) -> str:
        return self.get_env("GOOGLE_AI_API_KEY")

    @property
    def finnhub_api_key(self) -> str:
        return self.get_env("FINNHUB_API_KEY")

    @property
    def alpha_vantage_api_key(self) -> str:
        return self.get_env("ALPHA_VANTAGE_API_KEY")

    @property
    def slack_webhook_url(self) -> str | None:
        return self.get_env_optional("SLACK_WEBHOOK_URL")

    @property
    def alert_email_from(self) -> str | None:
        return self.get_env_optional("ALERT_EMAIL_FROM")

    @property
    def alert_email_to(self) -> str | None:
        return self.get_env_optional("ALERT_EMAIL_TO")

    @property
    def smtp_host(self) -> str | None:
        return self.get_env_optional("SMTP_HOST")

    @property
    def smtp_port(self) -> int:
        raw = self.get_env_optional("SMTP_PORT", "587")
        return int(raw) if raw is not None else 587

    @property
    def smtp_user(self) -> str | None:
        return self.get_env_optional("SMTP_USER")

    @property
    def smtp_pass(self) -> str | None:
        return self.get_env_optional("SMTP_PASS")

    @property
    def smtp_use_tls(self) -> bool:
        raw = (self.get_env_optional("SMTP_USE_TLS", "true") or "true").strip().lower()
        return raw in {"1", "true", "yes", "y", "on"}

    # --- Dashboard ---
    @property
    def dashboard(self) -> dict[str, Any]:
        return self._config.get("dashboard", {})

    @property
    def dashboard_enabled(self) -> bool:
        return bool(self.dashboard.get("enabled", True))

    @property
    def dashboard_events_enabled(self) -> bool:
        return bool(self.dashboard.get("events_enabled", True))

    @property
    def dashboard_cors_origins(self) -> list[str] | None:
        origins = self.dashboard.get("cors_origins")
        if isinstance(origins, list) and origins:
            return origins
        return None


# Singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
