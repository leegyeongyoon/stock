"""Application settings using pydantic-settings."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql://localhost:5432/stock_trading"

    # Kiwoom API
    kiwoom_account: str = ""

    # Logging
    log_level: str = "INFO"

    # Trading Settings
    max_position_size: float = 0.1  # 10% per position
    max_daily_loss: float = 0.03  # 3% daily loss limit
    max_positions: int = 10  # Maximum concurrent positions

    # Backtest Settings
    backtest_start_date: str = "2022-01-01"
    backtest_end_date: str = "2025-01-31"
    initial_capital: int = 100_000_000  # 1억원

    # Data Collection
    data_start_date: str = "2022-01-01"

    # OpenAI API
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
