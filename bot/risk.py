"""
bot/risk.py
Risk Management Engine — enforces all trading risk rules.
MANDATORY: No trade is executed without passing risk checks.
"""
from dataclasses import dataclass, field
from typing import Dict, Optional, List
from datetime import datetime, timezone, date
from loguru import logger

from config.settings import settings


@dataclass
class RiskMetrics:
    """Current state of risk exposure."""
    account_balance: float
    available_balance: float
    open_positions: int
    daily_pnl: float
    daily_pnl_pct: float
    daily_loss_limit: float
    daily_loss_remaining: float
    max_trade_size_usdt: float
    is_trading_halted: bool
    halt_reason: str

    def to_dict(self):
        return {
            "account_balance": round(self.account_balance, 2),
            "available_balance": round(self.available_balance, 2),
            "open_positions": self.open_positions,
            "daily_pnl": round(self.daily_pnl, 2),
            "daily_pnl_pct": round(self.daily_pnl_pct * 100, 2),
            "daily_loss_limit_pct": round(settings.max_daily_loss * 100, 2),
            "daily_loss_remaining": round(self.daily_loss_remaining, 2),
            "max_trade_size_usdt": round(self.max_trade_size_usdt, 2),
            "is_trading_halted": self.is_trading_halted,
            "halt_reason": self.halt_reason,
            "max_positions": settings.max_open_positions,
        }


@dataclass
class PositionSizeResult:
    """Output of position size calculation."""
    allowed: bool
    quantity: float        # Number of contracts/coins
    notional_usdt: float   # Total position value in USDT
    risk_usdt: float       # Amount at risk (stop loss distance × quantity)
    leverage: int
    stop_loss: float
    take_profit: float
    reject_reason: str     # Set if allowed=False

    def to_dict(self):
        return {
            "allowed": self.allowed,
            "quantity": round(self.quantity, 6),
            "notional_usdt": round(self.notional_usdt, 2),
            "risk_usdt": round(self.risk_usdt, 2),
            "leverage": self.leverage,
            "stop_loss": round(self.stop_loss, 6),
            "take_profit": round(self.take_profit, 6),
            "reject_reason": self.reject_reason,
        }


