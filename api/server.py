"""
api/server.py
FastAPI Backend Server — REST API + WebSocket for the dashboard.
Provides real-time data: positions, signals, PnL, orders, news, risk.
"""
import asyncio
import json
from datetime import datetime, timezone
from typing import List, Optional, Set
from loguru import logger

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from config.settings import settings
from exchange.binance_client import get_client
from exchange.algo_orders import get_algo_client
from bot.risk import get_risk_manager
from bot.engine import get_trading_engine
from ai.signal_ai import get_signal_engine
from ai.sentiment import get_sentiment_analyzer
from ai.smart_money import get_smart_money_tracker
from data.klines import fetch_klines


# ── FastAPI App ──────────────────────────────────────────────────────────────

app = FastAPI(
    title="Binance Futures Algo Trading API",
    description="Real-time trading bot dashboard API with TWAP/VP algo execution",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── WebSocket Manager ────────────────────────────────────────────────────────

class ConnectionManager:
    """Manages active WebSocket connections for live dashboard updates."""

    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)
        logger.info(f"WS client connected. Total: {len(self.active)}")

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)
        logger.info(f"WS client disconnected. Total: {len(self.active)}")

    async def broadcast(self, data: dict):
        dead = set()
        msg = json.dumps(data)
        for ws in self.active:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.active.discard(ws)


manager = ConnectionManager()


# ── Background Tasks ─────────────────────────────────────────────────────────

async def broadcast_loop():
    """Push live data to all connected WebSocket clients every 5 seconds."""
    client = get_client()
    risk = get_risk_manager()

    while True:
        try:
            balance = client.get_account_balance()
            positions = client.get_open_positions()
            account_bal = balance["balance"]
            avail_bal = balance["available"]

            risk.update_position_count(len(positions))
            metrics = risk.get_metrics(account_bal, avail_bal)

            payload = {
                "type": "live_update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "balance": balance,
                "positions": positions,
                "risk": metrics.to_dict(),
            }
            if manager.active:
                await manager.broadcast(payload)

        except Exception as e:
            logger.error(f"Broadcast loop error: {e}")

        await asyncio.sleep(5)


# ── Startup / Shutdown ────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    logger.info("FastAPI server starting up...")
    asyncio.create_task(broadcast_loop())
    logger.success("Background broadcast loop started ✓")


# ── REST Endpoints ────────────────────────────────────────────────────────────

