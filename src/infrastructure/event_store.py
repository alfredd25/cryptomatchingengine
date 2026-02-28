import uuid
import asyncpg
from decimal import Decimal
from typing import Optional, List, Dict, Any, AsyncGenerator

from src.common.logging import get_logger
from src.infrastructure.db import get_pool

LOGGER = get_logger("infrastructure.event_store")


class EventStore:
    """
    Abstractions for appending and fetching order events.
    Enforces the append-only rule for the WAL.
    """

    @staticmethod
    async def append_event(
        conn: asyncpg.Connection,
        event_type: str,
        order_id: uuid.UUID,
        symbol: str,
        side: str,
        order_type: str,
        quantity: Decimal,
        price: Optional[Decimal],
        idempotency_key: Optional[str] = None
    ) -> int:
        """
        Appends a new event to the order_events table.
        MUST be called within a transaction block (`async with conn.transaction():`).
        
        Raises asyncpg.exceptions.UniqueViolationError if idempotency_key is duplicate.
        """
        
        query = """
            INSERT INTO order_events (
                event_type, order_id, symbol, side, order_type, quantity, price, idempotency_key
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8
            ) RETURNING id;
        """
        
        event_id: int = await conn.fetchval(
            query,
            event_type,
            order_id,
            symbol,
            side,
            order_type,
            quantity,
            price,
            idempotency_key
        )
        return event_id


    @staticmethod
    async def fetch_all_events() -> List[asyncpg.Record]:
        """
        Fetches all events ordered by ID (chronological) for state reconstruction.
        """
        pool = get_pool()
        async with pool.acquire() as conn:
            LOGGER.info("Fetching all historical events for replay...")
            query = "SELECT * FROM order_events ORDER BY id ASC;"
            events = await conn.fetch(query)
            return events

    @staticmethod
    async def fetch_event_by_idempotency_key(idempotency_key: str) -> Optional[asyncpg.Record]:
        """
        Fetches the initial order placement event by idempotency key.
        Useful to return previously processed state.
        """
        pool = get_pool()
        async with pool.acquire() as conn:
            query = """
                SELECT * FROM order_events 
                WHERE idempotency_key = $1 AND event_type = 'ORDER_PLACED' 
                LIMIT 1;
            """
            return await conn.fetchrow(query, idempotency_key)
