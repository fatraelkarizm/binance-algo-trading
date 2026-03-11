"""
ai/signal_ai.py
AI Signal Engine — Technical Analysis based trading signals.
Uses RSI, MACD, EMA, Bollinger Bands for confluence-scored signals.
"""
import pandas as pd
import pandas_ta as ta
from typing import Optional, Dict, Any
from dataclasses import dataclass
from loguru import logger

from config.settings import settings
from data.klines import fetch_klines


@dataclass
class TradingSignal:
    """Output of the signal engine for a single symbol."""
    symbol: str
    action: str           # LONG | SHORT | HOLD
    entry: float
    stop_loss: float
    take_profit: float
    confidence: float     # 0–100
    rsi: float
    macd_signal: str      # bullish | bearish | neutral
    ema_trend: str        # uptrend | downtrend | sideways
    bb_position: str      # squeeze | upper | lower | middle
    reason: str           # human-readable reason

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "action": self.action,
            "entry": round(self.entry, 6),
            "stop_loss": round(self.stop_loss, 6),
            "take_profit": round(self.take_profit, 6),
            "confidence": round(self.confidence, 1),
            "rsi": round(self.rsi, 2),
            "macd_signal": self.macd_signal,
            "ema_trend": self.ema_trend,
            "bb_position": self.bb_position,
            "reason": self.reason,
        }


