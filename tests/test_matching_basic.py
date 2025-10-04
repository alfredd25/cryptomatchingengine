from decimal import Decimal

from src.common.types import Side, OrderType
from src.engine.order import Order
from src.engine.matching_engine import MatchingEngine


def L(order_id: str, side: Side, qty: str, price: str) -> Order:
    return Order(
        order_id=order_id,
        symbol="BTC-USDT",
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        price=price,
    )


def M(order_id: str, side: Side, qty: str) -> Order:
    return Order(
        order_id=order_id,
        symbol="BTC-USDT",
        side=side,
        order_type=OrderType.MARKET,
        quantity=qty,
        price=None,
    )


def test_market_buy_consumes_best_ask_fifo():
    eng = MatchingEngine("BTC-USDT")
    eng.book.add_order(L("S1", Side.SELL, "0.4", "62100"))
    eng.book.add_order(L("S2", Side.SELL, "0.6", "62100"))
    eng.book.add_order(L("S3", Side.SELL, "1.0", "62200"))

    inc = M("B_TK", Side.BUY, "0.7")
    res = eng.submit(inc)

    assert res.fully_filled is True
    assert res.resting is False
    assert len(res.trades) == 2
    assert res.trades[0].maker_order_id == "S1"
    assert res.trades[0].price == Decimal("62100")
    assert res.trades[0].qty == Decimal("0.4")
    assert res.trades[1].maker_order_id == "S2"
    assert res.trades[1].qty == Decimal("0.3")

    best_ask = eng.book.best_ask()
    assert best_ask == (Decimal("62100"), Decimal("0.3"))


def test_market_sell_consumes_best_bid_fifo():
    eng = MatchingEngine("BTC-USDT")
    eng.book.add_order(L("B1", Side.BUY, "0.5", "62000"))
    eng.book.add_order(L("B2", Side.BUY, "0.5", "61950"))

    inc = M("S_TK", Side.SELL, "0.6")
    res = eng.submit(inc)

    assert res.fully_filled is True
    assert len(res.trades) == 2
    assert res.trades[0].price == Decimal("62000")
    assert res.trades[0].qty == Decimal("0.5")
    assert res.trades[1].price == Decimal("61950")
    assert res.trades[1].qty == Decimal("0.1")

    best_bid = eng.book.best_bid()
    assert best_bid == (Decimal("61950"), Decimal("0.4"))


def test_marketable_limit_partial_fills_and_rests():
    eng = MatchingEngine("BTC-USDT")
    eng.book.add_order(L("S1", Side.SELL, "0.2", "62100"))
    eng.book.add_order(L("S2", Side.SELL, "0.5", "62200"))

    inc = L("B_LIM", Side.BUY, "0.5", "62100")
    res = eng.submit(inc)

    assert res.fully_filled is False
    assert res.resting is True
    assert len(res.trades) == 1
    assert res.trades[0].price == Decimal("62100")
    assert res.trades[0].qty == Decimal("0.2")

    bb = eng.book.best_bid()
    assert bb == (Decimal("62100"), Decimal("0.3"))
