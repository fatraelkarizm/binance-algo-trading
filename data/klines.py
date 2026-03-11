"""
data/klines.py
Fetch historical OHLCV candlestick data for indicator calculations.
Returns pandas DataFrame ready for ta/pandas-ta usage.
"""
import pandas as pd
from typing import Optional
from loguru import logger
from binance.client import Client
from binance.exceptions import BinanceAPIException

from config.settings import settings


# Binance interval map
INTERVAL_MAP = {
    "1m": Client.KLINE_INTERVAL_1MINUTE,
    "3m": Client.KLINE_INTERVAL_3MINUTE,
    "5m": Client.KLINE_INTERVAL_5MINUTE,
    "15m": Client.KLINE_INTERVAL_15MINUTE,
    "30m": Client.KLINE_INTERVAL_30MINUTE,
    "1h": Client.KLINE_INTERVAL_1HOUR,
    "4h": Client.KLINE_INTERVAL_4HOUR,
    "1d": Client.KLINE_INTERVAL_1DAY,
}

COLUMNS = ["open_time", "open", "high", "low", "close", "volume",
           "close_time", "quote_volume", "trades", "taker_buy_base",
           "taker_buy_quote", "ignore"]


def fetch_klines(
    symbol: str,
    interval: str = "15m",
    limit: int = 200,
    client: Optional[Client] = None,
) -> pd.DataFrame:
    """
    Fetch OHLCV candlestick data for a symbol.

    Args:
        symbol: Trading pair e.g. 'BTCUSDT'
        interval: Timeframe e.g. '15m', '1h', '4h'
        limit: Number of candles (max 1500)
        client: Optional existing Client instance

    Returns:
        DataFrame with columns: open, high, low, close, volume (float)
        Index: datetime64 (UTC)
    """
    if client is None:
        client = Client(
            api_key=settings.active_api_key,
            api_secret=settings.active_api_secret,
            testnet=settings.binance_testnet,
        )

    binance_interval = INTERVAL_MAP.get(interval)
    if not binance_interval:
        logger.error(f"Invalid interval: {interval}. Valid: {list(INTERVAL_MAP.keys())}")
        return pd.DataFrame()

    try:
        raw = client.futures_klines(
            symbol=symbol,
            interval=binance_interval,
            limit=limit,
        )

        df = pd.DataFrame(raw, columns=COLUMNS)

        # Convert types
        numeric_cols = ["open", "high", "low", "close", "volume",
                        "quote_volume", "taker_buy_base", "taker_buy_quote"]
        df[numeric_cols] = df[numeric_cols].astype(float)
        df["trades"] = df["trades"].astype(int)

        # Set datetime index
        df["datetime"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df.set_index("datetime", inplace=True)

        # Keep useful columns only
        df = df[["open", "high", "low", "close", "volume", "quote_volume",
                  "trades", "taker_buy_base", "open_time", "close_time"]]

        logger.debug(f"Fetched {len(df)} candles: {symbol} [{interval}]")
        return df

    except BinanceAPIException as e:
        logger.error(f"Kline fetch error {symbol}/{interval}: {e}")
        return pd.DataFrame()


def get_latest_candle(symbol: str, interval: str = "15m") -> Optional[dict]:
    """Get the most recent closed candle as a dict."""
    df = fetch_klines(symbol, interval, limit=2)
    if df.empty:
        return None
    row = df.iloc[-1]
    return {
        "symbol": symbol,
        "open": row["open"],
        "high": row["high"],
        "low": row["low"],
        "close": row["close"],
        "volume": row["volume"],
        "trades": row["trades"],
    }
