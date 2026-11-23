"""Environment-driven settings. Every secret comes from the environment, never from code."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(str(ROOT / ".env"), str(ROOT / "backend" / ".env")),
        extra="ignore",
    )

    app_name: str = "OneSeller AI"
    environment: str = "development"
    database_url: str = f"sqlite:///{ROOT / 'backend' / 'oneseller.db'}"
    jwt_secret: str = "dev-only-change-me-please-32-bytes-min"
    jwt_expire_minutes: int = 60 * 24 * 7
    cors_origins: str = "http://localhost:3000"
    public_base_url: str = "http://localhost:8000"

    # LLM
    llm_provider: str = "ollama"  # "ollama" | "anthropic" | "fake"
    ollama_model: str = "qwen3:4b-instruct-2507-q4_K_M"
    ollama_base_url: str = "http://localhost:11434"
    ollama_num_ctx: int = 8192
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-haiku-5-5"
    llm_max_output_tokens: int = 500
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2
    # Pricing in USD per 1M tokens (claude-haiku-5-5, <=100K prompt tier)
    anthropic_price_in_per_mtok: float = 0.10
    anthropic_price_out_per_mtok: float = 0.50
    # Hard spending guard for paid providers (USD, lifetime of the usage ledger)
    llm_budget_usd: float = 0.90
    llm_budget_reserve_usd: float = 0.01  # reserved per in-flight call

    # Agent
    agent_max_tool_steps: int = 5
    agent_history_messages: int = 12
    agent_prune_after_messages: int = 60
    agent_turn_timeout_seconds: float = 120.0
    max_chat_message_chars: int = 2000

    # Commerce
    currency: str = "PKR"
    trial_order_limit: int = 50
    standard_price: float = 2500
    standard_order_limit: int = 300
    premium_price: float = 6000
    premium_order_limit: int = 2000
    low_stock_threshold: int = 5
    public_api_orders_affect_inventory: bool = False
    allow_billing_simulation: bool = True
    max_image_bytes: int = 2 * 1024 * 1024

    # Rate limits (requests per minute)
    rate_limit_chat_per_minute: int = 30
    rate_limit_auth_per_minute: int = 20

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")


@lru_cache
def get_settings() -> Settings:
    return Settings()
