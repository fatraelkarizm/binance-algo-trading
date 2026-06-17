# Binance Algo Trading

Python + Next.js trading bot for Binance Futures with market streaming, AI-assisted signals, risk controls, TWAP/VP algo orders, a FastAPI backend, and a realtime dashboard.

> Trading crypto futures is risky. Keep `DRY_RUN=true` while testing, use testnet/demo keys first, and never commit API secrets.

## Features

- Binance COIN-M Futures market data stream
- Strategy engine with technical signals
- Risk manager for position count, risk per trade, daily loss, stop loss, and take profit
- TWAP and Volume Participation algo order client
- AI modules for sentiment, smart money tracking, and signal enrichment
- FastAPI REST API and WebSocket feed
- Next.js dashboard for balance, positions, risk, signals, orders, and market data
- Docker Compose stack with Redis, bot API, and dashboard

## Project Structure

```text
.
|-- ai/                 # Sentiment, smart money, and AI signal helpers
|-- api/                # FastAPI REST and WebSocket server
|-- bot/                # Trading engine, strategy, and risk manager
|-- config/             # Environment-driven settings
|-- dashboard/          # Next.js monitoring dashboard
|-- data/               # Klines and market stream clients
|-- exchange/           # Binance REST/algo order clients
|-- logs/               # Runtime logs
|-- main.py             # Starts market stream, engine, and API server
|-- docker-compose.yml  # Redis + bot + dashboard stack
|-- Dockerfile          # Python bot image
|-- requirements.txt    # Python dependencies
`-- SETUP.md            # Longer Binance Algo API notes
```

## Requirements

- Python 3.11+
- Node.js 20+ for the dashboard
- Docker and Docker Compose, optional but recommended
- Binance API key with Futures permission enabled
- Redis, if running outside Docker

## Configuration

Create a local `.env` file in the repository root. Do not commit it.

```env
# Safety
DRY_RUN=true
BINANCE_DEMO=true
BINANCE_TESTNET=false

# Binance live keys
BINANCE_API_KEY=
BINANCE_API_SECRET=

# Binance demo keys
BINANCE_DEMO_API_KEY=
BINANCE_DEMO_API_SECRET=

# Binance testnet keys
BINANCE_TESTNET_API_KEY=
BINANCE_TESTNET_API_SECRET=

# Trading
TRADING_SYMBOLS=BTCUSD_PERP,ETHUSD_PERP,SOLUSD_PERP
DEFAULT_LEVERAGE=5
SIGNAL_TIMEFRAME=15m

# Risk
MAX_RISK_PER_TRADE=0.01
MAX_OPEN_POSITIONS=3
MAX_DAILY_LOSS=0.05
DEFAULT_STOP_LOSS_PCT=0.02
DEFAULT_TAKE_PROFIT_PCT=0.04

# Algo orders
ALGO_MIN_ORDER_USDT=10000
TWAP_DEFAULT_DURATION=3600
VP_DEFAULT_URGENCY=MEDIUM

# Optional AI/news providers
CRYPTOCOMPARE_API_KEY=
OPENAI_API_KEY=

# Services
API_HOST=0.0.0.0
API_PORT=8000
REDIS_URL=redis://localhost:6379
```

Mode priority is `BINANCE_DEMO` first, then `BINANCE_TESTNET`, then live trading.

## Run With Docker

```powershell
docker compose up --build
```

Services:

- API: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`
- Dashboard: `http://localhost:3000`
- WebSocket: `ws://localhost:8000/ws/live`

## Run Locally

Install Python dependencies:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Start Redis separately, then run the bot/API:

```powershell
python main.py
```

Run the dashboard:

```powershell
cd dashboard
npm install
npm run dev
```

Open `http://localhost:3000`.

## API Endpoints

- `GET /` - health and current mode
- `GET /api/balance` - account balance and PnL data
- `GET /api/positions` - open futures positions
- `GET /api/pnl` - recent realized PnL
- `GET /api/signals` - latest trading signals
- `GET /api/sentiment` - news sentiment
- `GET /api/smart-money` - smart money analysis
- `GET /api/news` - cached crypto news
- `GET /api/risk` - current risk metrics
- `GET /api/orders/algo` - open and recent TWAP/VP orders
- `DELETE /api/orders/algo/{algo_id}` - cancel an algo order
- `GET /api/klines/{symbol}` - OHLCV candles
- `GET /api/trades` - internal trade history
- `WS /ws/live` - realtime balance, positions, and risk updates

## Development Notes

- Keep `DRY_RUN=true` until exchange connectivity and risk settings are verified.
- Keep `.env`, logs, cache files, and compiled artifacts out of commits.
- Review `SETUP.md` for Binance Futures Algo API behavior, TWAP/VP limits, and manual setup notes.
- Use demo/testnet keys before switching to live mode.

## Disclaimer

This project is for research and automation experiments. It is not financial advice, and it does not guarantee profit or protect against loss.
