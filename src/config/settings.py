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
    backtest_database_url: str = ""  # 비어있으면 database_url 사용

    # Kiwoom API (legacy)
    kiwoom_account: str = ""

    # KIS API (한국투자증권)
    kis_app_key: str = ""
    kis_app_secret: str = ""
    kis_account_no: str = ""           # 계좌번호 (8자리+2자리)
    kis_is_mock: bool = True           # True=모의투자, False=실전투자

    # Logging
    log_level: str = "INFO"

    # Trading Settings
    max_position_size: float = 0.40    # 40% per position (그리드서치 최적)
    max_daily_loss: float = 0.02       # 2% daily loss limit (3%에서 강화)
    max_positions: int = 3             # Maximum concurrent positions
    initial_capital: int = 5_000_000   # 500만원 (라이브 기본)

    # Backtest Settings
    backtest_start_date: str = "2022-01-01"
    backtest_end_date: str = "2025-01-31"
    backtest_initial_capital: int = 100_000_000  # 1억원

    # Data Collection
    data_start_date: str = "2022-01-01"

    # OpenAI API
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Telegram Alert
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()


settings = get_settings()
