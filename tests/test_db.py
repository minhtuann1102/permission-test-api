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


def test_seed_users_have_emails(engine):
    with engine.connect() as c:
        emails = dict(c.execute(select(users.c.username, users.c.email)).all())
    assert emails == {"admin": "admin@demo.local", "user1": "user1@demo.local", "user2": "user2@demo.local"}


def test_init_db_adds_email_column_to_an_old_users_table(tmp_path):
    from sqlalchemy import text

    from permapp.db import make_engine

    eng = make_engine(f"sqlite:///{tmp_path}/old.db")
    with eng.begin() as c:  # the schema before emails existed, already seeded
        c.execute(text("CREATE TABLE users (username VARCHAR(64) PRIMARY KEY, api_key VARCHAR(128) NOT NULL UNIQUE, "
                       "role VARCHAR(16) NOT NULL, display_name VARCHAR(128) NOT NULL)"))
        c.execute(text("INSERT INTO users VALUES ('user1', 'user1-key-123', 'user', 'Người dùng 1')"))
    init_db(eng)
    init_db(eng)  # idempotent
    with eng.connect() as c:
        emails = dict(c.execute(select(users.c.username, users.c.email)).all())
    eng.dispose()
    assert emails["user1"] == "user1@demo.local"
    assert emails["user2"] == "user2@demo.local"


def test_reset_restores_seed_email(engine):
    from sqlalchemy import update

    with engine.begin() as c:
        c.execute(update(users).where(users.c.username == "user1").values(email="changed@x.y"))
    reset_db(engine)
    with engine.connect() as c:
        assert c.execute(select(users.c.email).where(users.c.username == "user1")).scalar() == "user1@demo.local"
