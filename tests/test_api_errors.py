from fastapi.testclient import TestClient

from src.api.main import app, _engine_for
from src.engine.order_book import OrderBook

client = TestClient(app)
SYMBOL = "BTC-USDT"


def reset_book():
    _engine_for(SYMBOL).book = OrderBook(SYMBOL)

def test_bbo_empty_returns_none_sides():
    reset_book()  # <-- ensure clean state
    r = client.get("/bbo", params={"symbol": SYMBOL})
    assert r.status_code == 200
    body = r.json()
    assert body["bid"] is None
    assert body["ask"] is None

def test_submit_limit_and_check_bbo():
    reset_book()  # <-- ensure clean state
    r = client.post("/orders", json={
        "symbol": SYMBOL,
        "order_type": "limit",
        "side": "sell",
        "quantity": "0.5",
        "price": "62100",
    })
    assert r.status_code == 201
    ask_id = r.json()["order_id"]

    r = client.get("/bbo", params={"symbol": SYMBOL})
    assert r.status_code == 200
    bbo = r.json()
    assert bbo["ask"]["price"] == "62100"
    assert bbo["ask"]["qty"] == "0.5"

def test_cancel_nonexistent_returns_404():
    reset_book()
    r = client.delete("/orders/does-not-exist", params={"symbol": SYMBOL})
    assert r.status_code == 404
    body = r.json()
    assert body["error"] == "http_error"
    assert "not cancelable" in body["detail"]


def test_submit_invalid_symbol_400():
    r = client.post("/orders", json={
        "symbol": "ABC-XYZ",
        "order_type": "limit",
        "side": "buy",
        "quantity": "1.0",
        "price": "100"
    })
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "http_error"
    assert "unsupported symbol" in body["detail"]


def test_submit_invalid_order_type_422():
    r = client.post("/orders", json={
        "symbol": SYMBOL,
        "order_type": "good_till_cancelled",  
        "side": "buy",
        "quantity": "1.0",
        "price": "100"
    })
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"


def test_submit_invalid_side_422():
    r = client.post("/orders", json={
        "symbol": SYMBOL,
        "order_type": "limit",
        "side": "hold",  
        "quantity": "1.0",
        "price": "100"
    })
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"


def test_submit_zero_or_negative_price_for_priced_orders_422_or_400():
    r = client.post("/orders", json={
        "symbol": SYMBOL,
        "order_type": "limit",
        "side": "buy",
        "quantity": "1.0",
        "price": "0"
    })
    assert r.status_code in (400, 422)

    r2 = client.post("/orders", json={
        "symbol": SYMBOL,
        "order_type": "ioc",
        "side": "sell",
        "quantity": "1.0",
        "price": "-10"
    })
    assert r2.status_code in (400, 422)


def test_submit_market_with_price_ignores_price_and_executes():
    reset_book()
    r0 = client.post("/orders", json={
        "symbol": SYMBOL,
        "order_type": "limit",
        "side": "sell",
        "quantity": "0.2",
        "price": "50000"
    })
    assert r0.status_code == 201

    r = client.post("/orders", json={
        "symbol": SYMBOL,
        "order_type": "market",
        "side": "buy",
        "quantity": "0.1",
        "price": "999999"  
    })
    assert r.status_code == 201
    body = r.json()
    assert body["trades"][0]["price"] == "50000"
    assert body["trades"][0]["quantity"] == "0.1"
