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
    def cycle_hours(self) -> int:
        return self.trading["cycle_hours"]

    @property
    def cycle_times_utc(self) -> list[str]:
        return self.trading["cycle_times_utc"]

    @property
    def market_days(self) -> list[int]:
        return self.trading["market_days"]

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

    # --- Environment variables ---
    @staticmethod
    def get_env(key: str) -> str:
        """Get required environment variable."""
        val = os.getenv(key)
        if val is None:
            raise EnvironmentError(f"Missing required environment variable: {key}")
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


# Singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
