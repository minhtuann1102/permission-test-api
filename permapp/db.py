"""Database schema, engine creation, seeding and reset.

SQLite locally/tests, Postgres (Neon) on Vercel, same SQLAlchemy Core code.
"""
import functools
import os

from sqlalchemy import (
    Boolean,
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
    # Always visible: no system access (tier 1) needed, e.g. the mock LMS.
    Column("always_visible", Boolean, nullable=True),
    # Comma-separated member roles, e.g. "learner,instructor". "" = the miniapp has no roles.
    Column("roles", String(256), nullable=True),
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
    Column("role", String(32), nullable=True),  # "" when the miniapp has no roles
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
    {"id": "leave", "name": "Nghỉ phép", "description": "Đăng ký và duyệt đơn nghỉ phép",
     "always_visible": False, "roles": ""},
    {"id": "expense", "name": "Chi phí", "description": "Đề nghị thanh toán và quản lý chi phí",
     "always_visible": False, "roles": ""},
    {"id": "inventory", "name": "Kho", "description": "Quản lý xuất nhập tồn kho",
     "always_visible": False, "roles": ""},
    {"id": "lms", "name": "LMS", "description": "Học tập trực tuyến (giả lập): học viên học khoá, giảng viên quản lý khoá học",
     "always_visible": True, "roles": "learner,instructor"},
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


# Columns added after the first deploy. Old databases (Neon) get them in place.
LATE_COLUMNS = [
    ("users", "email", "VARCHAR(254)"),
    ("miniapps", "always_visible", "BOOLEAN"),
    ("miniapps", "roles", "VARCHAR(256)"),
    ("miniapp_grants", "role", "VARCHAR(32)"),
]


def _ensure_column(engine, table_name, column, sql_type):
    """Add a column to an existing table if it is missing. Safe to run twice and concurrently."""
    if column in {c["name"] for c in inspect(engine).get_columns(table_name)}:
        return
    ddl = f"ALTER TABLE {table_name} ADD COLUMN {column} {sql_type}"
    if engine.dialect.name == "postgresql":
        ddl = f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column} {sql_type}"
    try:
        with engine.begin() as c:
            c.execute(text(ddl))
    except DBAPIError:
        # A concurrent cold start may have added it first.
        if column not in {c["name"] for c in inspect(engine).get_columns(table_name)}:
            raise


def _backfill(engine, table, key_col, seed_rows, columns):
    """Fill seed values into columns that are still empty (NULL) on seeded rows."""
    with engine.begin() as c:
        for row in seed_rows:
            for col in columns:
                c.execute(
                    update(table)
                    .where(key_col == row[key_col.name], table.c[col].is_(None))
                    .values({col: row[col]})
                )


def init_db(engine):
    _create_schema(engine)
    for table_name, column, sql_type in LATE_COLUMNS:
        _ensure_column(engine, table_name, column, sql_type)
    for row in _seed_users():
        _insert_if_absent(engine, users, users.c.username, row)
    for row in SEED_MINIAPPS:
        _insert_if_absent(engine, miniapps, miniapps.c.id, row)
    _backfill(engine, users, users.c.username, SEED_USERS, ["email"])
    _backfill(engine, miniapps, miniapps.c.id, SEED_MINIAPPS, ["always_visible", "roles"])
    with engine.begin() as c:  # memberships granted before roles existed have no role
        c.execute(update(miniapp_grants).where(miniapp_grants.c.role.is_(None)).values(role=""))


def reset_db(engine):
    """Remove every grant and restore seed users/miniapps to their seed values."""
    _create_schema(engine)
    for table_name, column, sql_type in LATE_COLUMNS:
        _ensure_column(engine, table_name, column, sql_type)
    with engine.begin() as c:
        c.execute(delete(miniapp_grants))
        c.execute(delete(system_grants))
        for row in _seed_users():
            c.execute(update(users).where(users.c.username == row["username"]).values(**row))
        for row in SEED_MINIAPPS:
            c.execute(update(miniapps).where(miniapps.c.id == row["id"]).values(**row))
    init_db(engine)
