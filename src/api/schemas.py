from __future__ import annotations
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional, List
from pydantic import BaseModel, Field, field_validator


#Requests

class OrderSubmit(BaseModel):
    symbol: str = Field(examples=["BTC-USDT"])
    order_type: Literal["market", "limit", "ioc", "fok"]
    side: Literal["buy", "sell"]
    quantity: str = Field(..., examples=["0.5"])
    price: Optional[str] = Field(None, examples=["62000.10"]) 

    @field_validator("quantity")
    @classmethod
    def _qty_pos(cls, v: str) -> str:
        if Decimal(v) <= 0:
            raise ValueError("quantity must be > 0")
        return v

    @field_validator("price")
    @classmethod
    def _price_pos_if_present(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and Decimal(v) <= 0:
            raise ValueError("price must be > 0 when provided")
        return v


#Responses

class TradeReport(BaseModel):
    timestamp: datetime
    symbol: str
    trade_id: str
    price: str
    quantity: str
    aggressor_side: Literal["buy", "sell"]
    maker_order_id: str
    taker_order_id: str

class OrderSubmitResult(BaseModel):
    order_id: str
    fully_filled: bool
    resting: bool
    trades: List[TradeReport]

class BBO(BaseModel):
    bid: Optional[dict]  
    ask: Optional[dict]

class L2Depth(BaseModel):
    symbol: str
    bids: list[list[str]]
    asks: list[list[str]]
