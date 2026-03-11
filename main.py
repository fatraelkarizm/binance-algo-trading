"""
main.py
Entry point — starts all services concurrently:
1. Market Data WebSocket Stream
2. Trading Engine (candle processing loop)
3. FastAPI REST + WebSocket Server
"""
import asyncio
import sys
import os
from loguru import logger

# ── Pretty startup banner ─────────────────────────────────────────────────────
BANNER = """
╔══════════════════════════════════════════════════════╗
║    🚀 BINANCE FUTURES ALGO TRADING BOT               ║
║    TWAP • VP • AI Signals • Risk Management          ║
╚══════════════════════════════════════════════════════╝
"""


def configure_logging():
    """Set up loguru with color formatting."""
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | <cyan>{module}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
        level="INFO",
        colorize=True,
    )
    logger.add(
        "logs/trading_bot.log",
        rotation="500 MB",
        retention="30 days",
        level="DEBUG",
        compression="zip",
    )


async def main():
    configure_logging()
    print(BANNER)

    # ── Load config ────────────────────────────────────────────────────────────
    from config.settings import settings
    logger.info(f"Mode: {'🧪 TESTNET' if settings.binance_testnet else '🔴 LIVE'}")
    logger.info(f"DRY RUN: {settings.dry_run}")
    logger.info(f"Symbols: {settings.symbols}")
    logger.info(f"Timeframe: {settings.signal_timeframe}")
    logger.info(f"Max Leverage: {settings.default_leverage}x")
    logger.info(f"Risk per trade: {settings.max_risk_per_trade * 100:.0f}%")

    if not settings.active_api_key:
        logger.error("❌ No API key configured! Copy .env.example → .env and fill in your keys.")
        sys.exit(1)

    # ── Import services ────────────────────────────────────────────────────────
    from data.market_stream import get_market_stream
    from bot.engine import get_trading_engine
    import uvicorn

    stream = get_market_stream()
    engine = get_trading_engine()

    # ── Pre-flight checks ──────────────────────────────────────────────────────
    logger.info("Running pre-flight checks...")
    from exchange.binance_client import get_client
    client = get_client()

    try:
        balance = client.get_account_balance()
        logger.success(f"✓ Binance connected | Balance: ${balance['balance']:,.2f} USDT")
    except Exception as e:
        logger.error(f"❌ Binance connection failed: {e}")
        if not settings.dry_run:
            sys.exit(1)

    # ── Set leverage for all symbols ────────────────────────────────────────────
    if not settings.dry_run:
        for sym in settings.symbols:
            client.set_leverage(sym, settings.default_leverage)
            logger.info(f"Leverage set: {sym} → {settings.default_leverage}x")

    logger.success("Pre-flight checks complete ✓")

    # ── Start all services concurrently ────────────────────────────────────────
    logger.info("Starting all services...")

    uvicorn_config = uvicorn.Config(
        "api.server:app",
        host=settings.api_host,
        port=settings.api_port,
        log_level="warning",
        access_log=False,
    )
    uvicorn_server = uvicorn.Server(uvicorn_config)

    tasks = [
        asyncio.create_task(stream.start(), name="market_stream"),
        asyncio.create_task(engine.start(), name="trading_engine"),
        asyncio.create_task(uvicorn_server.serve(), name="api_server"),
    ]

    logger.success(
        f"🚀 All services running!\n"
        f"   📡 Market Stream: {len(settings.symbols)} symbols @ {settings.signal_timeframe}\n"
        f"   🤖 Trading Engine: {'DRY RUN' if settings.dry_run else 'LIVE'}\n"
        f"   🌐 API Server: http://{settings.api_host}:{settings.api_port}\n"
        f"   📊 Dashboard: http://localhost:3000\n"
    )

    try:
        await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        logger.info("Shutdown signal received...")
    except Exception as e:
        logger.critical(f"Fatal error: {e}")
    finally:
        stream.stop()
        await engine.stop()
        logger.info("All services stopped. Goodbye! 👋")


if __name__ == "__main__":
    # Create logs dir
    os.makedirs("logs", exist_ok=True)
    os.makedirs("data", exist_ok=True)

    asyncio.run(main())
