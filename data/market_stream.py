"""
data/market_stream.py
Real-time WebSocket market data streaming from Binance.
Multi-symbol concurrent streams: kline + mini-ticker.
"""
import asyncio
import json
from typing import Dict, Callable, Optional, Set
from loguru import logger
import websockets

from config.settings import settings


class MarketStream:
    """
    Connects to Binance Futures WebSocket streams for real-time data.
    Handles kline (candlestick) and mini-ticker price streams.
    Emits candle close events to registered callbacks.
    """

    FUTURES_WS_BASE = "wss://fstream.binance.com/stream"

    def __init__(self):
        self.symbols = [s.lower() for s in settings.symbols]
        self.timeframe = settings.signal_timeframe
        self._callbacks: Dict[str, list] = {
            "kline_close": [],
            "ticker": [],
        }
        self._latest_prices: Dict[str, float] = {}
        self._latest_candles: Dict[str, dict] = {}
        self._running = False
        self._ws = None

    # ── Subscriptions ──────────────────────────────────────────────────────────

    def on_kline_close(self, callback: Callable):
        """Register callback for closed candle events."""
        self._callbacks["kline_close"].append(callback)

    def on_ticker(self, callback: Callable):
        """Register callback for price tick events."""
        self._callbacks["ticker"].append(callback)

    def get_price(self, symbol: str) -> float:
        return self._latest_prices.get(symbol.upper(), 0.0)

    def get_latest_candle(self, symbol: str) -> Optional[dict]:
        return self._latest_candles.get(symbol.upper())

    # ── Stream Management ─────────────────────────────────────────────────────

    def _build_stream_url(self) -> str:
        """Build combined stream URL for all symbols."""
        streams = []
        for sym in self.symbols:
            streams.append(f"{sym}@kline_{self.timeframe}")
            streams.append(f"{sym}@miniTicker")
        stream_names = "/".join(streams)
        return f"{self.FUTURES_WS_BASE}?streams={stream_names}"

    async def _handle_message(self, raw: str):
        """Parse and dispatch incoming WebSocket messages."""
        try:
            msg = json.loads(raw)
            stream = msg.get("stream", "")
            data = msg.get("data", {})

            if "@kline_" in stream:
                await self._handle_kline(data)
            elif "@miniTicker" in stream:
                await self._handle_ticker(data)

        except json.JSONDecodeError:
            logger.warning(f"Invalid WS message: {raw[:100]}")
        except Exception as e:
            logger.error(f"Message handling error: {e}")

    async def _handle_kline(self, data: dict):
        """Process kline (candlestick) data."""
        k = data.get("k", {})
        symbol = k.get("s", "").upper()
        is_closed = k.get("x", False)

        candle = {
            "symbol": symbol,
            "open_time": k.get("t"),
            "close_time": k.get("T"),
            "open": float(k.get("o", 0)),
            "high": float(k.get("h", 0)),
            "low": float(k.get("l", 0)),
            "close": float(k.get("c", 0)),
            "volume": float(k.get("v", 0)),
            "trades": k.get("n", 0),
            "is_closed": is_closed,
        }

        self._latest_candles[symbol] = candle

        if is_closed:
            logger.debug(f"Candle closed: {symbol} | Close: {candle['close']:.4f}")
            for cb in self._callbacks["kline_close"]:
                try:
                    await cb(candle) if asyncio.iscoroutinefunction(cb) else cb(candle)
                except Exception as e:
                    logger.error(f"kline_close callback error: {e}")

    async def _handle_ticker(self, data: dict):
        """Process mini-ticker (real-time price) data."""
        symbol = data.get("s", "").upper()
        price = float(data.get("c", 0))
        self._latest_prices[symbol] = price

        for cb in self._callbacks["ticker"]:
            try:
                payload = {
                    "symbol": symbol,
                    "price": price,
                    "volume": float(data.get("v", 0)),
                    "quote_volume": float(data.get("q", 0)),
                    "high": float(data.get("h", 0)),
                    "low": float(data.get("l", 0)),
                    "price_change_pct": float(data.get("P", 0)),
                }
                await cb(payload) if asyncio.iscoroutinefunction(cb) else cb(payload)
            except Exception as e:
                logger.error(f"ticker callback error: {e}")

    async def start(self):
        """Start the WebSocket stream with auto-reconnect."""
        self._running = True
        url = self._build_stream_url()
        logger.info(f"Starting market stream: {len(self.symbols)} symbols @ {self.timeframe}")
        logger.debug(f"WS URL: {url}")

        while self._running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=20,
                    ping_timeout=10,
                    close_timeout=5,
                ) as ws:
                    self._ws = ws
                    logger.success("Market stream connected ✓")
                    async for message in ws:
                        await self._handle_message(message)

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WS connection closed: {e}. Reconnecting in 3s...")
                await asyncio.sleep(3)
            except Exception as e:
                logger.error(f"WS error: {e}. Reconnecting in 5s...")
                await asyncio.sleep(5)

        logger.info("Market stream stopped.")

    def stop(self):
        self._running = False
        if self._ws:
            asyncio.create_task(self._ws.close())


# Singleton
_stream: Optional[MarketStream] = None


def get_market_stream() -> MarketStream:
    global _stream
    if _stream is None:
        _stream = MarketStream()
    return _stream
