from fastapi.testclient import TestClient

from src.api.main import app, _engine_for


client = TestClient(app)
SYMBOL = "BTC-USDT"


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_bbo_empty_returns_none_sides():
    r = client.get("/bbo", params={"symbol": SYMBOL})
    assert r.status_code == 200
    body = r.json()
    assert body["bid"] is None
    assert body["ask"] is None


def test_submit_limit_and_check_bbo():
    r = client.post("/submit", json={
        "symbol": SYMBOL,
        "order_type": "limit",
        "side": "sell",
        "quantity": "0.5",
        "price": "62100",
    }, headers={"Idempotency-Key": "test-key-3"})
    assert r.status_code == 200
    ask_id = r.json()["order_id"]

    r = client.get("/bbo", params={"symbol": SYMBOL})
    assert r.status_code == 200
    bbo = r.json()
    assert bbo["ask"]["price"] == "62100"
    assert bbo["ask"]["qty"] == "0.5"

    r2 = client.post("/submit", json={
        "symbol": SYMBOL,
        "order_type": "market",
        "side": "buy",
        "quantity": "0.2"
    }, headers={"Idempotency-Key": "test-key-4"})
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["trades"][0]["price"] == "62100"
    assert body2["trades"][0]["qty"] == "0.2"

    r3 = client.get("/bbo", params={"symbol": SYMBOL})
    bbo2 = r3.json()
    assert bbo2["ask"]["price"] == "62100"
    assert bbo2["ask"]["qty"] == "0.3"

    ask_id2 = ask_id
    r4 = client.delete(f"/cancel/{ask_id2}", params={"symbol": SYMBOL})
    assert r4.status_code == 200

    r5 = client.get("/bbo", params={"symbol": SYMBOL})
    bbo3 = r5.json()
    assert bbo3["ask"] is None
