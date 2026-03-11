"""
bot/strategy.py
Strategy Engine — aggregates AI signals + sentiment + smart money
into final trading decisions with SL/TP and position sizing.
"""
import asyncio
from typing import Optional, Dict
from dataclasses import dataclass
from loguru import logger

from config.settings import settings
from ai.signal_ai import TradingSignal, get_signal_engine
from ai.sentiment import SymbolSentiment, get_sentiment_analyzer
from ai.smart_money import SmartMoneySignal, get_smart_money_tracker
from bot.risk import PositionSizeResult, get_risk_manager


@dataclass
class TradeDecision:
    """
    Final trade decision combining all signal sources.
    Passed to engine.py for order execution.
    """
    symbol: str
    action: str           # LONG | SHORT | HOLD
    entry: float
    stop_loss: float
    take_profit: float
    quantity: float
    notional_usdt: float
    leverage: int

    # Signal breakdown
    technical_signal: str  # LONG | SHORT | HOLD
    technical_confidence: float
    sentiment_label: str
    smart_money_label: str
    final_confidence: float

    # Metadata
    reason: str
    use_algo: bool         # True if notional >= ALGO_MIN_ORDER_USDT

    def to_dict(self):
        return {
            "symbol": self.symbol,
            "action": self.action,
            "entry": round(self.entry, 6),
            "stop_loss": round(self.stop_loss, 6),
            "take_profit": round(self.take_profit, 6),
            "quantity": round(self.quantity, 6),
            "notional_usdt": round(self.notional_usdt, 2),
            "leverage": self.leverage,
            "technical_signal": self.technical_signal,
            "technical_confidence": round(self.technical_confidence, 1),
            "sentiment_label": self.sentiment_label,
            "smart_money_label": self.smart_money_label,
            "final_confidence": round(self.final_confidence, 1),
            "reason": self.reason,
            "use_algo": self.use_algo,
        }