class RiskManager:
    """
    Enforces all trading risk rules before any order is placed.

    Rules:
    1. Max 1% account balance risk per trade
    2. Max 3 simultaneous open positions
    3. Max 5% daily drawdown (halts bot if breached)
    4. Stop loss MANDATORY on every trade
    5. Max leverage: 5x
    """

    def __init__(self):
        self._daily_pnl: Dict[str, float] = {}  # date_str → pnl
        self._open_position_count: int = 0
        self._is_halted: bool = False
        self._halt_reason: str = ""
        self._start_balance: Dict[str, float] = {}  # date_str → balance
        logger.info("RiskManager initialized")

    # ── State Updates ──────────────────────────────────────────────────────────

    def update_position_count(self, count: int):
        """Update current open position count."""
        self._open_position_count = count

    def record_pnl(self, pnl: float, balance: float):
        """Record realized PnL for today."""
        today = date.today().isoformat()
        self._daily_pnl[today] = self._daily_pnl.get(today, 0.0) + pnl

        if today not in self._start_balance:
            self._start_balance[today] = balance

        self._check_daily_loss(balance)

    def _check_daily_loss(self, current_balance: float):
        """Check if daily loss limit has been breached."""
        today = date.today().isoformat()
        start_bal = self._start_balance.get(today, current_balance)
        daily_pnl = self._daily_pnl.get(today, 0.0)

        if start_bal > 0:
            loss_pct = abs(min(0, daily_pnl)) / start_bal
            if loss_pct >= settings.max_daily_loss:
                self._is_halted = True
                self._halt_reason = (
                    f"Daily loss limit reached: {loss_pct*100:.1f}% "
                    f"(limit: {settings.max_daily_loss*100:.0f}%)"
                )
                logger.critical(f"🛑 TRADING HALTED: {self._halt_reason}")

    def reset_daily(self):
        """Reset daily state (call at start of each day)."""
        self._daily_pnl.clear()
        self._start_balance.clear()
        if self._is_halted and "daily" in self._halt_reason.lower():
            self._is_halted = False
            self._halt_reason = ""
            logger.info("Daily risk reset — trading resumed")

    # ── Position Sizing ────────────────────────────────────────────────────────

    def calculate_position_size(
        self,
        symbol: str,
        action: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        account_balance: float,
    ) -> PositionSizeResult:
        """
        Calculate safe position size based on 1% risk rule.

        Formula:
        risk_usdt = account_balance × max_risk_per_trade (1%)
        sl_distance = |entry - stop_loss| / entry (%)
        quantity = risk_usdt / (entry × sl_distance)
        notional = quantity × entry
        leverage applied to meet min notional if needed.
        """
        if entry_price <= 0:
            return self._reject("Invalid entry price")
        if stop_loss <= 0:
            return self._reject("Stop loss required")

        # Distance from entry to stop loss (percentage)
        sl_distance = abs(entry_price - stop_loss) / entry_price
        if sl_distance < 0.001:
            return self._reject("Stop loss too close to entry (<0.1%)")

        # 1% risk per trade
        risk_usdt = account_balance * settings.max_risk_per_trade
        # Quantity based on risk
        quantity = risk_usdt / (entry_price * sl_distance)
        notional = quantity * entry_price

        # Apply leverage if notional is small
        leverage = min(settings.default_leverage, 5)

        # Effective with leverage
        effective_notional = notional * leverage

        return PositionSizeResult(
            allowed=True,
            quantity=round(quantity, 6),
            notional_usdt=round(notional, 2),
            risk_usdt=round(risk_usdt, 2),
            leverage=leverage,
            stop_loss=stop_loss,
            take_profit=take_profit,
            reject_reason="",
        )

    # ── Pre-Trade Checks ───────────────────────────────────────────────────────

    def can_trade(self, symbol: str = None) -> tuple[bool, str]:
        """
        Run all pre-trade checks. Returns (ok, reason).
        This MUST return True before any order is placed.
        """
        # 1. Daily loss halt
        if self._is_halted:
            return False, self._halt_reason

        # 2. Max positions
        if self._open_position_count >= settings.max_open_positions:
            return False, (
                f"Max positions reached ({self._open_position_count}/{settings.max_open_positions})"
            )

        return True, ""

    def validate_order(
        self,
        symbol: str,
        action: str,
        entry_price: float,
        stop_loss: float,
        account_balance: float,
    ) -> tuple[bool, str]:
        """Validate all risk params before sending order."""
        can, reason = self.can_trade(symbol)
        if not can:
            return False, reason

        # SL required
        if stop_loss <= 0:
            return False, "Stop loss is required for all trades"

        # SL direction check
        if action == "LONG" and stop_loss >= entry_price:
            return False, "LONG stop loss must be below entry"
        if action == "SHORT" and stop_loss <= entry_price:
            return False, "SHORT stop loss must be above entry"

        # Max leverage
        if settings.default_leverage > 5:
            return False, "Leverage exceeds 5x limit"

        return True, ""

    def get_metrics(self, account_balance: float, available_balance: float) -> RiskMetrics:
        """Get current risk metrics snapshot."""
        today = date.today().isoformat()
        start_bal = self._start_balance.get(today, account_balance)
        daily_pnl = self._daily_pnl.get(today, 0.0)
        daily_pnl_pct = daily_pnl / start_bal if start_bal > 0 else 0.0

        daily_loss_limit_usdt = start_bal * settings.max_daily_loss
        daily_loss_remaining = daily_loss_limit_usdt - abs(min(0, daily_pnl))

        max_trade = account_balance * settings.max_risk_per_trade * settings.default_leverage

        return RiskMetrics(
            account_balance=account_balance,
            available_balance=available_balance,
            open_positions=self._open_position_count,
            daily_pnl=daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            daily_loss_limit=daily_loss_limit_usdt,
            daily_loss_remaining=max(0.0, daily_loss_remaining),
            max_trade_size_usdt=max_trade,
            is_trading_halted=self._is_halted,
            halt_reason=self._halt_reason,
        )

    def _reject(self, reason: str) -> PositionSizeResult:
        logger.warning(f"RiskManager rejection: {reason}")
        return PositionSizeResult(
            allowed=False, quantity=0, notional_usdt=0,
            risk_usdt=0, leverage=0, stop_loss=0, take_profit=0,
            reject_reason=reason,
        )


# Singleton
_risk_manager: Optional[RiskManager] = None


def get_risk_manager() -> RiskManager:
    global _risk_manager
    if _risk_manager is None:
        _risk_manager = RiskManager()
    return _risk_manager
