from __future__ import annotations

import uuid
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Set

from fastapi import (
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    BackgroundTasks,
    Request,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

from src.api.schemas import OrderSubmit, OrderSubmitResult, TradeReport, BBO, L2Depth
from src.common.logging import setup_logging, get_logger
from src.common.types import OrderType, Side
from src.engine.matching_engine import MatchingEngine
from src.engine.order import Order
from src.engine.order_book import OrderBook


app = FastAPI(title="Crypto Matching Engine", version="0.1.0")

#Logging 

LOGGER = setup_logging()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def log_requests(request: Request, call_next):
    path = request.url.path
    method = request.method
    try:
        response = await call_next(request)
        status = response.status_code
    except Exception as ex:
        LOGGER.exception("request_error path=%s method=%s", path, extra={"method": method})
        raise
    LOGGER.info("access path=%s method=%s status=%s", path, method, status)
    return response




SUPPORTED_SYMBOLS = {"BTC-USDT"}
_engines: dict[str, MatchingEngine] = {s: MatchingEngine(s) for s in SUPPORTED_SYMBOLS}


def _engine_for(symbol: str) -> MatchingEngine:
    if symbol not in _engines:
        raise HTTPException(status_code=400, detail=f"unsupported symbol: {symbol}")
    return _engines[symbol]


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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


@app.exception_handler(HTTPException)
async def http_exc_handler(_: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": "http_error", "detail": exc.detail},
    )

@app.exception_handler(RequestValidationError)
async def validation_exc_handler(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {"msg": "validation error"}
    return JSONResponse(
        status_code=422,
        content={"error": "validation_error", "detail": first.get("msg", "invalid request")},
    )


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
    if payload.symbol not in SUPPORTED_SYMBOLS:
        raise HTTPException(status_code=400, detail=f"unsupported symbol: {payload.symbol}")

    needs_price = payload.order_type in ("limit", "ioc", "fok")
    if needs_price and payload.price is None:
        raise HTTPException(status_code=400, detail="price is required for limit/ioc/fok orders")

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
    LOGGER.info("order_submit id=%s symbol=%s type=%s side=%s qty=%s price=%s",
                order_id, payload.symbol, payload.order_type, payload.side, payload.quantity, payload.price)

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
            LOGGER.info("trade_print id=%s symbol=%s px=%s qty=%s aggr=%s maker=%s taker=%s",
                        t.trade_id, t.symbol, t.price, t.qty, t.aggressor_side, t.maker_order_id, t.taker_order_id)

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
def cancel_order(order_id: str, symbol: str = Query(..., examples=["BTC-USDT"]), background_tasks: BackgroundTasks = None):
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
    if background_tasks is not None:
        background_tasks.add_task(_orderbook_feeds[symbol].publish, ob_msg)

    LOGGER.info("order_cancel id=%s symbol=%s", order_id, symbol)
    return {"status": "canceled", "order_id": order_id}


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