class StrategyEngine:
    """
    Aggregates 3 signal sources:
    1. Technical Analysis (RSI, MACD, EMA, BB) — weight: 50%
    2. News Sentiment — weight: 25%
    3. Smart Money (OI, Volume, Funding) — weight: 25%

    Decision flow:
    - Compute weighted score
    - If score strong enough → run risk checks → size position → emit decision
    - Minimum threshold: 60% combined confidence to trade
    """

    CONFIDENCE_THRESHOLD = 60.0

    def __init__(self):
        self.signal_engine = get_signal_engine()
        self.sentiment = get_sentiment_analyzer()
        self.smart_money = get_smart_money_tracker()
        self.risk = get_risk_manager()

    async def decide(self, symbol: str, account_balance: float) -> Optional[TradeDecision]:
        """
        Produce a single trade decision for a symbol.

        Args:
            symbol: e.g. 'BTCUSDT'
            account_balance: Current account balance in USDT

        Returns:
            TradeDecision or None if HOLD / risk check failed
        """
        logger.info(f"Analyzing {symbol}...")

        # ── 1. Technical Signal (50% weight) ──────────────────────────
        tech_signal: Optional[TradingSignal] = self.signal_engine.analyze(symbol)
        if not tech_signal:
            logger.warning(f"No technical signal for {symbol}")
            return None

        # ── 2. Sentiment (25% weight) ──────────────────────────────────
        sentiment: SymbolSentiment = await self.sentiment.get_symbol_sentiment(symbol)

        # ── 3. Smart Money (25% weight) ────────────────────────────────
        smart: SmartMoneySignal = await self.smart_money.analyze(symbol)

        # ── Weighted Scoring ───────────────────────────────────────────
        label_score = {"LONG": 1, "bullish": 1, "SHORT": -1, "bearish": -1, "HOLD": 0, "neutral": 0}

        tech_direction = label_score.get(tech_signal.action, 0)
        sent_direction = label_score.get(sentiment.label, 0)
        smart_direction = label_score.get(smart.label, 0)

        # Confidence-weighted
        tech_weighted = tech_direction * (tech_signal.confidence / 100) * 0.5
        sent_weighted = sent_direction * abs(sentiment.score) * 0.25
        smart_weighted = smart_direction * abs(smart.score) * 0.25

        raw_combined = tech_weighted + sent_weighted + smart_weighted
        final_confidence = abs(raw_combined) * 100  # 0-100

        # ── Decision ───────────────────────────────────────────────────
        if final_confidence < self.CONFIDENCE_THRESHOLD and tech_signal.action != "HOLD":
            # Mixed signals — downgrade to HOLD
            action = "HOLD"
            reason = (
                f"Mixed signals: tech={tech_signal.action}({tech_signal.confidence:.0f}%), "
                f"sentiment={sentiment.label}, smart={smart.label} → HOLD"
            )
        else:
            action = tech_signal.action  # Primary driver is technical

            # Confirm: if sentiment and smart money strongly disagree → HOLD
            if (
                action == "LONG"
                and sentiment.label == "bearish"
                and smart.label == "bearish"
            ):
                action = "HOLD"
                reason = "Technical LONG but both sentiment and smart money bearish → HOLD"
            elif (
                action == "SHORT"
                and sentiment.label == "bullish"
                and smart.label == "bullish"
            ):
                action = "HOLD"
                reason = "Technical SHORT but both sentiment and smart money bullish → HOLD"
            else:
                reason = (
                    f"{tech_signal.reason} | "
                    f"Sentiment: {sentiment.label} | "
                    f"SmartMoney: {smart.label}"
                )

        if action == "HOLD":
            logger.info(f"HOLD on {symbol}: {reason}")
            return None

        # ── Risk Checks ────────────────────────────────────────────────
        ok, reject_reason = self.risk.validate_order(
            symbol=symbol,
            action=action,
            entry_price=tech_signal.entry,
            stop_loss=tech_signal.stop_loss,
            account_balance=account_balance,
        )
        if not ok:
            logger.warning(f"Risk rejected {symbol}: {reject_reason}")
            return None

        # ── Position Sizing ────────────────────────────────────────────
        size: PositionSizeResult = self.risk.calculate_position_size(
            symbol=symbol,
            action=action,
            entry_price=tech_signal.entry,
            stop_loss=tech_signal.stop_loss,
            take_profit=tech_signal.take_profit,
            account_balance=account_balance,
        )
        if not size.allowed:
            logger.warning(f"Position size rejected {symbol}: {size.reject_reason}")
            return None

        # ── Build Decision ─────────────────────────────────────────────
        use_algo = size.notional_usdt >= settings.algo_min_order_usdt

        decision = TradeDecision(
            symbol=symbol,
            action=action,
            entry=tech_signal.entry,
            stop_loss=tech_signal.stop_loss,
            take_profit=tech_signal.take_profit,
            quantity=size.quantity,
            notional_usdt=size.notional_usdt,
            leverage=size.leverage,
            technical_signal=tech_signal.action,
            technical_confidence=tech_signal.confidence,
            sentiment_label=sentiment.label,
            smart_money_label=smart.label,
            final_confidence=final_confidence,
            reason=reason,
            use_algo=use_algo,
        )

        logger.success(
            f"✅ Decision: {action} {symbol} | "
            f"Conf: {final_confidence:.0f}% | "
            f"Qty: {size.quantity:.4f} | "
            f"{'ALGO' if use_algo else 'MARKET'}"
        )
        return decision

    async def decide_all(self, account_balance: float) -> Dict[str, TradeDecision]:
        """Analyze all symbols and return viable trade decisions."""
        decisions = {}
        tasks = {sym: self.decide(sym, account_balance) for sym in settings.symbols}
        results = await asyncio.gather(*tasks.values(), return_exceptions=True)
        for sym, result in zip(tasks.keys(), results):
            if isinstance(result, TradeDecision):
                decisions[sym] = result
        return decisions


# Singleton
_strategy: Optional[StrategyEngine] = None


def get_strategy_engine() -> StrategyEngine:
    global _strategy
    if _strategy is None:
        _strategy = StrategyEngine()
    return _strategy
