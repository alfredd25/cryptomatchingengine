from __future__ import annotations

import uuid
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from src.api.schemas import OrderSubmit, OrderSubmitResult, TradeReport, BBO, L2Depth
from src.common.types import OrderType, Side
from src.engine.matching_engine import MatchingEngine
from src.engine.order import Order


app = FastAPI(title="Crypto Matching Engine", version="0.1.0")

SUPPORTED_SYMBOLS = {"BTC-USDT"}
_engines: dict[str, MatchingEngine] = {s: MatchingEngine(s) for s in SUPPORTED_SYMBOLS}


@app.get("/health")
def health():
    return {"status": "ok"}


def _engine_for(symbol: str) -> MatchingEngine:
    if symbol not in _engines:
        raise HTTPException(status_code=400, detail=f"unsupported symbol: {symbol}")
    return _engines[symbol]


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
def submit_order(payload: OrderSubmit):
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
def cancel_order(order_id: str, symbol: str = Query(..., examples=["BTC-USDT"])):
    eng = _engine_for(symbol)
    ok = eng.book.cancel_order(order_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"order not found or not cancelable: {order_id}")
    return {"status": "canceled", "order_id": order_id}
