"""
exchange/binance_client.py
Authenticated Binance REST client for Futures trading.
Handles HMAC-SHA256 signature, rate limiting, testnet switching.
"""
import time
import hmac
import hashlib
import httpx
import asyncio
from typing import Optional, Dict, Any
from loguru import logger
from binance.client import Client
from binance.exceptions import BinanceAPIException

from config.settings import settings


class BinanceClient:
    """
    Wrapper around python-binance Client + raw httpx for Algo API.
    Algo API endpoints are on api.binance.com (not fapi).
    """

    def __init__(self):
        self.api_key = settings.active_api_key
        self.api_secret = settings.active_api_secret
        self.testnet = settings.binance_testnet
        self.dry_run = settings.dry_run

        # python-binance client (for standard futures ops)
        self.client = Client(
            api_key=self.api_key,
            api_secret=self.api_secret,
            testnet=self.testnet,
        )

        # Async HTTP client for Algo API calls
        self.http = httpx.AsyncClient(
            base_url=settings.algo_base_url,
            headers={
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30.0,
        )

        mode = "🧪 TESTNET" if self.testnet else "🔴 LIVE"
        dry = " | DRY RUN" if self.dry_run else ""
        logger.info(f"BinanceClient initialized [{mode}{dry}]")

    # ── Signature ──────────────────────────────────────────────────────────────

    def _sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Add timestamp + HMAC-SHA256 signature to params."""
        params["timestamp"] = int(time.time() * 1000)
        query_string = "&".join(f"{k}={v}" for k, v in params.items())
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = signature
        return params

    # ── Account ────────────────────────────────────────────────────────────────

    def get_account_balance(self) -> Dict[str, Any]:
        """Get futures account balance in USDT."""
        try:
            balances = self.client.futures_account_balance()
            usdt = next((b for b in balances if b["asset"] == "USDT"), None)
            return {
                "asset": "USDT",
                "balance": float(usdt["balance"]) if usdt else 0.0,
                "available": float(usdt["availableBalance"]) if usdt else 0.0,
                "unrealized_pnl": float(usdt.get("crossUnPnl", 0)) if usdt else 0.0,
            }
        except BinanceAPIException as e:
            logger.error(f"Balance fetch error: {e}")
            return {"asset": "USDT", "balance": 0.0, "available": 0.0, "unrealized_pnl": 0.0}

    def get_open_positions(self) -> list:
        """Get all open futures positions."""
        try:
            positions = self.client.futures_position_information()
            return [
                {
                    "symbol": p["symbol"],
                    "side": "LONG" if float(p["positionAmt"]) > 0 else "SHORT",
                    "size": abs(float(p["positionAmt"])),
                    "entry_price": float(p["entryPrice"]),
                    "mark_price": float(p["markPrice"]),
                    "unrealized_pnl": float(p["unRealizedProfit"]),
                    "leverage": int(p["leverage"]),
                    "liquidation_price": float(p["liquidationPrice"]),
                    "margin_type": p["marginType"],
                }
                for p in positions
                if float(p["positionAmt"]) != 0
            ]
        except BinanceAPIException as e:
            logger.error(f"Position fetch error: {e}")
            return []

    def get_ticker_price(self, symbol: str) -> float:
        """Get latest price for a symbol."""
        try:
            ticker = self.client.futures_symbol_ticker(symbol=symbol)
            return float(ticker["price"])
        except BinanceAPIException as e:
            logger.error(f"Ticker error {symbol}: {e}")
            return 0.0

    def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a symbol."""
        try:
            self.client.futures_change_leverage(symbol=symbol, leverage=leverage)
            logger.info(f"Leverage set: {symbol} → {leverage}x")
            return True
        except BinanceAPIException as e:
            logger.error(f"Leverage set error {symbol}: {e}")
            return False

    # ── Standard Futures Orders ────────────────────────────────────────────────

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        position_side: str = "BOTH",
        reduce_only: bool = False,
    ) -> Optional[Dict]:
        """Place a standard futures market order."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Market order: {side} {quantity} {symbol}")
            return {"orderId": "DRY_RUN", "symbol": symbol, "side": side, "qty": quantity}

        try:
            params = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": quantity,
                "positionSide": position_side,
            }
            if reduce_only:
                params["reduceOnly"] = True

            order = self.client.futures_create_order(**params)
            logger.success(f"Order placed: {order['orderId']} | {side} {quantity} {symbol}")
            return order
        except BinanceAPIException as e:
            logger.error(f"Order error: {e}")
            return None

    def place_stop_loss(self, symbol: str, side: str, quantity: float, stop_price: float) -> Optional[Dict]:
        """Place a stop-market order for stop loss."""
        if self.dry_run:
            logger.info(f"[DRY RUN] SL order: {symbol} @ {stop_price}")
            return {"orderId": "DRY_RUN_SL", "stopPrice": stop_price}

        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type="STOP_MARKET",
                stopPrice=stop_price,
                quantity=quantity,
                reduceOnly=True,
            )
            logger.info(f"SL placed: {symbol} @ {stop_price}")
            return order
        except BinanceAPIException as e:
            logger.error(f"SL order error: {e}")
            return None

    def place_take_profit(self, symbol: str, side: str, quantity: float, tp_price: float) -> Optional[Dict]:
        """Place a take-profit-market order."""
        if self.dry_run:
            logger.info(f"[DRY RUN] TP order: {symbol} @ {tp_price}")
            return {"orderId": "DRY_RUN_TP", "stopPrice": tp_price}

        try:
            order = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type="TAKE_PROFIT_MARKET",
                stopPrice=tp_price,
                quantity=quantity,
                reduceOnly=True,
            )
            logger.info(f"TP placed: {symbol} @ {tp_price}")
            return order
        except BinanceAPIException as e:
            logger.error(f"TP order error: {e}")
            return None

    def get_realized_pnl(self, symbol: str = None) -> list:
        """Fetch recent trade history with realized PnL."""
        try:
            kwargs = {"limit": 50}
            if symbol:
                kwargs["symbol"] = symbol
            trades = self.client.futures_account_trades(**kwargs)
            return [
                {
                    "symbol": t["symbol"],
                    "side": t["side"],
                    "realized_pnl": float(t["realizedPnl"]),
                    "commission": float(t["commission"]),
                    "time": t["time"],
                }
                for t in trades
            ]
        except BinanceAPIException as e:
            logger.error(f"PnL fetch error: {e}")
            return []

    async def close(self):
        await self.http.aclose()


# Singleton instance
_client: Optional[BinanceClient] = None


def get_client() -> BinanceClient:
    global _client
    if _client is None:
        _client = BinanceClient()
    return _client
