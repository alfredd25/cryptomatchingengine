from __future__ import annotations

import itertools
from dataclasses import dataclass
from decimal import Decimal
from typing import List, Optional, Tuple

from src.common.types import OrderType, Side
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
    Matching engine for a SINGLE symbol.
    - Strict price-time: consume best price levels first, FIFO within level.
    - Internal order protection: never skip a better price to trade at worse.
    - Supports: MARKET, LIMIT (marketable or resting), IOC, FOK.
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.book = OrderBook(symbol)
        self._trade_seq = itertools.count(1)

    # ---------- Public API ----------

    def submit(self, incoming: Order) -> MatchResult:
        if incoming.symbol != self.symbol:
            raise ValueError("Symbol mismatch for this engine")

        if incoming.is_fok:
            if not self._is_fully_fillable_now(incoming):
                incoming.active = False
                return MatchResult(trades=[], fully_filled=False, resting=False)

        trades: List[Trade] = []
        original_qty = incoming.remaining

        if incoming.side is Side.BUY:
            trades = self._aggress(incoming, is_buy=True)
        else:
            trades = self._aggress(incoming, is_buy=False)

        executed = original_qty - incoming.remaining
        fully_filled = incoming.remaining == Decimal("0")

        if incoming.is_ioc:
            incoming.active = False
            incoming.remaining = Decimal("0")
            return MatchResult(
                trades=trades,
                fully_filled=(executed == original_qty),
                resting=False,
            )

        rested = False
        if (not fully_filled) and incoming.is_limit:
            self.book.add_order(incoming)
            rested = True

        return MatchResult(trades=trades, fully_filled=fully_filled, resting=rested)

    # ---------- Core matching (Logic for price-time priority) ----------
    def _is_price_ok_for(self, inc: Order, is_buy: bool, best_price: Decimal) -> bool:
        """
        MARKET: always OK (price None).
        LIMIT/IOC/FOK with price:
          - BUY accepts best_price <= limit
          - SELL accepts best_price >= limit
        """
        if inc.price is None:
            return True

        if is_buy:
            return best_price <= inc.price
        else:
            return best_price >= inc.price

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

            if not self._is_price_ok_for(inc, is_buy, best_price):
                break

            level_map = self.book.asks if is_buy else self.book.bids
            level: Optional[PriceLevel] = level_map.get(best_price)
            if not level:
                continue

            while inc.remaining > 0:
                head = level.front()
                if head is None:
                    if best_price in level_map:
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

        return trades

    # ---------- FOK availability pre-check ----------

    def _is_fully_fillable_now(self, inc: Order) -> bool:
        """
        Check if the *entire* quantity of 'inc' can be filled immediately
        at prices that respect the order's limit (if any).
        MARKET FOK: aggregate across all prices on the opposite book.
        LIMIT FOK: only aggregate up to the limit price (<= for buys, >= for sells).
        """
        need = inc.remaining

        if inc.side is Side.BUY:
            total = Decimal("0")
            for i in range(len(self.book.asks)):
                price, level = self.book.asks.peekitem(i)
                level.pop_front_if_empty()
                if level.total_qty <= 0:
                    continue
                if inc.is_limit and inc.price is not None and price > inc.price:
                    break
                total += level.total_qty
                if total >= need:
                    return True
            return False
        else:
            total = Decimal("0")
            for i in range(1, len(self.book.bids) + 1):
                price, level = self.book.bids.peekitem(-i)
                level.pop_front_if_empty()
                if level.total_qty <= 0:
                    continue
                if inc.is_limit and inc.price is not None and price < inc.price:
                    break
                total += level.total_qty
                if total >= need:
                    return True
            return False
    
    def bbo(self) -> dict:
        """
        Return current Best Bid/Offer in a JSON-friendly structure:
        {
          "bid": {"price": "62100", "qty": "0.5"} | None,
          "ask": {"price": "62200", "qty": "0.7"} | None
        }
        """
        bb = self.book.best_bid()
        ba = self.book.best_ask()
        def pack(p):
            return None if p is None else {"price": str(p[0]), "qty": str(p[1])}
        return {"bid": pack(bb), "ask": pack(ba)}

    def l2(self, top_n: int = 10) -> dict:
        """
        Return top-N depth snapshot:
        {
          "bids": [["price","qty"], ...],  # highest -> lower
          "asks": [["price","qty"], ...]   # lowest -> higher
        }
        """
        from src.common.types import Side

        bids = self.book.depth(Side.BUY, top_n=top_n)
        asks = self.book.depth(Side.SELL, top_n=top_n)

    
        return {
            "bids": [list(x) for x in bids],
            "asks": [list(x) for x in asks],
        }
