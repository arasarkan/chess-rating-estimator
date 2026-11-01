import pytest


@pytest.fixture(autouse=True)
def _reset_rate_limiter():
    """Hız sınırlayıcı süreç geneli; testler birbirinin kotasını tüketmesin."""
    from chessdex.api import app as app_mod
    app_mod.session_limiter._b.clear()
    yield
