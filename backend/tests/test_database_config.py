from app.database import _engine_kwargs


def test_engine_kwargs_use_bounded_pool_defaults():
    kwargs = _engine_kwargs()

    assert kwargs["echo"] is False
    assert kwargs["pool_size"] == 3
    assert kwargs["max_overflow"] == 0
    assert kwargs["pool_timeout"] == 30
    assert kwargs["pool_recycle"] == 1800
    assert kwargs["pool_pre_ping"] is True
    assert kwargs["pool_use_lifo"] is True
