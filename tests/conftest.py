
import pytest
from src.api.main import _engines, SUPPORTED_SYMBOLS
from src.engine.matching_engine import MatchingEngine

@pytest.fixture(autouse=True)
def reset_engine_state():
    """
    Ensure a fresh in-memory MatchingEngine for every test, for every supported symbol.
    This prevents cross-test state leaks (e.g., leftover resting orders).
    """
    for sym in list(SUPPORTED_SYMBOLS):
        _engines[sym] = MatchingEngine(sym)
    yield
