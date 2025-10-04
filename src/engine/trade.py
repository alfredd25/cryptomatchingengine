from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal


@dataclass(frozen=True)
class Trade:
    ts: datetime
    symbol: str
    trade_id: str
    price: Decimal
    qty: Decimal
    aggressor_side: str  
    maker_order_id: str
    taker_order_id: str

    @staticmethod
    def now_ts() -> datetime:
        return datetime.now(timezone.utc)
