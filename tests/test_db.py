from sqlalchemy import func, select
from sqlalchemy.pool import NullPool

from permapp.db import (
    init_db,
    miniapp_grants,
    miniapps,
    normalize_db_url,
    reset_db,
    system_grants,
    users,
)


def test_normalize_db_url():
    assert normalize_db_url(None) == "sqlite:///./local.db"
    assert normalize_db_url("postgres://u:p@h/db?sslmode=require") == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert normalize_db_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_db_url("sqlite:///x.db") == "sqlite:///x.db"


def test_init_db_seeds_once(engine):
    init_db(engine)  # second call
    with engine.connect() as c:
        assert c.execute(select(func.count()).select_from(users)).scalar() == 3
        assert c.execute(select(func.count()).select_from(miniapps)).scalar() == 3
        roles = dict(c.execute(select(users.c.username, users.c.role)).all())
    assert roles == {"admin": "admin", "user1": "user", "user2": "user"}


def test_reset_clears_grants(engine):
    with engine.begin() as c:
        c.execute(system_grants.insert().values(username="user1", miniapp_id="leave"))
        c.execute(miniapp_grants.insert().values(username="user1", miniapp_id="leave"))
    reset_db(engine)
    with engine.connect() as c:
        assert c.execute(select(func.count()).select_from(system_grants)).scalar() == 0
        assert c.execute(select(func.count()).select_from(miniapp_grants)).scalar() == 0
        assert c.execute(select(func.count()).select_from(users)).scalar() == 3


def test_postgres_engine_is_pgbouncer_safe(monkeypatch):
    import permapp.db as db
    seen = {}

    def spy(url, **kwargs):
        seen.update(kwargs, url=url)

    monkeypatch.setattr(db, "create_engine", spy)
    db.make_engine("postgresql+psycopg://u:p@h/db?sslmode=require")
    assert seen["poolclass"] is NullPool
    assert seen["connect_args"] == {"prepare_threshold": None}  # PgBouncer transaction mode
