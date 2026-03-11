"""
bot/engine.py
Main Trading Engine — orchestrates the full trading loop.
Listens to market stream events, runs strategy, executes orders.
"""
import asyncio
import json
from datetime import datetime, timezone, date
from typing import Dict, List, Optional
from loguru import logger

from config.settings import settings
from data.market_stream import get_market_stream
from bot.strategy import get_strategy_engine, TradeDecision
from bot.risk import get_risk_manager
from exchange.binance_client import get_client
from exchange.algo_orders import get_algo_client


class TradingEngine:
    """
    Core trading loop.

    Flow per candle close:
    1. Get account balance + open positions
    2. Update risk state
    3. Run strategy → get decisions
    4. Execute approved orders (market or algo TWAP/VP)
    5. Place SL + TP orders
    6. Emit events to Redis / WebSocket
    """

    def __init__(self):
        self.stream = get_market_stream()
        self.strategy = get_strategy_engine()
        self.risk = get_risk_manager()
        self.client = get_client()
        self.algo = get_algo_client()

        self._is_running = False
        self._signal_history: List[dict] = []
        self._trade_history: List[dict] = []
        self._event_queue: asyncio.Queue = asyncio.Queue()

        # Subscribe to candle close events
        self.stream.on_kline_close(self._on_candle_close)
        logger.info("TradingEngine initialized")

    # ── Event Processing ────────────────────────────────────────────────────────

    async def _on_candle_close(self, candle: dict):
        """Called on every closed candle. Queues for async processing."""
        await self._event_queue.put(candle)

    async def _process_events(self):
        """Process candle close events from queue."""
        while self._is_running:
            try:
                candle = await asyncio.wait_for(self._event_queue.get(), timeout=1.0)
                await self._handle_candle(candle)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Event processing error: {e}")

    async def _handle_candle(self, candle: dict):
        """Main logic triggered on each candle close."""
        symbol = candle["symbol"]
        price = candle["close"]
        logger.debug(f"Processing candle: {symbol} @ {price:.4f}")

        # ── Get account state ──────────────────────────────────────────
        balance_info = self.client.get_account_balance()
        account_balance = balance_info["balance"]
        available_balance = balance_info["available"]

        # ── Update risk state ──────────────────────────────────────────
        positions = self.client.get_open_positions()
        self.risk.update_position_count(len(positions))

        # ── Can we trade? ──────────────────────────────────────────────
        can_trade, reason = self.risk.can_trade(symbol)
        if not can_trade:
            logger.warning(f"Trading blocked: {reason}")
            return

        # ── Run strategy ───────────────────────────────────────────────
        decision: Optional[TradeDecision] = await self.strategy.decide(
            symbol=symbol,
            account_balance=account_balance,
        )

        if decision is None:
            return  # HOLD or risk rejected

        # ── Check not already in this position ─────────────────────────
        existing = next((p for p in positions if p["symbol"] == symbol), None)
        if existing:
            logger.debug(f"Already in position: {symbol} → skip")
            return

        # ── Execute order ──────────────────────────────────────────────
        await self._execute_decision(decision, available_balance)

    async def _execute_decision(self, decision: TradeDecision, available: float):
        """Execute a trade decision with SL and TP."""
        symbol = decision.symbol
        action = decision.action
        side = "BUY" if action == "LONG" else "SELL"
        close_side = "SELL" if action == "LONG" else "BUY"
        qty = decision.quantity

        # ── Set leverage ────────────────────────────────────────────────
        self.client.set_leverage(symbol, decision.leverage)

        trade_record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
            "action": action,
            "entry": decision.entry,
            "stop_loss": decision.stop_loss,
            "take_profit": decision.take_profit,
            "quantity": qty,
            "notional_usdt": decision.notional_usdt,
            "leverage": decision.leverage,
            "confidence": decision.final_confidence,
            "use_algo": decision.use_algo,
            "reason": decision.reason,
            "status": "pending",
        }

        try:
            if decision.use_algo:
                # ── TWAP execution for large orders ──────────────────────
                order = self.algo.create_twap(
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                    duration=settings.twap_default_duration,
                    client_algo_id=f"BOT_{symbol}_{int(datetime.now().timestamp())}",
                )
                if order:
                    trade_record["status"] = "algo_submitted"
                    trade_record["algo_id"] = order.get("clientAlgoId")
                    logger.success(f"TWAP submitted: {symbol} | ID: {order.get('clientAlgoId')}")
            else:
                # ── Standard market order ─────────────────────────────────
                order = self.client.place_market_order(
                    symbol=symbol,
                    side=side,
                    quantity=qty,
                )
                if order:
                    trade_record["status"] = "filled"
                    trade_record["order_id"] = order.get("orderId")

                    # Place SL + TP after market fill
                    self.client.place_stop_loss(
                        symbol=symbol,
                        side=close_side,
                        quantity=qty,
                        stop_price=decision.stop_loss,
                    )
                    self.client.place_take_profit(
                        symbol=symbol,
                        side=close_side,
                        quantity=qty,
                        tp_price=decision.take_profit,
                    )
                    logger.success(f"Market order + SL/TP placed: {symbol}")

        except Exception as e:
            logger.error(f"Order execution error [{symbol}]: {e}")
            trade_record["status"] = "error"
            trade_record["error"] = str(e)

        self._trade_history.append(trade_record)
        if len(self._trade_history) > 500:
            self._trade_history = self._trade_history[-500:]

        # Emit to event queue for WebSocket broadcast
        await self._event_queue.put({"type": "trade", "data": trade_record})

    # ── Public Interface ────────────────────────────────────────────────────────

    def get_trade_history(self, limit: int = 50) -> List[dict]:
        return self._trade_history[-limit:]

    def get_signal_history(self, limit: int = 50) -> List[dict]:
        return self._signal_history[-limit:]

    async def start(self):
        """Start the trading engine (processes events, stream started separately)."""
        self._is_running = True
        logger.info("TradingEngine started 🚀")
        await self._process_events()

    async def stop(self):
        self._is_running = False
        logger.info("TradingEngine stopped")


# Singleton
_engine: Optional[TradingEngine] = None


def get_trading_engine() -> TradingEngine:
    global _engine
    if _engine is None:
        _engine = TradingEngine()
    return _engine
