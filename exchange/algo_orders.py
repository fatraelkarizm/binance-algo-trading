"""
exchange/algo_orders.py
Binance Futures Algo API — TWAP & VP order execution.
Endpoints: /sapi/v1/algo/futures/...
"""
import time
import hmac
import hashlib
from typing import Optional, Dict, Any, List
from loguru import logger
import httpx

from config.settings import settings


class AlgoOrderClient:
    """
    Direct client for Binance Futures Algo API.
    Uses api.binance.com (not testnet URL) with HMAC-SHA256 auth.
    Supports: TWAP and VP (Volume Participation) algo orders.
    """

    ALGO_BASE = "https://api.binance.com"

    def __init__(self):
        self.api_key = settings.active_api_key
        self.api_secret = settings.active_api_secret
        self.dry_run = settings.dry_run

        self.http = httpx.Client(
            base_url=self.ALGO_BASE,
            headers={
                "X-MBX-APIKEY": self.api_key,
                "Content-Type": "application/x-www-form-urlencoded",
            },
            timeout=30.0,
        )
        logger.info(f"AlgoOrderClient ready [DRY_RUN={self.dry_run}]")

    def _sign(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Stamp timestamp and compute HMAC-SHA256 signature."""
        params["timestamp"] = int(time.time() * 1000)
        query = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        sig = hmac.new(
            self.api_secret.encode(),
            query.encode(),
            hashlib.sha256,
        ).hexdigest()
        params["signature"] = sig
        return params

    def _post(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict]:
        """POST request with signed params."""
        signed = self._sign(params)
        try:
            resp = self.http.post(endpoint, data=signed)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Algo API error [{endpoint}]: {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"Request error [{endpoint}]: {e}")
            return None

    def _get(self, endpoint: str, params: Dict[str, Any] = None) -> Optional[Any]:
        """GET request with signed params."""
        signed = self._sign(params or {})
        try:
            resp = self.http.get(endpoint, params=signed)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Algo GET error [{endpoint}]: {e.response.text}")
            return None

    def _delete(self, endpoint: str, params: Dict[str, Any]) -> Optional[Dict]:
        """DELETE request with signed params."""
        signed = self._sign(params)
        try:
            resp = self.http.request("DELETE", endpoint, params=signed)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Algo DELETE error [{endpoint}]: {e.response.text}")
            return None

    # ── TWAP Order ────────────────────────────────────────────────────────────

    def create_twap(
        self,
        symbol: str,
        side: str,
        quantity: float,
        duration: int = None,
        position_side: str = "BOTH",
        limit_price: float = None,
        reduce_only: bool = False,
        client_algo_id: str = None,
    ) -> Optional[Dict]:
        """
        Create a TWAP (Time-Weighted Average Price) algo order.

        Args:
            symbol: e.g. 'BTCUSDT'
            side: 'BUY' or 'SELL'
            quantity: Total quantity to execute
            duration: Duration in seconds (min 300 = 5min, max 86400 = 24h)
            position_side: 'BOTH', 'LONG', or 'SHORT'
            limit_price: Optional limit price (prevents fill above/below)
            reduce_only: Only reduce existing position
            client_algo_id: Custom ID for tracking

        Returns:
            API response dict or None on failure

        Note: Minimum order size = 10,000 USDT
        """
        duration = duration or settings.twap_default_duration

        # Validate duration: 5 min – 24 hours
        if not (300 <= duration <= 86400):
            logger.error(f"TWAP duration must be 300–86400s, got {duration}")
            return None

        if self.dry_run:
            logger.info(
                f"[DRY RUN] TWAP | {side} {quantity} {symbol} "
                f"| Duration: {duration}s ({duration//60}min)"
            )
            return {
                "clientAlgoId": client_algo_id or f"DRY_{int(time.time())}",
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "duration": duration,
                "type": "TWAP",
            }

        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "duration": duration,
            "positionSide": position_side,
        }
        if limit_price:
            params["limitPrice"] = limit_price
        if reduce_only:
            params["reduceOnly"] = "true"
        if client_algo_id:
            params["clientAlgoId"] = client_algo_id

        resp = self._post("/sapi/v1/algo/futures/newOrderTwap", params)
        if resp:
            logger.success(f"TWAP created: {resp.get('clientAlgoId')} | {side} {quantity} {symbol}")
        return resp

    # ── VP Order ──────────────────────────────────────────────────────────────

    def create_vp(
        self,
        symbol: str,
        side: str,
        quantity: float,
        urgency: str = None,
        position_side: str = "BOTH",
        limit_price: float = None,
        reduce_only: bool = False,
        client_algo_id: str = None,
    ) -> Optional[Dict]:
        """
        Create a Volume Participation (VP) algo order.

        Args:
            symbol: e.g. 'BTCUSDT'
            side: 'BUY' or 'SELL'
            quantity: Total quantity to execute
            urgency: 'LOW', 'MEDIUM', or 'HIGH' (participation rate)
            position_side: 'BOTH', 'LONG', or 'SHORT'
            limit_price: Optional limit price
            reduce_only: Only reduce existing position
            client_algo_id: Custom ID for tracking

        Note:
            Max 10 open VP orders at a time.
            Min order size = 10,000 USDT
        """
        urgency = urgency or settings.vp_default_urgency

        if urgency not in ("LOW", "MEDIUM", "HIGH"):
            logger.error(f"VP urgency must be LOW/MEDIUM/HIGH, got {urgency}")
            return None

        if self.dry_run:
            logger.info(f"[DRY RUN] VP | {side} {quantity} {symbol} | Urgency: {urgency}")
            return {
                "clientAlgoId": client_algo_id or f"DRY_VP_{int(time.time())}",
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "urgency": urgency,
                "type": "VP",
            }

        params: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "quantity": quantity,
            "urgency": urgency,
            "positionSide": position_side,
        }
        if limit_price:
            params["limitPrice"] = limit_price
        if reduce_only:
            params["reduceOnly"] = "true"
        if client_algo_id:
            params["clientAlgoId"] = client_algo_id

        resp = self._post("/sapi/v1/algo/futures/newOrderVp", params)
        if resp:
            logger.success(f"VP created: {resp.get('clientAlgoId')} | {side} {quantity} {symbol}")
        return resp

    # ── Query & Cancel ────────────────────────────────────────────────────────

    def get_open_algo_orders(self) -> List[Dict]:
        """Get all currently open TWAP/VP algo orders."""
        resp = self._get("/sapi/v1/algo/futures/openOrders")
        if resp and "orders" in resp:
            return resp["orders"]
        return []

    def get_historical_algo_orders(
        self,
        symbol: str = None,
        algo_id: str = None,
        start_time: int = None,
        end_time: int = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Get historical completed/cancelled algo orders."""
        params: Dict[str, Any] = {"limit": limit}
        if symbol:
            params["symbol"] = symbol
        if algo_id:
            params["algoId"] = algo_id
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time

        resp = self._get("/sapi/v1/algo/futures/historicalOrders", params)
        if resp and "orders" in resp:
            return resp["orders"]
        return []

    def get_sub_orders(self, algo_id: str, limit: int = 50) -> List[Dict]:
        """Get child sub-orders of a specific algo order."""
        params = {"algoId": algo_id, "limit": limit}
        resp = self._get("/sapi/v1/algo/futures/subOrders", params)
        if resp and "subOrders" in resp:
            return resp["subOrders"]
        return []

    def cancel_algo_order(self, algo_id: str) -> Optional[Dict]:
        """Cancel a TWAP or VP algo order by its algoId."""
        if self.dry_run:
            logger.info(f"[DRY RUN] Cancel algo order: {algo_id}")
            return {"algoId": algo_id, "status": "CANCELLED"}

        resp = self._delete("/sapi/v1/algo/futures/order", {"algoId": algo_id})
        if resp:
            logger.info(f"Algo order cancelled: {algo_id}")
        return resp

    def cancel_all_algo_orders(self) -> int:
        """Cancel all open algo orders. Returns count cancelled."""
        orders = self.get_open_algo_orders()
        cancelled = 0
        for order in orders:
            if self.cancel_algo_order(order["algoId"]):
                cancelled += 1
        logger.info(f"Cancelled {cancelled} algo orders")
        return cancelled

    def close(self):
        self.http.close()


# Singleton
_algo_client: Optional[AlgoOrderClient] = None


def get_algo_client() -> AlgoOrderClient:
    global _algo_client
    if _algo_client is None:
        _algo_client = AlgoOrderClient()
    return _algo_client
