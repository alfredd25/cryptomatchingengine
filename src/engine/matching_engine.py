from __future__ import annotations
import itertools
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Tuple, Optional

from src.common.types import Side, OrderType, to_decimal
from src.engine.order import Order
from src.engine.order_book import OrderBook, PriceLevel
from src.engine.trade import Trade


@dataclass
class MatchResult:
    trades: List[Trade]
    fully_filled: bool
    resting: bool 


class MatchingEngine:
    """
    Minimal matching brain for a SINGLE symbol.
    - Strict price-time: consume best price levels first, FIFO within level.
    - Internal order protection: never skip a better price to trade at worse.
    - Today: supports MARKET + marketable LIMIT (IOC/FOK in next steps).
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.book = OrderBook(symbol)
        self._trade_seq = itertools.count(1) 


    def submit(self, incoming: Order) -> MatchResult:
        if incoming.symbol != self.symbol:
            raise ValueError("Symbol mismatch for this engine")

        trades: List[Trade] = []

        if incoming.side is Side.BUY:
            trades = self._aggress(incoming, is_buy=True)
        else:
            trades = self._aggress(incoming, is_buy=False)

        fully_filled = incoming.is_fully_filled()

        rested = False
        if (not fully_filled) and incoming.is_limit:
            self.book.add_order(incoming)
            rested = True

        return MatchResult(trades=trades, fully_filled=fully_filled, resting=rested)


    def _aggress(self, inc: Order, is_buy: bool) -> List[Trade]:
        """
        Consume the opposite side from best price outward.
        BUY consumes ASKS where ask_price <= inc.price (or any for market).
        SELL consumes BIDS where bid_price >= inc.price (or any for market).
        """
        trades: List[Trade] = []

        while inc.remaining > 0:
            best = self.book.best_ask() if is_buy else self.book.best_bid()
            if best is None:
                break  

            best_price, _level_qty = best

            if inc.is_limit:
                if is_buy and best_price > (inc.price or best_price):
                    break  
                if (not is_buy) and best_price < (inc.price or best_price):
                    break

            level_map = self.book.asks if is_buy else self.book.bids
            level: Optional[PriceLevel] = level_map.get(best_price)
            if not level:
                continue

            while inc.remaining > 0:
                head = level.front()
                if head is None:
                    del level_map[best_price]
                    break

                take = min(inc.remaining, head.remaining)
                level.deduct_from_front(take)
                inc.reduce(take)

                t = Trade(
                    ts=Trade.now_ts(),
                    symbol=self.symbol,
                    trade_id=f"T{next(self._trade_seq)}",
                    price=best_price,
                    qty=take,
                    aggressor_side="buy" if is_buy else "sell",
                    maker_order_id=str(head.order_id),
                    taker_order_id=str(inc.order_id),
                )
                trades.append(t)

                if level.front() is None:
                    if best_price in level_map:
                        if level.total_qty <= Decimal("0"):
                            del level_map[best_price]
                    break 

        return trades
