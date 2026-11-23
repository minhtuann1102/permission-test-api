import pytest

from permapp.db import init_db, make_engine


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    for name in ("ADMIN_API_KEY", "PUBLIC_HOST", "DATABASE_URL", "POSTGRES_URL"):
        monkeypatch.delenv(name, raising=False)


ADMIN = {"X-API-Key": "admin-key-123"}
U1 = {"X-API-Key": "user1-key-123"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    import app as app_module
    from permapp.db import get_engine

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/api.db")
    get_engine.cache_clear()
    app_module._db_ready = False
    with TestClient(app_module.app) as c:
        yield c
    get_engine().dispose()
    get_engine.cache_clear()
    app_module._db_ready = False


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(eng)
    yield eng
    eng.dispose()
