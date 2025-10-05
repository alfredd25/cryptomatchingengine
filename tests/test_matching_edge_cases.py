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


def M(oid: str, side: Side, qty: str) -> Order:
    return Order(
        order_id=oid,
        symbol="BTC-USDT",
        side=side,
        order_type=OrderType.MARKET,
        quantity=qty,
        price=None,
    )


def test_non_marketable_limit_rests_without_trades():
    eng = MatchingEngine("BTC-USDT")
    eng.book.add_order(L("S1", Side.SELL, "1.0", "62500"))

    inc = L("B_LIM", Side.BUY, "0.4", "62000")
    res = eng.submit(inc)

    assert len(res.trades) == 0
    assert res.resting is True
    assert res.fully_filled is False

    bb = eng.book.best_bid()
    assert bb == (Decimal("62000"), Decimal("0.4"))


def test_market_on_empty_book_does_nothing():
    eng = MatchingEngine("BTC-USDT")
    res = eng.submit(M("B_MKT", Side.BUY, "1.0"))
    assert len(res.trades) == 0
    assert res.resting is False
    assert res.fully_filled is False 


def test_no_trade_through_better_prices():
    eng = MatchingEngine("BTC-USDT")
    eng.book.add_order(L("S1", Side.SELL, "0.3", "62000"))
    eng.book.add_order(L("S2", Side.SELL, "0.5", "62100"))

    inc = L("B_LIM", Side.BUY, "0.6", "62100")
    res = eng.submit(inc)

    assert len(res.trades) >= 1
    assert res.trades[0].price == Decimal("62000")
    assert sum(t.qty for t in res.trades) == Decimal("0.6")

    ba = eng.book.best_ask()
    assert ba == (Decimal("62100"), Decimal("0.2"))


def test_bbo_helpers_return_expected_shapes():
    eng = MatchingEngine("BTC-USDT")
    eng.book.add_order(L("B1", Side.BUY, "1.0", "61900"))
    eng.book.add_order(L("S1", Side.SELL, "2.0", "62100"))

    bbo = eng.bbo()
    assert bbo["bid"]["price"] == "61900"
    assert bbo["bid"]["qty"] == "1.0"
    assert bbo["ask"]["price"] == "62100"
    assert bbo["ask"]["qty"] == "2.0"

    l2 = eng.l2(top_n=2)
    assert l2["bids"][0] == ["61900", "1.0"]
    assert l2["asks"][0] == ["62100", "2.0"]
