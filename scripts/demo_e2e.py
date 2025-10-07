from __future__ import annotations
import asyncio
import json
import uuid
from typing import Optional

import httpx

try:
    import websockets
except Exception:
    websockets = None

BASE = "http://127.0.0.1:8000"
SYMBOL = "BTC-USDT"


async def seed_liquidity(client: httpx.AsyncClient):
    asks = [("0.3","62100"), ("0.5","62150"), ("0.7","62200")]
    bids = [("0.4","61950"), ("0.6","61900")]
    for q,p in asks:
        await client.post("/orders", json={"symbol": SYMBOL, "order_type": "limit",
                                           "side": "sell", "quantity": q, "price": p})
    for q,p in bids:
        await client.post("/orders", json={"symbol": SYMBOL, "order_type": "limit",
                                           "side": "buy", "quantity": q, "price": p})


async def print_bbo_and_depth(client: httpx.AsyncClient):
    bbo = (await client.get("/bbo", params={"symbol": SYMBOL})).json()
    ob = (await client.get("/orderbook", params={"symbol": SYMBOL, "top_n": 5})).json()
    print("BBO:", json.dumps(bbo))
    print("L2:", json.dumps(ob))


async def ws_orderbook_listener(top_n: int = 5):
    if websockets is None:
        print("Install websockets to run WS demo: pip install websockets")
        return
    uri = f"ws://127.0.0.1:8000/ws/orderbook?symbol={SYMBOL}&top_n={top_n}"
    async with websockets.connect(uri) as ws:
        print("[WS-OB] connected")
        for _ in range(5):
            msg = await ws.recv()
            print("[WS-OB]", msg)


async def ws_trades_listener():
    if websockets is None:
        print("Install websockets to run WS demo: pip install websockets")
        return
    uri = f"ws://127.0.0.1:8000/ws/trades?symbol={SYMBOL}"
    async with websockets.connect(uri) as ws:
        print("[WS-TRD] connected")
        for _ in range(3):
            msg = await ws.recv()
            print("[WS-TRD]", msg)


async def place_sample_orders(client: httpx.AsyncClient):
    r1 = await client.post("/orders", json={"symbol": SYMBOL, "order_type": "market", "side": "buy", "quantity": "0.4"})
    print("MARKET BUY:", r1.json())
    r2 = await client.post("/orders", json={"symbol": SYMBOL, "order_type": "ioc", "side": "buy", "quantity": "0.6", "price": "62100"})
    print("IOC BUY:", r2.json())
    r3 = await client.post("/orders", json={"symbol": SYMBOL, "order_type": "fok", "side": "buy", "quantity": "0.5", "price": "62150"})
    print("FOK BUY:", r3.json())
    r4 = await client.post("/orders", json={"symbol": SYMBOL, "order_type": "limit", "side": "sell", "quantity": "0.3", "price": "62080"})
    print("REST SELL:", r4.json())


async def main():
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as client:
        await seed_liquidity(client)
        await print_bbo_and_depth(client)

        tasks = []
        if websockets is not None:
            tasks = [
                asyncio.create_task(ws_orderbook_listener(5)),
                asyncio.create_task(ws_trades_listener()),
            ]

        await place_sample_orders(client)
        await print_bbo_and_depth(client)

        if tasks:
            await asyncio.sleep(1.0)
            for t in tasks:
                t.cancel()

if __name__ == "__main__":
    asyncio.run(main())
