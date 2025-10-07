# Crypto Matching Engine (Python)

High-performance, REG NMS–inspired matching engine for cryptocurrency pairs.  
Implements strict **price–time priority**, **internal order protection**, and core order types (**Market, Limit, IOC, FOK**).  
Real-time **WebSocket** feeds provide L2 order book snapshots and **trade prints**.

---

## Features

- **Matching logic**
  - Price–time priority (FIFO at price level)
  - Internal order protection (no trade-throughs)
  - Order types: Market, Limit, IOC, FOK
- **Market data**
  - BBO (Best Bid/Offer)
  - L2 order book snapshot (top N)
  - Trade execution reports (maker/taker, aggressor, qty, price)
- **APIs**
  - REST (submit/cancel orders, BBO, order book)
  - WebSockets (order book + trades)
- **Reliability**
  - Input validation & clear error model
  - Structured logging (API + engine)
  - Unit & API tests (including negative paths)
- **Bench**
  - In-process and HTTP load tests (`scripts/load_test.py`)

---

## Quickstart

> Requires Python **3.10+**. Instructions assume Windows + PowerShell.  
> On macOS/Linux, replace backslashes with slashes and use `source .venv/bin/activate`.

```powershell
# 1) Clone and enter repo
cd C:\Users\alfre\OneDrive\Desktop\crypto-matching-engine

# 2) Create & activate venv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 3) Install deps
pip install -r requirements.txt -r requirements-dev.txt

# 4) Run tests (should all pass)
pytest -q

# 5) Start API server (FastAPI/Uvicorn)
uvicorn src.api.main:app --reload
# Visit docs at: http://127.0.0.1:8000/docs
