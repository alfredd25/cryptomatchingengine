from __future__ import annotations

import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Set

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, BackgroundTasks

from src.api.schemas import OrderSubmit, OrderSubmitResult, TradeReport, BBO, L2Depth
from src.common.types import OrderType, Side
from src.engine.matching_engine import MatchingEngine
from src.engine.order import Order


app = FastAPI(title="Crypto Matching Engine", version="0.1.0")


# Engines 

SUPPORTED_SYMBOLS = {"BTC-USDT"}
_engines: dict[str, MatchingEngine] = {s: MatchingEngine(s) for s in SUPPORTED_SYMBOLS}


def _engine_for(symbol: str) -> MatchingEngine:
    if symbol not in _engines:
        raise HTTPException(status_code=400, detail=f"unsupported symbol: {symbol}")
    return _engines[symbol]



# Utilities

def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")



# Simple PubSub (in-memory)

class PubSub:
    def __init__(self) -> None:
        self._subs: Set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        async with self._lock:
            self._subs.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subs.discard(q)

    async def publish(self, message: Dict[str, Any]) -> None:
        async with self._lock:
            for q in list(self._subs):
                try:
                    q.put_nowait(message)
                except Exception:
                    self._subs.discard(q)


_orderbook_feeds: dict[str, PubSub] = {s: PubSub() for s in SUPPORTED_SYMBOLS}
_trade_feeds: dict[str, PubSub] = {s: PubSub() for s in SUPPORTED_SYMBOLS}



# REST (existing)

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/bbo", response_model=BBO)
def get_bbo(symbol: str = Query(..., examples=["BTC-USDT"])):
    eng = _engine_for(symbol)
    return eng.bbo()


@app.get("/orderbook", response_model=L2Depth)
def get_orderbook(symbol: str = Query(..., examples=["BTC-USDT"]), top_n: int = 10):
    if top_n <= 0 or top_n > 100:
        raise HTTPException(status_code=400, detail="top_n must be between 1 and 100")
    eng = _engine_for(symbol)
    snap = eng.l2(top_n=top_n)
    return L2Depth(symbol=symbol, bids=snap["bids"], asks=snap["asks"])


@app.post("/orders", response_model=OrderSubmitResult, status_code=201)
def submit_order(payload: OrderSubmit, background_tasks: BackgroundTasks):
    needs_price = payload.order_type in ("limit", "ioc", "fok")
    if needs_price and payload.price is None:
        raise HTTPException(status_code=400, detail="price is required for limit/ioc/fok orders")

    if payload.symbol not in SUPPORTED_SYMBOLS:
        raise HTTPException(status_code=400, detail=f"unsupported symbol: {payload.symbol}")

    order_id = str(uuid.uuid4())

    otype = OrderType(payload.order_type)
    side = Side(payload.side)

    order = Order(
        order_id=order_id,
        symbol=payload.symbol,
        side=side,
        order_type=otype,
        quantity=payload.quantity,
        price=payload.price,
    )

    eng = _engine_for(payload.symbol)
    res = eng.submit(order)

    if res.trades:
        feed = _trade_feeds[payload.symbol]
        for t in res.trades:
            msg = {
                "timestamp": _ts(),
                "symbol": t.symbol,
                "trade_id": t.trade_id,
                "price": str(t.price),
                "quantity": str(t.qty),
                "aggressor_side": t.aggressor_side,
                "maker_order_id": t.maker_order_id,
                "taker_order_id": t.taker_order_id,
            }
            background_tasks.add_task(feed.publish, msg)

    snap = eng.l2(top_n=10)
    ob_msg = {
        "timestamp": _ts(),
        "symbol": payload.symbol,
        "asks": snap["asks"],
        "bids": snap["bids"],
    }
    background_tasks.add_task(_orderbook_feeds[payload.symbol].publish, ob_msg)

    trades = [
        TradeReport(
            timestamp=t.ts,
            symbol=t.symbol,
            trade_id=t.trade_id,
            price=str(t.price),
            quantity=str(t.qty),
            aggressor_side=t.aggressor_side,  
            maker_order_id=t.maker_order_id,
            taker_order_id=t.taker_order_id,
        )
        for t in res.trades
    ]

    return OrderSubmitResult(
        order_id=order_id,
        fully_filled=res.fully_filled,
        resting=res.resting,
        trades=trades,
    )


@app.delete("/orders/{order_id}")
def cancel_order(order_id: str, background_tasks: BackgroundTasks, symbol: str = Query(..., examples=["BTC-USDT"])):
    eng = _engine_for(symbol)
    ok = eng.book.cancel_order(order_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"order not found or not cancelable: {order_id}")

    snap = eng.l2(top_n=10)
    ob_msg = {
        "timestamp": _ts(),
        "symbol": symbol,
        "asks": snap["asks"],
        "bids": snap["bids"],
    }
    background_tasks.add_task(_orderbook_feeds[symbol].publish, ob_msg)

    return {"status": "canceled", "order_id": order_id}

# WebSockets

@app.websocket("/ws/orderbook")
async def ws_orderbook(ws: WebSocket, symbol: str, top_n: int = 10):
    if symbol not in SUPPORTED_SYMBOLS:
        await ws.close(code=1008)
        return
    if top_n <= 0 or top_n > 100:
        await ws.close(code=1008)
        return

    await ws.accept()

    eng = _engine_for(symbol)
    snap = eng.l2(top_n=top_n)
    await ws.send_json({
        "timestamp": _ts(),
        "symbol": symbol,
        "asks": snap["asks"],
        "bids": snap["bids"],
    })

    feed = _orderbook_feeds[symbol]
    q = await feed.subscribe()
    try:
        while True:
            msg = await q.get()
            if "asks" in msg and "bids" in msg:
                msg = {
                    "timestamp": msg["timestamp"],
                    "symbol": msg["symbol"],
                    "asks": msg["asks"][:top_n],
                    "bids": msg["bids"][:top_n],
                }
            await ws.send_json(msg)
    except WebSocketDisconnect:
        await feed.unsubscribe(q)


@app.websocket("/ws/trades")
async def ws_trades(ws: WebSocket, symbol: str):
    if symbol not in SUPPORTED_SYMBOLS:
        await ws.close(code=1008)
        return

    await ws.accept()

    feed = _trade_feeds[symbol]
    q = await feed.subscribe()
    try:
        while True:
            msg = await q.get()
            await ws.send_json(msg)
    except WebSocketDisconnect:
        await feed.unsubscribe(q)
