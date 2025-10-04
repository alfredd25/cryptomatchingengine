from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from src.common.types import OrderId, OrderType, Side, to_decimal


@dataclass
class Order:
    order_id: OrderId
    symbol: str
    side: Side
    order_type: OrderType
    quantity: Decimal
    price: Optional[Decimal]  
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    remaining: Decimal = field(init=False)
    active: bool = field(default=True)
    seq: int = field(default=0)  

    def __post_init__(self) -> None:
        self.quantity = to_decimal(self.quantity)
        if self.price is not None:
            self.price = to_decimal(self.price)

        if self.quantity <= 0:
            raise ValueError("quantity must be > 0")
        if self.order_type in (OrderType.LIMIT, OrderType.IOC, OrderType.FOK):
            if self.price is None or self.price <= 0:
                raise ValueError("price must be > 0 for limit/IOC/FOK orders")
        if self.order_type is OrderType.MARKET and self.price is not None:
            self.price = None

        self.remaining = self.quantity

    @property
    def is_market(self) -> bool:
        return self.order_type is OrderType.MARKET

    @property
    def is_limit(self) -> bool:
        return self.order_type is OrderType.LIMIT

    @property
    def is_ioc(self) -> bool:
        return self.order_type is OrderType.IOC

    @property
    def is_fok(self) -> bool:
        return self.order_type is OrderType.FOK

    def filled(self) -> Decimal:
        return self.quantity - self.remaining

    def is_fully_filled(self) -> bool:
        return self.remaining == 0

    def reduce(self, qty: Decimal) -> None:
        qty = to_decimal(qty)
        if qty <= 0:
            raise ValueError("reduce qty must be > 0")
        if qty > self.remaining:
            raise ValueError("cannot reduce beyond remaining")
        self.remaining -= qty
        if self.remaining == 0:
            self.active = False
