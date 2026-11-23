"""Database schema, engine creation, seeding and reset.

SQLite locally/tests, Postgres (Neon) on Vercel, same SQLAlchemy Core code.
"""
import functools
import os

from sqlalchemy import (
    Column,
    ForeignKey,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.pool import NullPool

DEFAULT_SQLITE_URL = "sqlite:///./local.db"

metadata = MetaData()

users = Table(
    "users",
    metadata,
    Column("username", String(64), primary_key=True),
    Column("api_key", String(128), nullable=False, unique=True),
    Column("role", String(16), nullable=False),  # 'admin' | 'user'
    Column("display_name", String(128), nullable=False),
    Column("email", String(254), nullable=True),  # mock identity; matched case-insensitively
)

miniapps = Table(
    "miniapps",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", String(128), nullable=False),
    Column("description", String(512), nullable=False),
)

system_grants = Table(
    "system_grants",
    metadata,
    Column("username", String(64), ForeignKey("users.username"), primary_key=True),
    Column("miniapp_id", String(64), ForeignKey("miniapps.id"), primary_key=True),
)

miniapp_grants = Table(
    "miniapp_grants",
    metadata,
    Column("username", String(64), ForeignKey("users.username"), primary_key=True),
    Column("miniapp_id", String(64), ForeignKey("miniapps.id"), primary_key=True),
)

SEED_USERS = [
    {"username": "admin", "api_key": None, "role": "admin", "display_name": "Quản trị viên",
     "email": "admin@demo.local"},
    {"username": "user1", "api_key": "user1-key-123", "role": "user", "display_name": "Người dùng 1",
     "email": "user1@demo.local"},
    {"username": "user2", "api_key": "user2-key-123", "role": "user", "display_name": "Người dùng 2",
     "email": "user2@demo.local"},
]

SEED_MINIAPPS = [
    {"id": "leave", "name": "Nghỉ phép", "description": "Đăng ký và duyệt đơn nghỉ phép"},
    {"id": "expense", "name": "Chi phí", "description": "Đề nghị thanh toán và quản lý chi phí"},
    {"id": "inventory", "name": "Kho", "description": "Quản lý xuất nhập tồn kho"},
]


def normalize_db_url(url):
    """Map env-provided URLs to a SQLAlchemy URL using the psycopg 3 driver."""
    if not url:
        return DEFAULT_SQLITE_URL
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def make_engine(url):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    # prepare_threshold=None: Neon's pooled URL goes through PgBouncer in
    # transaction mode, where psycopg's auto-prepared statements can break.
    return create_engine(
        url,
        poolclass=NullPool,
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None},
    )


@functools.lru_cache(maxsize=None)
def get_engine():
    raw = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_URL")
    return make_engine(normalize_db_url(raw))


def _seed_users():
    admin_key = os.environ.get("ADMIN_API_KEY") or "admin-key-123"
    rows = []
    for row in SEED_USERS:
        row = dict(row)
        if row["username"] == "admin":
            row["api_key"] = admin_key
        rows.append(row)
    return rows


def _insert_if_absent(engine, table, key_col, row):
    # One transaction per row: on Postgres an IntegrityError aborts the whole
    # transaction, so a concurrent cold start must not poison later inserts.
    try:
        with engine.begin() as c:
            exists = c.execute(select(key_col).where(key_col == row[key_col.name])).first()
            if exists is None:
                c.execute(table.insert().values(**row))
    except IntegrityError:
        pass


def _create_schema(engine):
    try:
        metadata.create_all(engine)
    except DBAPIError:
        # Concurrent cold starts on Postgres can race on CREATE TABLE
        # (DuplicateTable / pg_type unique violation). Retry once.
        metadata.create_all(engine)


def _ensure_email_column(engine):
    """Databases created before emails existed (Neon) get the column added in place."""
    if "email" in {c["name"] for c in inspect(engine).get_columns("users")}:
        return
    ddl = "ALTER TABLE users ADD COLUMN email VARCHAR(254)"
    if engine.dialect.name == "postgresql":
        ddl = "ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(254)"
    try:
        with engine.begin() as c:
            c.execute(text(ddl))
    except DBAPIError:
        # A concurrent cold start may have added it first.
        if "email" not in {c["name"] for c in inspect(engine).get_columns("users")}:
            raise


def _backfill_seed_emails(engine):
    with engine.begin() as c:
        for row in SEED_USERS:
            c.execute(
                update(users)
                .where(users.c.username == row["username"], users.c.email.is_(None))
                .values(email=row["email"])
            )


def init_db(engine):
    _create_schema(engine)
    _ensure_email_column(engine)
    for row in _seed_users():
        _insert_if_absent(engine, users, users.c.username, row)
    _backfill_seed_emails(engine)
    for row in SEED_MINIAPPS:
        _insert_if_absent(engine, miniapps, miniapps.c.id, row)


def reset_db(engine):
    """Remove every grant and restore seed users/miniapps to their seed values."""
    _create_schema(engine)
    with engine.begin() as c:
        c.execute(delete(miniapp_grants))
        c.execute(delete(system_grants))
        for row in _seed_users():
            c.execute(update(users).where(users.c.username == row["username"]).values(**row))
        for row in SEED_MINIAPPS:
            c.execute(update(miniapps).where(miniapps.c.id == row["id"]).values(**row))
    init_db(engine)
