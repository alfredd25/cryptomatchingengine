from decimal import Decimal

from src.common.types import Side, OrderType
from src.engine.order import Order
from src.engine.order_book import OrderBook


def make_limit(order_id: str, side: Side, qty: str, price: str) -> Order:
    return Order(
        order_id=order_id,
        symbol="BTC-USDT",
        side=side,
        order_type=OrderType.LIMIT,
        quantity=qty,
        price=price,
    )


def test_insert_and_bbo_simple():
    ob = OrderBook("BTC-USDT")

    ob.add_order(make_limit("B1", Side.BUY, "1.0", "62000"))
    ob.add_order(make_limit("B2", Side.BUY, "0.5", "62100"))
    ob.add_order(make_limit("S1", Side.SELL, "0.7", "62200"))
    ob.add_order(make_limit("S2", Side.SELL, "0.4", "62300"))

    best_bid = ob.best_bid()
    best_ask = ob.best_ask()

    assert best_bid == (Decimal("62100"), Decimal("0.5"))
    assert best_ask == (Decimal("62200"), Decimal("0.7"))

    bids = ob.depth(Side.BUY, top_n=5)
    asks = ob.depth(Side.SELL, top_n=5)

    assert bids[0] == ("62100", "0.5")
    assert bids[1] == ("62000", "1.0")
    assert asks[0] == ("62200", "0.7")
    assert asks[1] == ("62300", "0.4")


def test_price_time_fifo_within_level():
    ob = OrderBook("BTC-USDT")
    ob.add_order(make_limit("B1", Side.BUY, "1.0", "62000"))
    ob.add_order(make_limit("B2", Side.BUY, "2.0", "62000"))
    best_bid = ob.best_bid()
    assert best_bid == (Decimal("62000"), Decimal("3.0"))

    assert ob.cancel_order("B1") is True
    best_bid = ob.best_bid()
    assert best_bid == (Decimal("62000"), Decimal("2.0"))
    assert ob.has_order("B2") is True
    assert ob.has_order("B1") is False


def test_cancel_removes_levels_when_empty():
    ob = OrderBook("BTC-USDT")
    ob.add_order(make_limit("S1", Side.SELL, "1.0", "63000"))
    assert ob.best_ask() == (Decimal("63000"), Decimal("1.0"))
    assert ob.cancel_order("S1") is True
    assert ob.best_ask() is None  
