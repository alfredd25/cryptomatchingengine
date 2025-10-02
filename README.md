# Crypto Matching Engine (Python, FastAPI)

High-performance cryptocurrency matching engine implementing:
- Price–time priority (FIFO within price levels)
- Internal order protection (no trade-through)
- Market/Limit/IOC/FOK order types
- Real-time BBO + L2 depth stream
- Trade execution feed

## Project Layout
- `src/engine/` – core matching logic (order, order book, matcher)
- `src/api/` – FastAPI app (REST + WebSockets)
- `src/common/` – shared types/helpers
- `tests/` – unit tests (pytest)

## Quick start (dev)
```bash
# from project root, with venv activated
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
