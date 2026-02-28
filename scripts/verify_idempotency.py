import asyncio
import uuid
from decimal import Decimal

from src.common.types import Side, OrderType
from src.application.order_service import OrderService
from src.api.main import lifespan
from src.infrastructure.db import get_pool

async def run_idempotency_verification():
    print("Testing Idempotency Constraint...")
    
    # Needs the lifespan to initialize the DB Pool and Run Replay
    async with lifespan(None):
        idemp_key = "verify-idempotency-" + str(uuid.uuid4())
        
        # 1. Place a limit order
        res1 = await OrderService.place_order(
            symbol="BTC-USDT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            quantity=Decimal("1.5"),
            price=Decimal("60000"),
            idempotency_key=idemp_key
        )
        print("First Request:", res1)
        assert res1["status"] == "Accepted"
        
        # 2. Duplicate the exact same request using the SAME key
        res2 = await OrderService.place_order(
            symbol="BTC-USDT",
            side=Side.BUY,
            order_type=OrderType.LIMIT,
            # Different quantity/price simulates a race condition, the DB constraint MUST return the old result!
            quantity=Decimal("100"),
            price=Decimal("99999"),
            idempotency_key=idemp_key
        )
        print("Second Request (Duplicate Key):", res2)
        assert res2["status"] == "Idempotent Processed"
        assert res2["original_order_id"] == res1["order_id"]
        
        print("IDEOMPOTENCY VERIFIED ✅")

if __name__ == "__main__":
    asyncio.run(run_idempotency_verification())
