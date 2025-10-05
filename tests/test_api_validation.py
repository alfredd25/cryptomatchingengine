from fastapi.testclient import TestClient
from src.api.main import app, _engine_for, SUPPORTED_SYMBOLS
from src.engine.order_book import OrderBook

client = TestClient(app)
SYMBOL = "BTC-USDT"


def reset_book():
    _engine_for(SYMBOL).book = OrderBook(SYMBOL)


def test_reject_unsupported_symbol():
    r = client.get("/bbo", params={"symbol": "ABC-XYZ"})
    assert r.status_code == 400
    body = r.json()
    assert body["error"] == "http_error"
    assert "unsupported symbol" in body["detail"]


def test_require_price_for_priced_orders():
    reset_book()
    r = client.post("/orders", json={
        "symbol": SYMBOL,
        "order_type": "limit",
        "side": "buy",
        "quantity": "1.0"
    })
    assert r.status_code == 400
    assert r.json()["error"] == "http_error"


def test_negative_qty_validation():
    reset_book()
    r = client.post("/orders", json={
        "symbol": SYMBOL,
        "order_type": "market",
        "side": "sell",
        "quantity": "-1.0"
    })
    assert r.status_code == 422
    assert r.json()["error"] == "validation_error"
