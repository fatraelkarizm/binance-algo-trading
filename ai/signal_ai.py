"""
ai/signal_ai.py
AI Signal Engine — Technical Analysis based trading signals.
Uses `ta` library (stable, Python 3.11 compatible): RSI, MACD, EMA, Bollinger Bands.
"""
import pandas as pd
import ta
from ta.momentum import RSIIndicator
from ta.trend import MACD, EMAIndicator
from ta.volatility import BollingerBands
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
    reason: str

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
    Multi-indicator confluence signal engine using `ta` library.

    Indicators:
    - RSI(14): <30 → LONG vote, >70 → SHORT vote
    - MACD(12,26,9): histogram crossover direction
    - EMA(20) + EMA(50): trend filter
    - Bollinger Bands(20,2): volatility + squeeze

    Scoring: each indicator votes LONG (+1) / SHORT (-1) / NEUTRAL (0).
    Confluence score ≥ 2.0 → LONG, ≤ -2.0 → SHORT, else HOLD.
    """

    def __init__(self):
        self.sl_pct = settings.default_stop_loss_pct
        self.tp_pct = settings.default_take_profit_pct

    def analyze(self, symbol: str, interval: str = None) -> Optional[TradingSignal]:
        """Analyze a symbol and produce a trading signal."""
        interval = interval or settings.signal_timeframe
        df = fetch_klines(symbol, interval, limit=200)

        if df.empty or len(df) < 60:
            logger.warning(f"Insufficient data for {symbol} [{interval}]")
            return None

        try:
            return self._compute_signal(df, symbol)
        except Exception as e:
            logger.error(f"Signal error [{symbol}]: {e}")
            return None

    def _compute_signal(self, df: pd.DataFrame, symbol: str) -> TradingSignal:
        close = df["close"]
        price_now = float(close.iloc[-1])

        # ── RSI(14) ────────────────────────────────────────────────────
        rsi_ind = RSIIndicator(close=close, window=14)
        rsi_series = rsi_ind.rsi()
        rsi = float(rsi_series.iloc[-1])

        rsi_vote = 0.0
        rsi_reason = "RSI neutral"
        if rsi < 30:
            rsi_vote = 1.0
            rsi_reason = f"RSI oversold ({rsi:.1f})"
        elif rsi < 40:
            rsi_vote = 0.5
            rsi_reason = f"RSI approaching oversold ({rsi:.1f})"
        elif rsi > 70:
            rsi_vote = -1.0
            rsi_reason = f"RSI overbought ({rsi:.1f})"
        elif rsi > 60:
            rsi_vote = -0.5
            rsi_reason = f"RSI approaching overbought ({rsi:.1f})"

        # ── MACD(12,26,9) ──────────────────────────────────────────────
        macd_ind = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
        macd_line = macd_ind.macd()
        macd_sig_line = macd_ind.macd_signal()
        macd_hist = macd_ind.macd_diff()

        m = float(macd_line.iloc[-1])
        s = float(macd_sig_line.iloc[-1])
        h = float(macd_hist.iloc[-1])
        h_prev = float(macd_hist.iloc[-2])

        macd_vote = 0.0
        macd_signal_str = "neutral"
        if m > s and h > 0:
            macd_vote = 1.5 if h > h_prev else 1.0
            macd_signal_str = "bullish"
        elif m < s and h < 0:
            macd_vote = -1.5 if h < h_prev else -1.0
            macd_signal_str = "bearish"

        # ── EMA(20) + EMA(50) ──────────────────────────────────────────
        ema20 = float(EMAIndicator(close=close, window=20).ema_indicator().iloc[-1])
        ema50 = float(EMAIndicator(close=close, window=50).ema_indicator().iloc[-1])

        ema_vote = 0.0
        ema_trend = "sideways"
        if ema20 > ema50 and price_now > ema20:
            ema_vote = 1.0
            ema_trend = "uptrend"
        elif ema20 < ema50 and price_now < ema20:
            ema_vote = -1.0
            ema_trend = "downtrend"

        # ── Bollinger Bands(20,2) ──────────────────────────────────────
        bb = BollingerBands(close=close, window=20, window_dev=2)
        bb_upper = float(bb.bollinger_hband().iloc[-1])
        bb_lower = float(bb.bollinger_lband().iloc[-1])
        bb_mid   = float(bb.bollinger_mavg().iloc[-1])
        bb_width = (bb_upper - bb_lower) / bb_mid if bb_mid > 0 else 0

        bb_vote = 0.0
        bb_position = "middle"
        if price_now <= bb_lower:
            bb_vote = 1.0
            bb_position = "lower"
        elif price_now >= bb_upper:
            bb_vote = -1.0
            bb_position = "upper"
        elif bb_width < 0.02:
            bb_position = "squeeze"

        # ── Volume spike ───────────────────────────────────────────────
        vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].rolling(20).mean().iloc[-1])
        vol_mult = vol / avg_vol if avg_vol > 0 else 1.0
        vol_vote = 0.5 if vol_mult >= 2.0 else 0.0

        # ── Confluence Score ───────────────────────────────────────────
        raw_score = rsi_vote + macd_vote + ema_vote + bb_vote + vol_vote
        max_score = 5.0
        confidence = (abs(raw_score) / max_score) * 100

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
            confidence = max(0, 50 - abs(raw_score) * 10)
            reason = f"Mixed signals (score={raw_score:.1f})"

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
        """Analyze all configured symbols."""
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
