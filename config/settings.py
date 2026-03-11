"""
config/settings.py
Central configuration for the Binance Futures Trading Bot.
All values loaded from .env file via pydantic-settings.
"""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List
from functools import lru_cache


class Settings(BaseSettings):
    # ── Binance API ────────────────────────────────────────────
    binance_api_key: str = Field("", env="BINANCE_API_KEY")
    binance_api_secret: str = Field("", env="BINANCE_API_SECRET")
    binance_testnet: bool = Field(True, env="BINANCE_TESTNET")
    binance_testnet_api_key: str = Field("", env="BINANCE_TESTNET_API_KEY")
    binance_testnet_api_secret: str = Field("", env="BINANCE_TESTNET_API_SECRET")

    # ── Trading ────────────────────────────────────────────────
    dry_run: bool = Field(True, env="DRY_RUN")
    trading_symbols: str = Field("BTCUSDT,ETHUSDT,SOLUSDT", env="TRADING_SYMBOLS")
    default_leverage: int = Field(5, env="DEFAULT_LEVERAGE")
    signal_timeframe: str = Field("15m", env="SIGNAL_TIMEFRAME")

    # ── Risk ───────────────────────────────────────────────────
    max_risk_per_trade: float = Field(0.01, env="MAX_RISK_PER_TRADE")
    max_open_positions: int = Field(3, env="MAX_OPEN_POSITIONS")
    max_daily_loss: float = Field(0.05, env="MAX_DAILY_LOSS")
    default_stop_loss_pct: float = Field(0.02, env="DEFAULT_STOP_LOSS_PCT")
    default_take_profit_pct: float = Field(0.04, env="DEFAULT_TAKE_PROFIT_PCT")

    # ── Algo Orders ────────────────────────────────────────────
    algo_min_order_usdt: float = Field(10000.0, env="ALGO_MIN_ORDER_USDT")
    twap_default_duration: int = Field(3600, env="TWAP_DEFAULT_DURATION")
    vp_default_urgency: str = Field("MEDIUM", env="VP_DEFAULT_URGENCY")

    # ── News & Sentiment ───────────────────────────────────────
    cryptocompare_api_key: str = Field("", env="CRYPTOCOMPARE_API_KEY")
    openai_api_key: str = Field("", env="OPENAI_API_KEY")

    # ── Server ─────────────────────────────────────────────────
    api_host: str = Field("0.0.0.0", env="API_HOST")
    api_port: int = Field(8000, env="API_PORT")
    redis_url: str = Field("redis://localhost:6379", env="REDIS_URL")

    @property
    def symbols(self) -> List[str]:
        return [s.strip() for s in self.trading_symbols.split(",")]

    @property
    def active_api_key(self) -> str:
        return self.binance_testnet_api_key if self.binance_testnet else self.binance_api_key

    @property
    def active_api_secret(self) -> str:
        return self.binance_testnet_api_secret if self.binance_testnet else self.binance_api_secret

    @property
    def base_url(self) -> str:
        return "https://testnet.binancefuture.com" if self.binance_testnet else "https://fapi.binance.com"

    @property
    def algo_base_url(self) -> str:
        # Algo API always uses main URL
        return "https://api.binance.com"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
