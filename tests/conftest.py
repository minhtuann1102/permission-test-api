import pytest

from permapp.db import init_db, make_engine


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch):
    for name in ("ADMIN_API_KEY", "PUBLIC_HOST", "DATABASE_URL", "POSTGRES_URL"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(f"sqlite:///{tmp_path}/t.db")
    init_db(eng)
    yield eng
    eng.dispose()
