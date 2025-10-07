from __future__ import annotations

import argparse
import random
import string
import time
from decimal import Decimal
from typing import Tuple

from src.engine.matching_engine import MatchingEngine
from src.engine.order import Order
from src.common.types import Side, OrderType

try:
    import asyncio
    import httpx
except Exception:
    asyncio = None
    httpx = None


SYMBOL = "BTC-USDT"


def _rid(prefix: str = "O") -> str:
    return prefix + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def seed_book_inproc(eng: MatchingEngine, n_levels: int = 20, qty_per_level: str = "0.5") -> None:
    """
    Seed asks and bids around a mid price to create depth.
    """
    mid = Decimal("62000")
    tick = Decimal("10")

    for i in range(1, n_levels + 1):
        px = mid + tick * i
        eng.book.add_order(
            Order(
                order_id=_rid("S"),
                symbol=SYMBOL,
                side=Side.SELL,
                order_type=OrderType.LIMIT,
                quantity=qty_per_level,
                price=str(px),
            )
        )

    for i in range(1, n_levels + 1):
        px = mid - tick * i
        eng.book.add_order(
            Order(
                order_id=_rid("B"),
                symbol=SYMBOL,
                side=Side.BUY,
                order_type=OrderType.LIMIT,
                quantity=qty_per_level,
                price=str(px),
            )
        )


def run_inproc(num_orders: int = 5000, market_ratio: float = 0.5) -> Tuple[int, float]:
    """
    Benchmark direct engine.submit (no HTTP). Returns (orders_processed, seconds).
    """
    eng = MatchingEngine(SYMBOL)
    seed_book_inproc(eng)

    t0 = time.perf_counter()
    trades = 0

    for i in range(num_orders):
        side = Side.BUY if (i % 2 == 0) else Side.SELL
        is_market = (random.random() < market_ratio)

        if is_market:
            otype = OrderType.MARKET
            price = None
        else:
            bbo = eng.bbo()
            px = None
            if side is Side.BUY and bbo["ask"]:
                px = bbo["ask"]["price"]
            elif side is Side.SELL and bbo["bid"]:
                px = bbo["bid"]["price"]
            else:
                px = "62000"
            otype = OrderType.LIMIT
            price = px

        o = Order(
            order_id=_rid(),
            symbol=SYMBOL,
            side=side,
            order_type=otype,
            quantity="0.1",
            price=price,
        )
        res = eng.submit(o)
        trades += len(res.trades)

    dt = time.perf_counter() - t0
    print(f"[INPROC] orders={num_orders} trades={trades} elapsed={dt:.4f}s rate={num_orders/dt:.0f} orders/sec")
    return num_orders, dt


async def run_http_async(endpoint: str, num_orders: int = 2000, market_ratio: float = 0.5) -> Tuple[int, float]:
    """
    Benchmark via HTTP REST API using httpx.AsyncClient. Expects FastAPI server running at endpoint.
    """
    assert httpx is not None and asyncio is not None, "Install httpx to use HTTP mode: pip install httpx"

    async with httpx.AsyncClient(base_url=endpoint, timeout=10.0) as client:
        for i in range(10):
            px = 62000 + 10 * (i + 1)
            r = await client.post("/orders", json={
                "symbol": SYMBOL, "order_type": "limit", "side": "sell",
                "quantity": "0.5", "price": str(px)
            })
            r.raise_for_status()

        t0 = time.perf_counter()
        trades = 0

        for i in range(num_orders):
            side = "buy" if (i % 2 == 0) else "sell"
            is_market = (random.random() < market_ratio)

            if is_market:
                payload = {
                    "symbol": SYMBOL, "order_type": "market", "side": side, "quantity": "0.1"
                }
            else:
                bbo = (await client.get("/bbo", params={"symbol": SYMBOL})).json()
                if side == "buy" and bbo["ask"]:
                    px = bbo["ask"]["price"]
                elif side == "sell" and bbo["bid"]:
                    px = bbo["bid"]["price"]
                else:
                    px = "62000"
                payload = {
                    "symbol": SYMBOL, "order_type": "limit", "side": side, "quantity": "0.1", "price": px
                }

            r = await client.post("/orders", json=payload)
            r.raise_for_status()
            trades += len(r.json().get("trades", []))

        dt = time.perf_counter() - t0
        print(f"[HTTP] {endpoint} orders={num_orders} trades={trades} elapsed={dt:.4f}s rate={num_orders/dt:.0f} orders/sec")
        return num_orders, dt


def main():
    parser = argparse.ArgumentParser(description="Basic load test for matching engine")
    parser.add_argument("--mode", choices=["inproc", "http"], default="inproc")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8000", help="FastAPI base URL for http mode")
    parser.add_argument("--orders", type=int, default=5000)
    parser.add_argument("--market-ratio", type=float, default=0.5, help="Probability an order is MARKET (0..1)")
    args = parser.parse_args()

    if args.mode == "inproc":
        run_inproc(num_orders=args.orders, market_ratio=args.market_ratio)
    else:
        if httpx is None:
            print("Please: pip install httpx")
            return
        asyncio.run(run_http_async(endpoint=args.endpoint, num_orders=args.orders, market_ratio=args.market_ratio))


if __name__ == "__main__":
    main()
