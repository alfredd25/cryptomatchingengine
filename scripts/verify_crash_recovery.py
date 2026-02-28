import asyncio
import uuid
from decimal import Decimal

from src.common.types import Side, OrderType
from src.application.order_service import OrderService, get_engine
from src.api.main import lifespan
from src.infrastructure.db import get_pool

async def run_crash_recovery():
    print("Testing Crash Recovery (WAL Replay)...")
    
    # 1. Start application and populate DB
    async with lifespan(None):
        engine = get_engine("BTC-USDT")
        
        # We start by placing orders to create a known book state
        # Then we cancel one, and match another
        print("--- PHASE 1: Populate State ---")
        
        await OrderService.place_order("BTC-USDT", Side.BUY, OrderType.LIMIT, Decimal("1.0"), Decimal("61000"), str(uuid.uuid4()))
        await OrderService.place_order("BTC-USDT", Side.BUY, OrderType.LIMIT, Decimal("2.0"), Decimal("61000"), str(uuid.uuid4()))
        # This one will be cancelled
        res_cancel = await OrderService.place_order("BTC-USDT", Side.BUY, OrderType.LIMIT, Decimal("5.0"), Decimal("61000"), str(uuid.uuid4()))
        
        # This sell will aggressively cross the spread and eat the 1.0 limit
        await OrderService.place_order("BTC-USDT", Side.SELL, OrderType.MARKET, Decimal("1.0"), None, str(uuid.uuid4()))
        
        await OrderService.cancel_order("BTC-USDT", res_cancel["order_id"])
        
        # EXPECTED BBO:
        # Best Bid: 61000 @ 2.0 (The first 1.0 was eaten by the market sell, the 5.0 was cancelled)
        bbo = engine.bbo()
        print("Pre-Crash BBO:", bbo)
        assert bbo[0] is not None
        assert bbo[0][0] == Decimal("61000")
        assert bbo[0][1] == Decimal("2.0")
        
    print("--- SERVER CRASHED! (Lifespan exit destroyed matching engines) ---")
    
    # 2. Restart sequence mimicking server reboot
    # Ensure our engine from phase 1 is indeed destroyed by the lifespan context ending
    # Actually wait we need to explicitly clear it since we mocked the globals earlier, let's just assert on the lifespan
    from src.application.order_service import _engines
    _engines.clear()
    
    print("--- PHASE 2: Reboot & Replay ---")
    async with lifespan(None):
        engine_restarted = get_engine("BTC-USDT")
        bbo_restarted = engine_restarted.bbo()
        print("Post-Crash BBO:", bbo_restarted)
        
        assert bbo_restarted[0] is not None
        assert bbo_restarted[0][0] == Decimal("61000")
        assert bbo_restarted[0][1] == Decimal("2.0")
        
        print("CRASH RECOVERY VERIFIED ✅")

if __name__ == "__main__":
    asyncio.run(run_crash_recovery())
