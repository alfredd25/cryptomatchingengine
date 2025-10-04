from decimal import Decimal

from src.common.types import Side, OrderType
from src.engine.order import Order
from src.engine.matching_engine import MatchingEngine


def L(oid: str, side: Side, qty: str, price: str) -> Order:
    return Order(
        order_id=oid,
        symbol="BTC-USDT",
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        price=price,
    )


def IOC(oid: str, side: Side, qty: str, price: str | None) -> Order:
    return Order(
        order_id=oid,
        symbol="BTC-USDT",
        side=side,
        order_type=OrderType.IOC,
        quantity=qty,
        price=price,
    )


def FOK(oid: str, side: Side, qty: str, price: str | None) -> Order:
    return Order(
        order_id=oid,
        symbol="BTC-USDT",
        side=side,
        order_type=OrderType.FOK,
        quantity=qty,
        price=price,
    )


def test_ioc_partial_fills_cancel_remainder():
    eng = MatchingEngine("BTC-USDT")
    eng.book.add_order(L("S1", Side.SELL, "0.2", "62100"))
    eng.book.add_order(L("S2", Side.SELL, "0.5", "62200"))

    inc = IOC("B_IOC", Side.BUY, "0.5", "62150")  
    res = eng.submit(inc)

    assert res.resting is False
    assert res.fully_filled is False
    assert len(res.trades) == 1
    assert res.trades[0].price == Decimal("62100")
    assert res.trades[0].qty == Decimal("0.2")

    best_ask = eng.book.best_ask()
    assert best_ask == (Decimal("62200"), Decimal("0.5"))


def test_ioc_not_marketable_cancels_immediately():
    eng = MatchingEngine("BTC-USDT")
    eng.book.add_order(L("S1", Side.SELL, "1.0", "62500"))

    inc = IOC("B_IOC2", Side.BUY, "0.3", "62000")
    res = eng.submit(inc)
    assert len(res.trades) == 0
    assert res.resting is False
    assert res.fully_filled is False


def test_fok_full_fill_across_levels():
    eng = MatchingEngine("BTC-USDT")
    eng.book.add_order(L("S1", Side.SELL, "0.4", "62100"))
    eng.book.add_order(L("S2", Side.SELL, "0.4", "62150"))
    eng.book.add_order(L("S3", Side.SELL, "0.4", "62200"))

    inc = FOK("B_FOK_OK", Side.BUY, "1.0", "62200")
    res = eng.submit(inc)

    assert res.resting is False
    assert res.fully_filled is True
    assert len(res.trades) >= 2
    best_ask = eng.book.best_ask()
    assert best_ask is not None
    assert best_ask[1] == Decimal("0.2")


def test_fok_reject_when_insufficient():
    eng = MatchingEngine("BTC-USDT")
    eng.book.add_order(L("S1", Side.SELL, "0.5", "62100"))

    inc = FOK("B_FOK_NO", Side.BUY, "0.6", "62100")
    res = eng.submit(inc)

    assert len(res.trades) == 0
    assert res.resting is False
    assert res.fully_filled is False
    best_ask = eng.book.best_ask()
    assert best_ask == (Decimal("62100"), Decimal("0.5"))
