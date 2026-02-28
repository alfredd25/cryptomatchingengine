import json
from fastapi.testclient import TestClient

from src.api.main import app, _engine_for
from src.engine.order_book import OrderBook

client = TestClient(app)
SYMBOL = "BTC-USDT"


def test_ws_orderbook_initial_and_update():
    _engine_for(SYMBOL).book = OrderBook(SYMBOL)
    
    with client.websocket_connect(f"/ws/orderbook?symbol={SYMBOL}&top_n=5") as ws:
        msg = ws.receive_json()
        assert msg["symbol"] == SYMBOL
        assert msg["bids"] == []
        assert msg["asks"] == []

        r = client.post("/submit", json={
            "symbol": SYMBOL,
            "order_type": "limit",
            "side": "sell",
            "quantity": "0.4",
            "price": "62100"
        }, headers={"Idempotency-Key": "test-key-5"})
        assert r.status_code == 200

        msg2 = ws.receive_json()
        assert msg2["asks"][0] == ["62100", "0.4"]


def test_ws_trades_receives_prints():
    _engine_for(SYMBOL).book = OrderBook(SYMBOL)
    with client.websocket_connect(f"/ws/trades?symbol={SYMBOL}") as ws:
        r = client.post("/submit", json={
            "symbol": SYMBOL,
            "order_type": "limit",
            "side": "sell",
            "quantity": "0.5",
            "price": "62050"
        }, headers={"Idempotency-Key": "test-key-6"})
        assert r.status_code == 200

        r2 = client.post("/submit", json={
            "symbol": SYMBOL,
            "order_type": "market",
            "side": "buy",
            "quantity": "0.3"
        }, headers={"Idempotency-Key": "test-key-7"})
        assert r2.status_code == 200

        trade_msg = ws.receive_json()
        assert trade_msg["symbol"] == SYMBOL
        assert trade_msg["price"] == "62050"
        assert trade_msg["qty"] == "0.3"
        assert trade_msg["aggressor_side"] == "buy"
