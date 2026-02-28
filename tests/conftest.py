
import pytest
from unittest.mock import AsyncMock, patch
from src.api.main import SUPPORTED_SYMBOLS
from src.application.order_service import _engines, get_engine
from src.engine.matching_engine import MatchingEngine

@pytest.fixture(autouse=True)
def mock_db_and_engine_state():
    """
    Ensure a fresh in-memory MatchingEngine for every test, for every supported symbol.
    Also mocks the EventStore and DB Pool so unit tests don't require Postgres.
    """
    # 1. Reset Engines
    _engines.clear()
    for sym in list(SUPPORTED_SYMBOLS):
        _engines[sym] = MatchingEngine(sym)
        
    # 2. Mock Database infrastructure globally for tests
    with patch("src.application.order_service.EventStore.append_event", new_callable=AsyncMock) as mock_append, \
         patch("src.application.order_service.get_pool"), \
         patch("src.infrastructure.db.get_pool"), \
         patch("src.infrastructure.db.init_db", new_callable=AsyncMock), \
         patch("src.infrastructure.db.close_db", new_callable=AsyncMock):
        yield
