import uuid
import asyncpg
from decimal import Decimal
from typing import Optional, Dict

from src.common.types import Side, OrderType
from src.engine.matching_engine import MatchingEngine, MatchResult
from src.engine.order import Order
from src.engine.trade import Trade
from src.infrastructure.db import get_pool
from src.infrastructure.event_store import EventStore
from src.common.logging import get_logger

LOGGER = get_logger("application.order_service")

# A global registry of engines for the application orchestrator
_engines: Dict[str, MatchingEngine] = {}

def get_engine(symbol: str) -> MatchingEngine:
    if symbol not in _engines:
        # Engine is created purely in-memory upon valid first request
        _engines[symbol] = MatchingEngine(symbol)
    return _engines[symbol]


class OrderService:
    """
    Orchestrates the order submission process:
    Client -> Persist Event (WAL) -> In-Memory Match -> Emit Trades.
    """

    @staticmethod
    async def place_order(
        symbol: str,
        side: Side,
        order_type: OrderType,
        quantity: Decimal,
        price: Optional[Decimal],
        idempotency_key: str
    ) -> dict:
        """
        Process a new order symmetrically writing WAL events and interacting with the Engine.
        """
        pool = get_pool()
        
        # 1. Begin DB Transaction to persist the incoming event
        async with pool.acquire() as conn:
            async with conn.transaction():
                order_id = uuid.uuid4()
                
                try:
                    # Append ORDER_PLACED to WAL
                    await EventStore.append_event(
                        conn=conn,
                        event_type="ORDER_PLACED",
                        order_id=order_id,
                        symbol=symbol,
                        side=side.value,
                        order_type=order_type.value,
                        quantity=quantity,
                        price=price,
                        idempotency_key=idempotency_key
                    )
                except asyncpg.exceptions.UniqueViolationError:
                    LOGGER.warning(f"Duplicate idempotency_key detected: {idempotency_key}")
                    # If this is a duplicate request, we simply fetch the original event
                    # We can't easily return the exact `MatchResult` because the engine processed it
                    # theoretically long ago, but we CAN indicate it was already handled successfully.
                    prev_event = await EventStore.fetch_event_by_idempotency_key(idempotency_key)
                    return {
                        "status": "Idempotent Processed",
                        "original_order_id": str(prev_event["order_id"]) if prev_event else None,
                        "message": "Order was previously successfully accepted."
                    }

                # 2. Transaction commit happens at the end of the `async with` block.
                # However we want to wait for commit BEFORE applying to engine. 
                # So we break the transaction early or we just let it commit and THEN apply.
                pass 
        
        # 3. Tx is committed. Safely apply to the deterministic engine
        engine = get_engine(symbol)
        
        order = Order(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price
        )
        
        match_result: MatchResult = engine.submit(order)
        
        # 4. If trades occur, we can optionally store them as TRADE_EXECUTED events
        if match_result.trades:
            # We open a new, lightweight insert to log trades (they don't mutate state strictly on replay, but are good for auditing)
             async with pool.acquire() as trade_conn:
                for trade in match_result.trades:
                     try:
                        query = """
                            INSERT INTO order_events (
                                event_type, order_id, symbol, side, order_type, quantity, price
                            ) VALUES (
                                $1, $2, $3, $4, $5, $6, $7
                            )
                        """
                        # Normally a trade involves *two* orders, for simplicity of the event store 
                        # we can log that the *aggressor* executed a trade at a price
                        await trade_conn.execute(
                            query,
                            "TRADE_EXECUTED",
                            order_id,
                            symbol,
                            side.value,
                            order_type.value,
                            trade.qty,
                            trade.price
                        )
                     except Exception as e:
                         LOGGER.error(f"Failed to record trade event: {e}")
        
        return {
            "status": "Accepted",
            "order_id": str(order_id),
            "fully_filled": match_result.fully_filled,
            "resting": match_result.resting,
            "trades": [
                 {
                     "trade_id": str(t.trade_id), 
                     "price": str(t.price), 
                     "qty": str(t.qty), 
                     "maker_order_id": str(t.maker_order_id),
                     "aggressor_side": t.aggressor_side
                 }
                 for t in match_result.trades
            ]
        }

    @staticmethod
    async def cancel_order(symbol: str, order_id: str) -> bool:
        """
        Cancel an order, ensuring a WAL cancellation event is written first.
        """
        pool = get_pool()
        
        # 1. We must verify the engine even knows about this order, otherwise don't write event
        engine = get_engine(symbol)
        if not engine.book.has_order(order_id):
             return False
             
        # 2. Persist WAL EVENT (No idempotency key needed for explicit cancellations)
        async with pool.acquire() as conn:
              await EventStore.append_event(
                        conn=conn,
                        event_type="ORDER_CANCELLED",
                        order_id=uuid.UUID(order_id),
                        symbol=symbol,
                        side="CANCEL", # Dummy padding
                        order_type="CANCEL",
                        quantity=Decimal("0"),
                        price=None
                    )
        
        # 3. Apply to engine
        return engine.cancel(order_id)
