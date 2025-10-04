from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, getcontext
from enum import Enum
from typing import NewType

getcontext().prec = 28

OrderId = NewType("OrderId", str)

class Side(str, Enum):
  BUY = "buy"
  SELL = "sell"

class OrderType(str, Enum):
  MARKET = "market"
  LIMIT = "limit" 
  IOC = "ioc"
  FOK = "fok"

def to_decimal(x: str | int | float | Decimal) -> Decimal:
  """
    Convert incoming numeric types to Decimal safely.
    Always convert floats via str to avoid binary float artifacts.
  """

  if isinstance(x, Decimal):
    return x
  if isinstance(x, float):
    return Decimal(str(x))
  return Decimal(x)