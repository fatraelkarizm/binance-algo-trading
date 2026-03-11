1. Cara Kerja Binance Futures Algo

Algo API memungkinkan lu bikin order execution algorithm seperti:

TWAP

Time Weighted Average Price

order besar → dipecah jadi order kecil selama waktu tertentu.

Misal:

Buy 10 BTC
duration = 2 jam

Binance otomatis:

buy kecil tiap interval

Tujuan:

mengurangi slippage

tidak mempengaruhi market

VP (Volume Participation)

Order mengikuti volume market.

Contoh:

buy 5% volume market

Kecepatan eksekusi bisa diatur:

LOW
MEDIUM
HIGH

Jumlah algo order dibatasi:

max 10 open VP orders

dan harus aktifkan Futures Trading Permission pada API key.

2. Endpoint Futures Algo API

Base URL

https://api.binance.com

Endpoint penting:

Create TWAP
POST /sapi/v1/algo/futures/newOrderTwap
Create Volume Participation
POST /sapi/v1/algo/futures/newOrderVp
Query Open Orders
GET /sapi/v1/algo/futures/openOrders
Query Historical Orders
GET /sapi/v1/algo/futures/historicalOrders
Query Sub Orders
GET /sapi/v1/algo/futures/subOrders
Cancel Algo Order
DELETE /sapi/v1/algo/futures/order
3. Parameter Penting

Parameter yang wajib:

symbol
side
quantity
timestamp
signature

Parameter tambahan:

positionSide
limitPrice
reduceOnly
clientAlgoId
duration (TWAP)
urgency (VP)

Contoh:

symbol=BTCUSDT
side=BUY
quantity=0.5
duration=3600

TWAP duration rules:

min 5 minutes
max 24 hours

dan order size minimal:

10,000 USDT

4. System Architecture Auto Trading

Kalau lu bikin bot serius, arsitekturnya harus seperti ini.

                ┌──────────────┐
                │ Market Data  │
                │ Binance WS   │
                └──────┬───────┘
                       │
                       ▼
                ┌──────────────┐
                │ Signal Engine│
                │ AI / Strategy│
                └──────┬───────┘
                       │
                       ▼
                ┌──────────────┐
                │ Risk Manager │
                └──────┬───────┘
                       │
                       ▼
                ┌──────────────┐
                │ Trade Engine │
                │ Algo API     │
                └──────┬───────┘
                       │
                       ▼
                ┌──────────────┐
                │ Monitoring   │
                │ Dashboard    │
                └──────────────┘
5. Setup Step-by-Step

Sekarang setup real.

Step 1 — Create API Key

Masuk:

Binance → API Management

Enable:

Futures Trading

jangan enable withdrawal.

Step 2 — Install Library

Python bot biasanya pakai:

pip install python-binance
pip install ccxt
pip install websockets
Step 3 — Connect Binance
from binance.client import Client

client = Client(API_KEY, API_SECRET)
Step 4 — Get Market Data
price = client.futures_symbol_ticker(symbol="BTCUSDT")
print(price)
Step 5 — Execute Algo Order

TWAP example:

import requests
import time
import hmac
import hashlib

endpoint="/sapi/v1/algo/futures/newOrderTwap"

payload:

symbol=BTCUSDT
side=BUY
quantity=0.5
duration=3600
6. Backend Project Structure

Project structure yang proper:

trading-bot/
│
├── bot
│   ├── engine.py
│   ├── strategy.py
│   ├── risk.py
│
├── exchange
│   ├── binance_client.py
│
├── ai
│   ├── signal_ai.py
│
├── data
│   ├── market_stream.py
│
├── api
│   ├── server.py
│
├── config
│   ├── settings.py
│
└── main.py
7. Strategy Engine

Contoh strategi sederhana.

RSI < 30 → LONG
RSI > 70 → SHORT

Pseudo:

if rsi < 30:
   open_long()

if rsi > 70:
   open_short()
8. Risk Management (WAJIB)

Kalau bot tanpa risk management = cepat liquid.

Minimal:

max risk per trade = 1%
max position = 3
max daily loss = 5%

Stop loss wajib.

9. PRD (Product Requirement Document)
Product
AI Futures Trading Agent
Problem

crypto trading:

24/7
volatile
manual trading sulit
Solution

AI bot yang:

analyze market
generate signal
execute algo order
manage risk
Target User

crypto trader

hedge fund kecil

algo trader

copy trading user

Core Features
auto futures trading
AI signal
algo execution
risk management
Advanced Features
TWAP execution
VP execution
smart money tracking
AI sentiment
portfolio management
10. prompt.md untuk AI Trading Agent

Contoh prompt:

You are a professional crypto trading AI.

Analyze Binance Futures market data and generate trading signals.

Rules:

Risk per trade: 1%
Max leverage: 5x
Allowed pairs: BTCUSDT, ETHUSDT, SOLUSDT

Output format:

{
 "symbol": "",
 "action": "LONG | SHORT | HOLD",
 "entry": "",
 "stop_loss": "",
 "take_profit": ""
}
11. Dashboard Monitoring

Lu harus punya dashboard.

Features:

open positions
PnL
win rate
active orders
risk level

Tech:

Next.js
FastAPI
Redis
Websocket