@app.get("/", tags=["Health"])
async def root():
    return {
        "status": "online",
        "system": "Binance Futures Algo Trading Bot",
        "mode": "TESTNET" if settings.binance_testnet else "LIVE",
        "dry_run": settings.dry_run,
        "symbols": settings.symbols,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/balance", tags=["Account"])
async def get_balance():
    """Get current account balance and unrealized PnL."""
    client = get_client()
    return client.get_account_balance()


@app.get("/api/positions", tags=["Trading"])
async def get_positions():
    """Get all open futures positions."""
    client = get_client()
    positions = client.get_open_positions()
    return {"positions": positions, "count": len(positions)}


@app.get("/api/pnl", tags=["Account"])
async def get_pnl(symbol: Optional[str] = None):
    """Get realized PnL from recent trades."""
    client = get_client()
    trades = client.get_realized_pnl(symbol)
    total_pnl = sum(t["realized_pnl"] for t in trades)
    total_commission = sum(t["commission"] for t in trades)
    return {
        "trades": trades[:25],
        "total_realized_pnl": round(total_pnl, 4),
        "total_commission": round(total_commission, 4),
        "net_pnl": round(total_pnl - total_commission, 4),
    }


@app.get("/api/signals", tags=["Signals"])
async def get_signals(symbol: Optional[str] = None):
    """Get latest technical signals for all or specific symbols."""
    engine = get_signal_engine()

    if symbol:
        sig = engine.analyze(symbol.upper())
        return {"signals": [sig.to_dict()] if sig else [], "count": 1 if sig else 0}

    signals = engine.analyze_all()
    return {
        "signals": [s.to_dict() for s in signals.values()],
        "count": len(signals),
    }


@app.get("/api/sentiment", tags=["AI"])
async def get_sentiment(symbol: Optional[str] = None):
    """Get news sentiment for symbols."""
    analyzer = get_sentiment_analyzer()

    if symbol:
        sent = await analyzer.get_symbol_sentiment(symbol.upper())
        return sent.to_dict()

    sentiments = await analyzer.get_all_sentiments()
    return {
        "sentiments": {k: v.to_dict() for k, v in sentiments.items()},
    }


@app.get("/api/smart-money", tags=["AI"])
async def get_smart_money(symbol: Optional[str] = None):
    """Get smart money / whale activity analysis."""
    tracker = get_smart_money_tracker()

    if symbol:
        signal = await tracker.analyze(symbol.upper())
        return signal.to_dict()

    signals = await tracker.analyze_all()
    return {
        "smart_money": {k: v.to_dict() for k, v in signals.items()},
    }


@app.get("/api/news", tags=["News"])
async def get_news():
    """Get latest crypto news with sentiment scores."""
    analyzer = get_sentiment_analyzer()
    news = analyzer.get_cached_news()
    if not news:
        # Fetch if cache empty
        await analyzer.fetch_news()
        news = analyzer.get_cached_news()
    return {"news": news, "count": len(news)}


@app.get("/api/risk", tags=["Risk"])
async def get_risk():
    """Get current risk management metrics."""
    client = get_client()
    risk = get_risk_manager()
    balance = client.get_account_balance()
    metrics = risk.get_metrics(balance["balance"], balance["available"])
    return metrics.to_dict()


@app.get("/api/orders/algo", tags=["Orders"])
async def get_algo_orders():
    """Get open TWAP/VP algo orders."""
    algo = get_algo_client()
    orders = algo.get_open_algo_orders()
    historical = algo.get_historical_algo_orders(limit=20)
    return {
        "open_orders": orders,
        "open_count": len(orders),
        "recent_historical": historical[:10],
    }


@app.delete("/api/orders/algo/{algo_id}", tags=["Orders"])
async def cancel_algo_order(algo_id: str):
    """Cancel a TWAP or VP algo order."""
    algo = get_algo_client()
    result = algo.cancel_algo_order(algo_id)
    if result:
        return {"success": True, "result": result}
    return JSONResponse({"success": False, "error": "Cancel failed"}, status_code=400)


@app.get("/api/klines/{symbol}", tags=["Market"])
async def get_klines(symbol: str, interval: str = "15m", limit: int = 100):
    """Get OHLCV candle data for charting."""
    df = fetch_klines(symbol.upper(), interval, limit)
    if df.empty:
        return JSONResponse({"error": "No data"}, status_code=404)

    candles = df[["open", "high", "low", "close", "volume"]].tail(limit).to_dict(orient="records")
    timestamps = df.tail(limit).index.astype(str).tolist()
    return {
        "symbol": symbol.upper(),
        "interval": interval,
        "candles": candles,
        "timestamps": timestamps,
    }


@app.get("/api/trades", tags=["Trading"])
async def get_trade_history():
    """Get bot's internal trade history."""
    engine = get_trading_engine()
    return {
        "trades": engine.get_trade_history(50),
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_endpoint(websocket: WebSocket):
    """Real-time WebSocket: broadcasts positions, balance, risk every 5s."""
    await manager.connect(websocket)
    try:
        # Send welcome message
        await websocket.send_json({
            "type": "connected",
            "message": "Connected to Binance Algo Trading Bot",
            "symbols": settings.symbols,
            "mode": "TESTNET" if settings.binance_testnet else "LIVE",
        })
        # Keep alive
        while True:
            data = await websocket.receive_text()
            # Handle ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(websocket)


# ── Run ───────────────────────────────────────────────────────────────────────

def run_server():
    uvicorn.run(
        "api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info",
    )
