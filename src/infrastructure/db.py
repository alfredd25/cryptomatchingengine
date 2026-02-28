import asyncio
import os
from importlib.resources import path
import asyncpg
from dotenv import load_dotenv

from src.common.logging import get_logger

LOGGER = get_logger("infrastructure.db")

load_dotenv()

# Global connection pool
_pool: asyncpg.Pool | None = None

async def init_db() -> None:
    """Initialize the database connection pool using DATABASE_URL."""
    global _pool
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise ValueError("DATABASE_URL environment variable is required")

    LOGGER.info("Initializing database connection pool...")
    _pool = await asyncpg.create_pool(
        dsn=db_url,
        min_size=2,
        max_size=10,
        command_timeout=10,
    )
    LOGGER.info("Database connection pool initialized.")
    await _create_tables()

async def close_db() -> None:
    """Close the database connection pool."""
    global _pool
    if _pool:
        LOGGER.info("Closing database connection pool...")
        await _pool.close()
        _pool = None
        LOGGER.info("Database connection pool closed.")

def get_pool() -> asyncpg.Pool:
    """Get the initialized database connection pool."""
    if _pool is None:
        raise RuntimeError("Database pool is not initialized. Call init_db() first.")
    return _pool

async def _create_tables() -> None:
    """Create necessary tables if they do not exist."""
    pool = get_pool()
    async with pool.acquire() as conn:
        LOGGER.info("Creating tables if not exists...")
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS order_events (
                id BIGSERIAL PRIMARY KEY,
                event_type VARCHAR(50) NOT NULL,
                order_id UUID NOT NULL,
                symbol VARCHAR(20) NOT NULL,
                side VARCHAR(10) NOT NULL,
                order_type VARCHAR(20) NOT NULL,
                quantity NUMERIC NOT NULL,
                price NUMERIC,
                idempotency_key VARCHAR(100) UNIQUE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
            
            -- Index for quick lookups by order_id (e.g. for cancellations)
            CREATE INDEX IF NOT EXISTS idx_order_events_order_id ON order_events(order_id);
            -- Index for replaying per symbol if we ever need it 
            CREATE INDEX IF NOT EXISTS idx_order_events_symbol ON order_events(symbol);
        """)
        LOGGER.info("Tables checked/created.")
