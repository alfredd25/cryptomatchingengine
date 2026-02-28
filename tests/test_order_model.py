from decimal import Decimal
import pytest

from src.common.types import Side, OrderType
from src.engine.order import Order


def test_limit_order_creation():
    o = Order(
        order_id="O1",
        symbol="BTC-USDT",
        side=Side.BUY,
        order_type=OrderType.LIMIT,
        quantity="0.5",
        price="62000.10",
    )
    assert o.remaining == Decimal("0.5")
    assert o.price == Decimal("62000.10")
    assert o.active is True
    assert o.seq == 0  


def test_market_disallows_price():
    o = Order(
        order_id="O2",
        symbol="BTC-USDT",
        side=Side.SELL,
        order_type=OrderType.MARKET,
        quantity="1.0",
        price=None, 
    )
    assert o.price is None


def test_invalid_qty_raises():
    with pytest.raises(ValueError):
        Order(
            order_id="O3",
            symbol="BTC-USDT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity="0",
            price="61000",
        )


def test_invalid_price_for_limit_raises():
    with pytest.raises(ValueError):
        Order(
            order_id="O4",
            symbol="BTC-USDT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity="1",
            price="0",
        )


def test_reduce_and_filled_flags():
    o = Order(
        order_id="O5",
        symbol="BTC-USDT",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        quantity="2",
        price="63000",
    )
    o.reduce("0.5")
    assert o.remaining == Decimal("1.5")
    assert o.filled() == Decimal("0.5")
    assert o.active is True

    o.reduce("1.5")
    assert o.remaining == Decimal("0")
    assert o.is_fully_filled() is True
    assert o.active is False
