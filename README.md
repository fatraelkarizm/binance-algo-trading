# 🚀 Binance Futures Algo Trading Bot

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue.svg" alt="Python Version" />
  <img src="https://img.shields.io/badge/FastAPI-0.109-009688.svg" alt="FastAPI" />
  <img src="https://img.shields.io/badge/Next.js-16-000000.svg" alt="Next.js" />
  <img src="https://img.shields.io/badge/Binance-Futures-F3BA2F.svg" alt="Binance" />
  <img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License" />
</p>

## 📖 Overview

The **Binance Futures Algo Trading Bot** is a high-performance, fully automated algorithmic trading system designed for Binance COIN-M Futures. It combines institutional-grade order execution strategies (TWAP, Volume Participation), robust risk management protocols, and AI-driven market analysis to execute trades autonomously 24/7. It also features a sleek, real-time web dashboard built with Next.js to monitor your portfolio, active signals, and risk metrics.

## ⚠️ Problem Statement

In the highly volatile cryptocurrency derivatives market, traders face several critical challenges:
1. **24/7 Market Monitoring:** Humans cannot constantly monitor charts and technical indicators around the clock without fatigue.
2. **Execution Slippage & Market Impact:** Placing large orders manually often results in high slippage.
3. **Emotional Trading & Risk Control:** Maintaining strict risk management discipline (e.g., stopping trading after a 5% daily drawdown) is psychologically difficult.
4. **Information Overload:** Quickly digesting news sentiment and technical confluence across multiple timeframes is overwhelming.

## 💡 Solution

This project solves these challenges by providing an autonomous, multi-service trading engine:
- **Algorithmic Execution:** Utilizes Binance's Algo API for TWAP (Time-Weighted Average Price) and VP (Volume Participation) to minimize slippage on large orders (>10,000 USDT).
- **Ironclad Risk Management:** Hard-coded rules enforce a maximum of 1% balance risk per trade, a strict 5% daily drawdown limit (which automatically halts the bot), a maximum of 3 concurrent positions, and mandatory stop-losses on every trade.
- **AI-Powered Confluence:** Analyzes RSI, MACD, EMA trends, and Bollinger Bands alongside real-time news sentiment (via CryptoCompare/OpenAI) to generate high-confidence trading signals.
- **Real-Time Visibility:** A low-latency Next.js dashboard connects via WebSockets to provide a live, unified view of PnL, active signals, algo orders, and overall risk exposure.

## ✨ Key Features

* **Multi-Mode Support:** Seamlessly switch between LIVE, TESTNET, and DEMO (`demo-fapi.binance.com`) environments.
* **Concurrent Architecture:** Runs the Market Data WebSocket stream, Trading Engine, and REST/WS API Server simultaneously using Python `asyncio`.
* **Advanced Indicator Scoring:** Computes signal confidence using multiple technical indicators (`pandas` + `ta`).
* **News & Sentiment Tracking:** Fetches and analyzes crypto news sentiment to avoid trading against major macroeconomic trends.
* **Real-time Web Dashboard:** A beautiful, dark-themed UI featuring Recharts for PnL visualization and real-time updates.

## 🛠️ Tech Stack

### Backend (Trading Engine & API)
* **Language:** Python 3
* **Framework:** FastAPI, Uvicorn (REST & WebSocket Server)
* **Trading APIs:** `python-binance`, `ccxt`, `httpx`, `websockets`
* **Data Processing:** `pandas`, `numpy`, `ta` (Technical Analysis)
* **Scheduling & Logging:** `apscheduler`, `loguru`

### Frontend (Dashboard)
* **Framework:** Next.js 16 (App Router), React 19
* **Styling:** Tailwind CSS v4
* **Charting & Icons:** Recharts, Lucide-React
* **Language:** TypeScript

## 🚀 Getting Started

### Prerequisites
* Python 3.10+
* Node.js 20+
* A Binance account with Futures enabled (API Key & Secret)
* Redis (optional, based on config)

### 1. Backend Setup

```bash
# Clone the repository
git clone https://github.com/yourusername/Binance-Algo-Trading.git
cd Binance-Algo-Trading

# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
cp .env.example .env
# Edit .env with your Binance API keys and desired trading mode (e.g., BINANCE_DEMO=true)
```

### 2. Frontend Setup

```bash
# Navigate to the dashboard directory
cd dashboard

# Install dependencies
npm install

# Configure frontend environment variables
cp .env.local.example .env.local
# Ensure NEXT_PUBLIC_API_URL and NEXT_PUBLIC_WS_URL point to your Python backend
```

### 3. Running the System

Start the Python Trading Engine & API Server:
```bash
# From the root directory
python main.py
```

Start the Next.js Dashboard:
```bash
# From the dashboard directory
npm run dev
```

Visit `http://localhost:3000` in your browser to view the live dashboard!

---
*Disclaimer: This software is for educational purposes only. Do not risk money which you are afraid to lose. USE THE SOFTWARE AT YOUR OWN RISK. THE AUTHORS ASSUME NO RESPONSIBILITY FOR YOUR TRADING RESULTS.*
