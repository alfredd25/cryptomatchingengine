from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Deque, Dict, Optional, Tuple

from sortedcontainers import SortedDict

from src.common.types import Side, to_decimal
from src.engine.order import Order
from src.common.logging import get_logger

LOGGER = get_logger("engine.order_book")


@dataclass
class PriceLevel:
    """Holds FIFO queue of orders and maintains total remaining qty for the level."""
    price: Decimal
    queue: Deque[Order]
    total_qty: Decimal

    @staticmethod
    def new(price: Decimal) -> "PriceLevel":
        return PriceLevel(price=price, queue=deque(), total_qty=Decimal("0"))

    def append(self, order: Order) -> None:
        self.queue.append(order)
        self.total_qty += order.remaining

    def remove(self, order: Order) -> None:
        """
        Remove a specific order from the queue
        """
        removed = False
        new_q: Deque[Order] = deque()
        while self.queue:
            o = self.queue.popleft()
            if o is order and not removed:
                self.total_qty -= o.remaining
                removed = True
                continue
            new_q.append(o)
        self.queue = new_q

    def pop_front_if_empty(self) -> bool:
        """Returns True if level became empty (total_qty == 0 or queue empty)."""
        while self.queue and self.queue[0].remaining == 0:
            o = self.queue.popleft()
            self.total_qty -= o.remaining  
        return len(self.queue) == 0 or self.total_qty == 0

    def consume_front(self) -> Optional[Order]:
        """Pop and return the front order if any (used later by matcher)."""
        if not self.queue:
            return None
        o = self.queue.popleft()
        self.total_qty -= o.remaining
        return o
    
    def front(self) -> Order | None:
        """Return the FIFO-front order (skipping any zero-remaining)."""
        while self.queue and self.queue[0].remaining == 0:
            self.queue.popleft()  
        return self.queue[0] if self.queue else None

    def deduct_from_front(self, qty: Decimal) -> Order | None:
        """
        Reduce remaining of the front order by qty, adjust total_qty,
        and pop it if fully filled. Returns the (possibly filled) order.
        """
        if not self.queue:
            return None
        while self.queue and self.queue[0].remaining == 0:
            self.queue.popleft()
        if not self.queue:
            return None

        o = self.queue[0]
        if qty <= 0:
            return o

        take = min(o.remaining, qty)
        self.total_qty -= take
        o.reduce(take)

        if o.remaining == 0:
            self.queue.popleft()  

        return o



class OrderBook:
    """
    OrderBook for a single trading pair (symbol).
    - Bids and asks live in separate SortedDicts keyed by price (Decimal).
    - Price-time priority: each price level is a FIFO queue (deque).
    - We maintain a global sequence counter to stamp orders on insert (for FIFO).
    """

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.asks: SortedDict[Decimal, PriceLevel] = SortedDict()
        self.bids: SortedDict[Decimal, PriceLevel] = SortedDict()
        self._index: Dict[str, Tuple[Side, Decimal, Order]] = {}
        self._seq_counter: int = 0


    def add_order(self, order: Order) -> None:
        """Insert a new order into the appropriate side/price level."""
        if order.symbol != self.symbol:
            raise ValueError("Order symbol does not match order book symbol")
        if order.is_market:
            raise ValueError("Market orders do not rest on the book")

        self._seq_counter += 1
        order.seq = self._seq_counter

        if order.side is Side.BUY:
            level = self.bids.get(order.price)
            if level is None:
                level = PriceLevel.new(order.price) 
                self.bids[order.price] = level 
            level.append(order)
        else:
            level = self.asks.get(order.price)
            if level is None:
                level = PriceLevel.new(order.price)  
                self.asks[order.price] = level  
            level.append(order)

        self._index[str(order.order_id)] = (order.side, order.price or Decimal("0"), order)
        LOGGER.info(
            "ob_add symbol=%s side=%s price=%s qty=%s seq=%s order_id=%s",
            self.symbol,
            order.side.value,
            str(order.price),
            str(order.remaining),
            order.seq,
            str(order.order_id),
        )

    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a resting order by id.
        Returns True if found and removed, False if not found.
        """
        ref = self._index.pop(order_id, None)
        if ref is None:
            return False

        side, price, order = ref

        book = self.bids if side is Side.BUY else self.asks
        level = book.get(price)
        if not level:
            return False  

        level.remove(order)

        order.active = False
        order.remaining = Decimal("0")

        if level.pop_front_if_empty():
            del book[price]
        
        LOGGER.info(
            "ob_cancel symbol=%s side=%s price=%s order_id=%s",
            self.symbol,
            side.value,
            str(price),
            order_id,
        )

        return True


    def best_bid(self) -> Optional[Tuple[Decimal, Decimal]]:
        """
        Returns (price, total_qty) for best bid or None if no bids.
        """
        if not self.bids:
            return None
        price, level = self.bids.peekitem(-1)
        self._refresh_front(level, is_bid=True)
        if level.total_qty <= 0:
            del self.bids[price]
            return self.best_bid()
        return (price, level.total_qty)

    def best_ask(self) -> Optional[Tuple[Decimal, Decimal]]:
        """
        Returns (price, total_qty) for best ask or None if no asks.
        """
        if not self.asks:
            return None
        price, level = self.asks.peekitem(0)
        self._refresh_front(level, is_bid=False)
        if level.total_qty <= 0:
            del self.asks[price]
            return self.best_ask()
        return (price, level.total_qty)

    def bbo(self) -> Tuple[Optional[Tuple[Decimal, Decimal]], Optional[Tuple[Decimal, Decimal]]]:
        """Convenience wrapper returning (best_bid, best_ask)."""
        return (self.best_bid(), self.best_ask())

    def depth(self, side: Side, top_n: int = 10) -> list[Tuple[str, str]]:
        """
        Return top N levels as [("price", "qty"), ...] with both as strings.
        """
        out: list[Tuple[str, str]] = []
        if side is Side.BUY:
            for i in range(1, min(top_n, len(self.bids)) + 1):
                price, level = self.bids.peekitem(-i)
                out.append((str(price), str(level.total_qty)))
        else:
            for i in range(min(top_n, len(self.asks))):
                price, level = self.asks.peekitem(i)
                out.append((str(price), str(level.total_qty)))
        return out


    def _refresh_front(self, level: PriceLevel, is_bid: bool) -> None:
        """
        Clean any zero-remaining orders at the front of the deque.
        (When cancels/partial fills happen, some zeros can linger.)
        """
        level.pop_front_if_empty()

 
    def order_count(self) -> int:
        return len(self._index)


    def has_order(self, order_id: str) -> bool:
        return order_id in self._index