class SignalEngine:
    """
    Multi-indicator confluence signal engine.

    Indicators used:
    - RSI(14): Overbought/Oversold
    - MACD(12,26,9): Momentum crossover
    - EMA(20) + EMA(50): Trend direction
    - Bollinger Bands(20,2): Volatility + squeeze detection

    Scoring:
    Each indicator votes for LONG (+1), SHORT (-1), or NEUTRAL (0).
    Total score → confidence percentage → final signal.
    """

    def __init__(self):
        self.sl_pct = settings.default_stop_loss_pct
        self.tp_pct = settings.default_take_profit_pct

    def analyze(self, symbol: str, interval: str = None) -> Optional[TradingSignal]:
        """
        Analyze a symbol and produce a trading signal.

        Args:
            symbol: e.g. 'BTCUSDT'
            interval: Timeframe override (default: signal_timeframe from settings)

        Returns:
            TradingSignal or None on insufficient data
        """
        interval = interval or settings.signal_timeframe
        df = fetch_klines(symbol, interval, limit=200)

        if df.empty or len(df) < 60:
            logger.warning(f"Insufficient data for {symbol} [{interval}]")
            return None

        try:
            return self._compute_signal(df, symbol)
        except Exception as e:
            logger.error(f"Signal computation error [{symbol}]: {e}")
            return None

    def _compute_signal(self, df: pd.DataFrame, symbol: str) -> TradingSignal:
        """Compute multi-indicator confluence signal."""

        # ── RSI(14) ────────────────────────────────────────────────────
        df.ta.rsi(length=14, append=True)
        rsi = float(df["RSI_14"].iloc[-1])

        rsi_vote = 0
        rsi_reason = "RSI neutral"
        if rsi < 30:
            rsi_vote = 1
            rsi_reason = f"RSI oversold ({rsi:.1f})"
        elif rsi < 40:
            rsi_vote = 0.5
            rsi_reason = f"RSI approaching oversold ({rsi:.1f})"
        elif rsi > 70:
            rsi_vote = -1
            rsi_reason = f"RSI overbought ({rsi:.1f})"
        elif rsi > 60:
            rsi_vote = -0.5
            rsi_reason = f"RSI approaching overbought ({rsi:.1f})"

        # ── MACD(12,26,9) ──────────────────────────────────────────────
        df.ta.macd(fast=12, slow=26, signal=9, append=True)
        macd_col = "MACD_12_26_9"
        signal_col = "MACDs_12_26_9"
        hist_col = "MACDh_12_26_9"

        macd_val = float(df[macd_col].iloc[-1]) if macd_col in df else 0
        macd_sig = float(df[signal_col].iloc[-1]) if signal_col in df else 0
        macd_hist = float(df[hist_col].iloc[-1]) if hist_col in df else 0
        macd_hist_prev = float(df[hist_col].iloc[-2]) if hist_col in df else 0

        macd_vote = 0
        macd_signal_str = "neutral"
        if macd_val > macd_sig and macd_hist > 0:
            macd_vote = 1
            macd_signal_str = "bullish"
            if macd_hist > macd_hist_prev:
                macd_vote = 1.5  # Strengthening bullish
        elif macd_val < macd_sig and macd_hist < 0:
            macd_vote = -1
            macd_signal_str = "bearish"
            if macd_hist < macd_hist_prev:
                macd_vote = -1.5  # Strengthening bearish

        # ── EMA(20) + EMA(50) Trend ────────────────────────────────────
        df.ta.ema(length=20, append=True)
        df.ta.ema(length=50, append=True)

        ema20 = float(df["EMA_20"].iloc[-1]) if "EMA_20" in df else 0
        ema50 = float(df["EMA_50"].iloc[-1]) if "EMA_50" in df else 0
        price_now = float(df["close"].iloc[-1])

        ema_vote = 0
        ema_trend = "sideways"
        if ema20 > ema50 and price_now > ema20:
            ema_vote = 1
            ema_trend = "uptrend"
        elif ema20 < ema50 and price_now < ema20:
            ema_vote = -1
            ema_trend = "downtrend"

        # ── Bollinger Bands(20,2) ──────────────────────────────────────
        df.ta.bbands(length=20, std=2, append=True)
        bb_upper = float(df["BBU_20_2.0"].iloc[-1]) if "BBU_20_2.0" in df else price_now * 1.02
        bb_lower = float(df["BBL_20_2.0"].iloc[-1]) if "BBL_20_2.0" in df else price_now * 0.98
        bb_mid = float(df["BBM_20_2.0"].iloc[-1]) if "BBM_20_2.0" in df else price_now
        bb_width = (bb_upper - bb_lower) / bb_mid

        bb_vote = 0
        bb_position = "middle"
        if price_now <= bb_lower:
            bb_vote = 1
            bb_position = "lower"
        elif price_now >= bb_upper:
            bb_vote = -1
            bb_position = "upper"
        elif bb_width < 0.02:
            bb_position = "squeeze"

        # ── Volume Confirmation ────────────────────────────────────────
        vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].rolling(20).mean().iloc[-1])
        vol_multiplier = vol / avg_vol if avg_vol > 0 else 1.0
        vol_vote = 0.5 if vol_multiplier > 1.5 else 0

        # ── Confluence Score ───────────────────────────────────────────
        raw_score = rsi_vote + macd_vote + ema_vote + bb_vote + vol_vote
        # Max possible: 1 + 1.5 + 1 + 1 + 0.5 = 5.0
        # Min possible: -1 + -1.5 + -1 + -1 = -4.5
        max_score = 5.0

        # Normalize to -100..100 then map to 0..100 confidence
        normalized = raw_score / max_score  # -1 to 1
        confidence = abs(normalized) * 100

        # ── Decision ──────────────────────────────────────────────────
        if raw_score >= 2.0:
            action = "LONG"
            sl = price_now * (1 - self.sl_pct)
            tp = price_now * (1 + self.tp_pct)
            reason = f"{rsi_reason}; MACD {macd_signal_str}; {ema_trend}; BB {bb_position}"
        elif raw_score <= -2.0:
            action = "SHORT"
            sl = price_now * (1 + self.sl_pct)
            tp = price_now * (1 - self.tp_pct)
            reason = f"{rsi_reason}; MACD {macd_signal_str}; {ema_trend}; BB {bb_position}"
        else:
            action = "HOLD"
            sl = price_now * (1 - self.sl_pct)
            tp = price_now * (1 + self.tp_pct)
            reason = f"Mixed signals (score={raw_score:.1f})"
            confidence = max(0, 50 - abs(raw_score) * 10)

        signal = TradingSignal(
            symbol=symbol,
            action=action,
            entry=price_now,
            stop_loss=round(sl, 6),
            take_profit=round(tp, 6),
            confidence=round(confidence, 1),
            rsi=round(rsi, 2),
            macd_signal=macd_signal_str,
            ema_trend=ema_trend,
            bb_position=bb_position,
            reason=reason,
        )

        logger.info(
            f"Signal [{symbol}] → {action} | Conf: {confidence:.0f}% | "
            f"RSI: {rsi:.1f} | MACD: {macd_signal_str} | EMA: {ema_trend}"
        )
        return signal

    def analyze_all(self) -> Dict[str, TradingSignal]:
        """Analyze all configured symbols. Returns dict keyed by symbol."""
        signals = {}
        for sym in settings.symbols:
            sig = self.analyze(sym)
            if sig:
                signals[sym] = sig
        return signals


# Singleton
_engine: Optional[SignalEngine] = None


def get_signal_engine() -> SignalEngine:
    global _engine
    if _engine is None:
        _engine = SignalEngine()
    return _engine
