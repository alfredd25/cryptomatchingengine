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
    Request,
    Header,
    BackgroundTasks,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from src.common.types import Side, OrderType, to_decimal
from src.engine.matching_engine import MatchingEngine
from src.engine.order import Order
from src.api.schemas import (
    OrderSubmit,
    OrderSubmitResponse,
    OrderBookDepthResponse,
    BBOResponse,
    TradeFeedMessage,
    DepthFeedMessage,
)
from src.common.logging import setup_logging
from src.infrastructure.db import init_db, close_db
from src.infrastructure.event_store import EventStore
from src.application.order_service import OrderService, get_engine, get_logger
from src.engine.order_book import OrderBook


SUPPORTED_SYMBOLS = {"BTC-USDT"}

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Initialize DB Connection pool & Tables
    await init_db()
    
    # 2. Replay historical events deterministically
    LOGGER.info("Starting WAL event replay...")
    events = await EventStore.fetch_all_events()
    for row in events:
        sym = row["symbol"]
        if sym not in SUPPORTED_SYMBOLS:
            continue
            
        engine = get_engine(sym)
        event_type = row["event_type"]
        
        if event_type == "ORDER_PLACED":
             engine.submit(Order(
                 order_id=row["order_id"],
                 symbol=sym,
                 side=Side(row["side"]),
                 order_type=OrderType(row["order_type"]),
                 quantity=row["quantity"],
                 price=row["price"]
             ))
        elif event_type == "ORDER_CANCELLED":
             engine.cancel(str(row["order_id"]))
             
    LOGGER.info(f"Replayed {len(events)} events successfully. Engine is ready.")
    
    yield
    
    # 3. Shutdown
    await close_db()


app = FastAPI(title="Crypto Matching Engine", version="0.1.0", lifespan=lifespan)

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
    if symbol not in SUPPORTED_SYMBOLS:
        raise HTTPException(status_code=400, detail=f"Unsupported symbol {symbol}")
    return get_engine(symbol)


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


@app.get("/bbo", response_model=BBOResponse)
def get_bbo(symbol: str = Query(..., examples=["BTC-USDT"])):
    eng = _engine_for(symbol)
    return eng.bbo()


@app.get("/orderbook", response_model=OrderBookDepthResponse)
def get_orderbook(symbol: str = Query(..., examples=["BTC-USDT"]), top_n: int = 10):
    if top_n <= 0 or top_n > 100:
        raise HTTPException(status_code=400, detail="top_n must be between 1 and 100")
    eng = _engine_for(symbol)
    snap = eng.l2(top_n=top_n)
    return OrderBookDepthResponse(symbol=symbol, bids=snap["bids"], asks=snap["asks"])


@app.post("/submit", response_model=Dict[str, Any])
async def submit_order(
    payload: OrderSubmit, 
    background_tasks: BackgroundTasks,
    idempotency_key: str = Header(..., description="Unique key for idempotent processing")
):
    """
    1. Parse validation
    2. Delegate to OrderService to write append-log via Postgres Tx
    3. Apply to engine
    4. Emit async websockets if trades happen
    """
    if payload.symbol not in SUPPORTED_SYMBOLS:
        raise HTTPException(status_code=400, detail="Invalid symbol")

    qty = to_decimal(payload.quantity)
    px = to_decimal(payload.price) if payload.price else None

    # Limit orders MUST have price
    if payload.order_type in (OrderType.LIMIT, OrderType.MAKER_ONLY) and px is None:
        raise HTTPException(status_code=400, detail="Limit orders require a price")

    result_dict = await OrderService.place_order(
         symbol=payload.symbol,
         side=payload.side,
         order_type=payload.order_type,
         quantity=qty,
         price=px,
         idempotency_key=idempotency_key
    )
    
    # If the response indicates this wasn't purely idempotent skip (duplicate)
    # We broadcast the depth updates and public trades
    if result_dict.get("status") == "Accepted":
        engine = get_engine(payload.symbol)
        
        trades = result_dict.get("trades", [])
        if trades:
             for t in trades:
                 msg: TradeFeedMessage = {
                     "type": "trade",
                     "symbol": payload.symbol,
                     "trade_id": t["trade_id"],
                     "price": t["price"],
                     "qty": t["qty"],
                     "maker_order_id": t["maker_order_id"],
                     "taker_order_id": result_dict["order_id"],
                     "ts": _ts(),
                     "aggressor_side": t["aggressor_side"]
                 }
                 background_tasks.add_task(_trade_feeds[payload.symbol].publish, msg)
                 
        # Depth update
        bbo = engine.bbo()
        ob_msg: DepthFeedMessage = {
            "type": "bbo",
            "symbol": payload.symbol,
            "bbo": bbo,
            "ts": _ts()
        }
        background_tasks.add_task(_orderbook_feeds[payload.symbol].publish, ob_msg)

    return result_dict


@app.delete("/cancel/{order_id}")
async def cancel_order(
    order_id: str, 
    symbol: str = Query(..., examples=["BTC-USDT"]),
    background_tasks: BackgroundTasks = None
):
    if symbol not in SUPPORTED_SYMBOLS:
         raise HTTPException(status_code=400, detail="Invalid symbol")
         
    success = await OrderService.cancel_order(symbol, order_id)
    if not success:
        raise HTTPException(status_code=404, detail="Order not found or already filled")
        
    engine = get_engine(symbol)
    bbo = engine.bbo()
    ob_msg: DepthFeedMessage = {
        "type": "bbo",
        "symbol": symbol,
        "bbo": bbo,
        "ts": _ts()
    }
    if background_tasks:
        background_tasks.add_task(_orderbook_feeds[symbol].publish, ob_msg)

    return {"status": "cancelled", "order_id": order_id}


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
