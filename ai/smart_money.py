"""
ai/smart_money.py
Smart Money Tracking — detects institutional/whale activity.
Analyzes volume spikes, open interest changes, and funding rate anomalies.
"""
import asyncio
from typing import Dict, Optional, List
from dataclasses import dataclass
from loguru import logger
import httpx
import pandas as pd

from config.settings import settings
from data.klines import fetch_klines


@dataclass
class SmartMoneySignal:
    symbol: str
    volume_spike: bool         # Volume > 2x 20-period average
    volume_multiplier: float   # How many times above average
    oi_change_pct: float       # Open interest % change (last 4 candles)
    oi_trend: str              # rising | falling | stable
    funding_rate: float        # Current funding rate
    funding_sentiment: str     # longs_paying | shorts_paying | neutral
    liqmap_bias: str           # long_bias | short_bias | neutral
    score: float               # -1.0 to 1.0 (smart money directional bias)
    label: str                 # bullish | bearish | neutral

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "volume_spike": self.volume_spike,
            "volume_multiplier": round(self.volume_multiplier, 2),
            "oi_change_pct": round(self.oi_change_pct, 2),
            "oi_trend": self.oi_trend,
            "funding_rate": self.funding_rate,
            "funding_sentiment": self.funding_sentiment,
            "liqmap_bias": self.liqmap_bias,
            "score": round(self.score, 3),
            "label": self.label,
        }


class SmartMoneyTracker:
    """
    Detects smart money / whale activity by analyzing:
    1. Volume Spikes (>2x 20-bar average)
    2. Open Interest trends (rising price + rising OI = strong trend)
    3. Funding Rate direction (extreme positive = crowd long = bearish signal)
    4. Liquidation map bias from order book depth
    """

    FUTURES_BASE = "https://fapi.binance.com"

    def __init__(self):
        self.http = httpx.AsyncClient(base_url=self.FUTURES_BASE, timeout=15.0)

    async def get_open_interest_history(self, symbol: str, limit: int = 8) -> Optional[pd.DataFrame]:
        """Fetch open interest history for a symbol."""
        try:
            resp = await self.http.get(
                "/futures/data/openInterestHist",
                params={
                    "symbol": symbol,
                    "period": "15m",
                    "limit": limit,
                },
            )
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            df = pd.DataFrame(data)
            df["sumOpenInterest"] = df["sumOpenInterest"].astype(float)
            df["sumOpenInterestValue"] = df["sumOpenInterestValue"].astype(float)
            return df
        except Exception as e:
            logger.warning(f"OI history error [{symbol}]: {e}")
            return None

    async def get_funding_rate(self, symbol: str) -> float:
        """Get current funding rate for a symbol."""
        try:
            resp = await self.http.get(
                "/fapi/v1/premiumIndex",
                params={"symbol": symbol},
            )
            resp.raise_for_status()
            data = resp.json()
            return float(data.get("lastFundingRate", 0))
        except Exception as e:
            logger.warning(f"Funding rate error [{symbol}]: {e}")
            return 0.0

    async def analyze(self, symbol: str) -> SmartMoneySignal:
        """Full smart money analysis for a symbol."""

        # ── Volume Spike Analysis ──────────────────────────────────────
        df = fetch_klines(symbol, "15m", limit=25)
        vol_spike = False
        vol_multiplier = 1.0

        if not df.empty:
            current_vol = float(df["volume"].iloc[-1])
            avg_vol = float(df["volume"].rolling(20).mean().iloc[-1])
            vol_multiplier = current_vol / avg_vol if avg_vol > 0 else 1.0
            vol_spike = vol_multiplier >= 2.0

            if vol_spike:
                logger.info(f"🐋 Volume spike detected: {symbol} | {vol_multiplier:.1f}x avg")

        # ── Open Interest ──────────────────────────────────────────────
        oi_df = await self.get_open_interest_history(symbol)
        oi_change_pct = 0.0
        oi_trend = "stable"

        if oi_df is not None and len(oi_df) >= 2:
            oi_start = float(oi_df["sumOpenInterest"].iloc[0])
            oi_end = float(oi_df["sumOpenInterest"].iloc[-1])
            oi_change_pct = ((oi_end - oi_start) / oi_start * 100) if oi_start > 0 else 0.0

            if oi_change_pct > 2:
                oi_trend = "rising"
            elif oi_change_pct < -2:
                oi_trend = "falling"

        # ── Funding Rate ───────────────────────────────────────────────
        funding_rate = await self.get_funding_rate(symbol)
        funding_sentiment = "neutral"
        if funding_rate > 0.001:  # > 0.1%
            funding_sentiment = "longs_paying"  # Crowd is long → potential short signal
        elif funding_rate < -0.001:
            funding_sentiment = "shorts_paying"  # Crowd is short → potential long signal

        # ── Liquidation Map (simplified: funding rate extremes as proxy) ──
        liqmap_bias = "neutral"
        if abs(funding_rate) > 0.003:
            # Extreme funding → large liquidation potential on dominant side
            liqmap_bias = "short_bias" if funding_rate > 0 else "long_bias"

        # ── Scoring ────────────────────────────────────────────────────
        score = 0.0

        # Volume spike in direction of trend
        if vol_spike:
            score += 0.2 if oi_trend == "rising" else -0.1

        # OI rising with price = real buyers
        if oi_trend == "rising":
            score += 0.3
        elif oi_trend == "falling":
            score -= 0.2

        # Funding rate: extreme longs = contrarian bearish
        if funding_sentiment == "longs_paying":
            score -= 0.3  # Crowd too long → squeeze risk
        elif funding_sentiment == "shorts_paying":
            score += 0.3  # Crowd too short → squeeze up

        score = max(-1.0, min(1.0, score))
        label = "bullish" if score > 0.2 else "bearish" if score < -0.2 else "neutral"

        signal = SmartMoneySignal(
            symbol=symbol,
            volume_spike=vol_spike,
            volume_multiplier=vol_multiplier,
            oi_change_pct=oi_change_pct,
            oi_trend=oi_trend,
            funding_rate=funding_rate,
            funding_sentiment=funding_sentiment,
            liqmap_bias=liqmap_bias,
            score=score,
            label=label,
        )

        logger.debug(
            f"SmartMoney [{symbol}]: Vol×{vol_multiplier:.1f} | OI {oi_trend} "
            f"({oi_change_pct:+.1f}%) | FR {funding_rate:.4f} | {label.upper()}"
        )
        return signal

    async def analyze_all(self) -> Dict[str, SmartMoneySignal]:
        """Analyze all configured symbols concurrently."""
        tasks = [self.analyze(sym) for sym in settings.symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        output = {}
        for sym, result in zip(settings.symbols, results):
            if isinstance(result, SmartMoneySignal):
                output[sym] = result
            else:
                logger.error(f"SmartMoney analysis failed for {sym}: {result}")
        return output

    async def close(self):
        await self.http.aclose()


# Singleton
_tracker: Optional[SmartMoneyTracker] = None


def get_smart_money_tracker() -> SmartMoneyTracker:
    global _tracker
    if _tracker is None:
        _tracker = SmartMoneyTracker()
    return _tracker
