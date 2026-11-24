"""Database schema, engine creation, seeding and reset.

SQLite locally/tests, Postgres (Neon) on Vercel, same SQLAlchemy Core code.
"""
import functools
import os

from sqlalchemy import (
    Boolean,
    Column,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
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
    # Mock org data used by the eligibility rules. Blank values are "" (never null in responses).
    Column("department", String(128), nullable=True),
    Column("title", String(128), nullable=True),
    Column("manager_email", String(254), nullable=True),  # direct manager, need not be an account here
    Column("status", String(16), nullable=True),  # 'ACTIVE' | 'RESIGNED'
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

# Eligibility rules: each row is one way to qualify for (miniapp_id, role). A user qualifies when
# their department equals `department`, OR their title contains `title_keyword` (case-insensitive).
# A (miniapp, role) pair with no rows is open to everyone. Blank columns are "".
role_rules = Table(
    "role_rules",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("miniapp_id", String(64), nullable=False),
    Column("role", String(32), nullable=False),
    Column("department", String(128), nullable=False),
    Column("title_keyword", String(128), nullable=False),
    UniqueConstraint("miniapp_id", "role", "department", "title_keyword", name="uq_role_rules"),
)

# Change log of the two permission tiers: one row per real change, made by the console or the agent.
# Levels: none | see | use | <member role> (e.g. learner, instructor).
permission_log = Table(
    "permission_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("at", String(32), nullable=False),  # UTC ISO timestamp
    Column("actor", String(16), nullable=False),  # console | agent
    Column("action", String(16), nullable=False),  # Grant | ChangeRole | RevokeUse | RevokeAll
    Column("username", String(64), nullable=False),
    Column("miniapp_id", String(64), nullable=False),
    Column("from_level", String(32), nullable=False),
    Column("to_level", String(32), nullable=False),
    Column("detail", String(512), nullable=False),
)

# ---------- Đánh giá (performance reviews) ----------
# A mock of the appraisal system behind the "Đánh giá" tickets: periods (kỳ đánh giá), each employee's
# form (phiếu) with goals/criteria (mục tiêu / tiêu chí) and evaluators (người đánh giá), uploaded
# results (kết quả HQCV) and an audit log. Dates are ISO strings 'YYYY-MM-DD'. Blank values are "".

review_periods = Table(
    "review_periods",
    metadata,
    Column("id", String(64), primary_key=True),  # e.g. VINFAST-Q4-2026
    Column("name", String(128), nullable=False),
    Column("company", String(64), nullable=False),
    Column("kind", String(16), nullable=False),  # KPI_MONTH | KPI_QUARTER | KPI_YEAR | REVIEW_360
    Column("start_date", String(10), nullable=False),
    Column("deadline", String(10), nullable=False),
    Column("original_deadline", String(10), nullable=False),  # extensions are capped from this date
    Column("status", String(16), nullable=False),  # OPEN | CLOSED | LOCKED (results finalised)
    Column("extension_count", Integer, nullable=False),
)

review_forms = Table(
    "review_forms",
    metadata,
    Column("id", String(32), primary_key=True),  # e.g. RF-1001
    Column("period_id", String(64), nullable=False),  # "" for probation / contract forms
    Column("username", String(64), nullable=False),
    Column("kind", String(16), nullable=False),  # KPI | REVIEW_360 | PROBATION | CONTRACT
    Column("status", String(16), nullable=False),  # DRAFT | SUBMITTED | APPROVED | LOCKED
    Column("deadline", String(10), nullable=False),  # personal deadline; "" = the period's deadline
    Column("base_deadline", String(10), nullable=False),  # first deadline of a form without period
    Column("reopen_count", Integer, nullable=False),
    Column("extension_count", Integer, nullable=False),
)

review_evaluators = Table(
    "review_evaluators",
    metadata,
    Column("form_id", String(32), primary_key=True),
    Column("email", String(254), primary_key=True),
    Column("relation", String(16), nullable=False),  # manager | peer | subordinate
)

review_goals = Table(
    "review_goals",
    metadata,
    Column("id", String(32), primary_key=True),  # e.g. G-1001-3
    Column("form_id", String(32), nullable=False),
    Column("title", String(256), nullable=False),
    Column("weight", Integer, nullable=False),  # percent
    Column("target", String(128), nullable=False),
    Column("created_by", String(16), nullable=False),  # employee | manager
)

review_results = Table(
    "review_results",
    metadata,
    Column("period_id", String(64), primary_key=True),
    Column("username", String(64), primary_key=True),
    Column("score", Integer, nullable=False),
    Column("grade", String(4), nullable=False),
)

review_log = Table(
    "review_log",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("at", String(32), nullable=False),  # UTC ISO timestamp
    Column("ticket", String(32), nullable=False),  # always "" now (no tickets in the system); kept for old DBs
    Column("actor", String(16), nullable=True),  # console | agent; NULL on old rows reads as agent
    Column("action", String(64), nullable=False),  # operationId of the write
    Column("target", String(64), nullable=False),  # period, form or goal id
    Column("detail", String(1024), nullable=False),
)

REVIEW_TABLES = [review_log, review_results, review_goals, review_evaluators, review_forms, review_periods]


def _period(pid, name, company, kind, start, deadline, status):
    return {"id": pid, "name": name, "company": company, "kind": kind, "start_date": start,
            "deadline": deadline, "original_deadline": deadline, "status": status, "extension_count": 0}


def _form(fid, period_id, username, kind, status, deadline=""):
    return {"id": fid, "period_id": period_id, "username": username, "kind": kind, "status": status,
            "deadline": deadline, "base_deadline": deadline, "reopen_count": 0, "extension_count": 0}


def _goal(gid, form_id, title, weight, target, created_by="employee"):
    return {"id": gid, "form_id": form_id, "title": title, "weight": weight, "target": target,
            "created_by": created_by}


def _ev(form_id, email, relation="manager"):
    return {"form_id": form_id, "email": email, "relation": relation}


SEED_REVIEW_PERIODS = [
    _period("VINFAST-Q3-2026", "KPI quý 3/2026 - VinFast", "VinFast", "KPI_QUARTER", "2026-07-01", "2026-10-15", "CLOSED"),
    _period("VINFAST-Q4-2026", "KPI quý 4/2026 - VinFast", "VinFast", "KPI_QUARTER", "2026-10-01", "2026-11-30", "OPEN"),
    _period("VINFAST-360-2026", "Đánh giá 360 năm 2026 - VinFast", "VinFast", "REVIEW_360", "2026-11-01", "2026-11-28", "OPEN"),
    _period("VINHOMES-Q1-2026", "KPI quý 1/2026 - Vinhomes", "Vinhomes", "KPI_QUARTER", "2026-01-01", "2026-04-15", "LOCKED"),
    _period("VINHOMES-Q2-2026", "KPI quý 2/2026 - Vinhomes", "Vinhomes", "KPI_QUARTER", "2026-04-01", "2026-07-15", "CLOSED"),
    _period("VINHOMES-T11-2026", "KPI tháng 11/2026 - Vinhomes", "Vinhomes", "KPI_MONTH", "2026-11-01", "2026-12-05", "OPEN"),
]

SEED_REVIEW_FORMS = [
    _form("RF-1001", "VINFAST-Q4-2026", "user1", "KPI", "DRAFT"),
    _form("RF-1002", "VINFAST-Q4-2026", "user2", "KPI", "APPROVED"),
    _form("RF-1003", "VINFAST-360-2026", "user1", "REVIEW_360", "DRAFT"),
    _form("RF-1004", "", "user2", "PROBATION", "DRAFT", "2026-11-30"),
    _form("RF-1005", "", "user1", "CONTRACT", "SUBMITTED", "2026-12-10"),
    _form("RF-1006", "VINFAST-Q4-2026", "user3", "KPI", "DRAFT"),
    _form("RF-1007", "VINHOMES-Q1-2026", "user2", "KPI", "APPROVED"),
    _form("RF-1008", "VINHOMES-Q2-2026", "user2", "KPI", "DRAFT"),
    _form("RF-1009", "VINHOMES-T11-2026", "user1", "KPI", "SUBMITTED"),
]

SEED_REVIEW_EVALUATORS = [
    _ev("RF-1001", "truongphong.daotao@demo.local"),
    _ev("RF-1002", "truongphong.kinhdoanh@demo.local"),
    _ev("RF-1003", "truongphong.daotao@demo.local"),
    _ev("RF-1003", "user2@demo.local", "peer"),
    _ev("RF-1003", "nguyen.van.a@demo.local", "peer"),
    _ev("RF-1004", "pham.van.cu@demo.local"),  # former manager, moved to another unit
    _ev("RF-1005", "truongphong.daotao@demo.local"),
    _ev("RF-1006", "truongphong.kinhdoanh@demo.local"),
    _ev("RF-1007", "truongphong.kinhdoanh@demo.local"),
    _ev("RF-1008", "truongphong.kinhdoanh@demo.local"),
    _ev("RF-1009", "truongphong.daotao@demo.local"),
]

SEED_REVIEW_GOALS = [
    _goal("G-1001-1", "RF-1001", "Tổ chức khóa đào tạo nội bộ", 40, "12 khóa"),
    _goal("G-1001-2", "RF-1001", "Tỷ lệ học viên hài lòng", 40, ">= 90%"),
    _goal("G-1001-3", "RF-1001", "Tổ chức khóa đào tạo nội bộ (tạo trùng)", 20, "12 khóa"),
    _goal("G-1002-1", "RF-1002", "Doanh số quý 4", 50, "15 tỷ"),
    _goal("G-1002-2", "RF-1002", "Khách hàng mới", 30, "20 khách hàng"),
    _goal("G-1002-3", "RF-1002", "Doanh số quý 4 (nhập sai đơn vị)", 20, "15 triệu"),
    _goal("G-1004-1", "RF-1004", "Hoàn thành đào tạo hội nhập", 30, "100%", "manager"),
    _goal("G-1004-2", "RF-1004", "Đạt chỉ tiêu doanh số thử việc", 50, ">= 80%", "manager"),
    _goal("G-1004-3", "RF-1004", "Tuân thủ nội quy", 20, "Không vi phạm", "manager"),
    _goal("G-1005-1", "RF-1005", "Chất lượng công việc", 40, "Đạt", "manager"),
    _goal("G-1005-2", "RF-1005", "Thái độ, tác phong", 30, "Đạt", "manager"),
    _goal("G-1005-3", "RF-1005", "Kỹ năng bán hàng (sai vị trí)", 15, "Đạt", "manager"),
    _goal("G-1005-4", "RF-1005", "Doanh số cá nhân (sai vị trí)", 15, "5 tỷ", "manager"),
    _goal("G-1006-1", "RF-1006", "Doanh số quý 4", 100, "10 tỷ"),
    _goal("G-1007-1", "RF-1007", "Doanh số quý 1", 100, "12 tỷ"),
    _goal("G-1008-1", "RF-1008", "Doanh số quý 2", 70, "12 tỷ"),
    _goal("G-1008-2", "RF-1008", "Khách hàng mới", 30, "15 khách hàng"),
    _goal("G-1009-1", "RF-1009", "Số khóa học mở trong tháng", 100, "3 khóa"),
]

SEED_USERS = [
    {"username": "admin", "api_key": None, "role": "admin", "display_name": "Quản trị viên",
     "email": "admin@demo.local", "department": "Phòng CNTT", "title": "Quản trị hệ thống",
     "manager_email": "", "status": "ACTIVE"},
    {"username": "user1", "api_key": "user1-key-123", "role": "user", "display_name": "Người dùng 1",
     "email": "user1@demo.local", "department": "Phòng Đào tạo (L&D)", "title": "Chuyên viên đào tạo",
     "manager_email": "truongphong.daotao@demo.local", "status": "ACTIVE"},
    {"username": "user2", "api_key": "user2-key-123", "role": "user", "display_name": "Người dùng 2",
     "email": "user2@demo.local", "department": "Phòng Kinh doanh", "title": "Nhân viên kinh doanh",
     "manager_email": "truongphong.kinhdoanh@demo.local", "status": "ACTIVE"},
    {"username": "user3", "api_key": "user3-key-123", "role": "user", "display_name": "Người dùng 3",
     "email": "user3@demo.local", "department": "Phòng Kinh doanh", "title": "Nhân viên kinh doanh",
     "manager_email": "truongphong.kinhdoanh@demo.local", "status": "RESIGNED"},
]

ORG_COLUMNS = ["email", "department", "title", "manager_email", "status"]

SEED_ROLE_RULES = [
    {"miniapp_id": "lms", "role": "instructor", "department": "Phòng Đào tạo (L&D)", "title_keyword": ""},
    {"miniapp_id": "lms", "role": "instructor", "department": "", "title_keyword": "giảng viên"},
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
    ("users", "department", "VARCHAR(128)"),
    ("users", "title", "VARCHAR(128)"),
    ("users", "manager_email", "VARCHAR(254)"),
    ("users", "status", "VARCHAR(16)"),
    ("miniapps", "always_visible", "BOOLEAN"),
    ("miniapps", "roles", "VARCHAR(256)"),
    ("miniapp_grants", "role", "VARCHAR(32)"),
    ("review_log", "actor", "VARCHAR(16)"),
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


def _seed_role_rules(engine):
    for rule in SEED_ROLE_RULES:
        try:
            with engine.begin() as c:
                exists = c.execute(select(role_rules.c.id).where(
                    *(role_rules.c[k] == v for k, v in rule.items())
                )).first()
                if exists is None:
                    c.execute(role_rules.insert().values(**rule))
        except IntegrityError:
            pass  # a concurrent cold start inserted it first


def _seed_reviews(engine):
    """Seed the review tables once, while they are empty (new tables on an old database, or after reset)."""
    try:
        with engine.begin() as c:
            if c.execute(select(review_periods.c.id)).first() is not None:
                return
            c.execute(review_periods.insert(), SEED_REVIEW_PERIODS)
            c.execute(review_forms.insert(), SEED_REVIEW_FORMS)
            c.execute(review_evaluators.insert(), SEED_REVIEW_EVALUATORS)
            c.execute(review_goals.insert(), SEED_REVIEW_GOALS)
    except IntegrityError:
        pass  # a concurrent cold start seeded it first


def init_db(engine):
    _create_schema(engine)
    for table_name, column, sql_type in LATE_COLUMNS:
        _ensure_column(engine, table_name, column, sql_type)
    for row in _seed_users():
        _insert_if_absent(engine, users, users.c.username, row)
    for row in SEED_MINIAPPS:
        _insert_if_absent(engine, miniapps, miniapps.c.id, row)
    _backfill(engine, users, users.c.username, SEED_USERS, ORG_COLUMNS)
    _backfill(engine, miniapps, miniapps.c.id, SEED_MINIAPPS, ["always_visible", "roles"])
    with engine.begin() as c:  # memberships granted before roles existed have no role
        c.execute(update(miniapp_grants).where(miniapp_grants.c.role.is_(None)).values(role=""))
    _seed_role_rules(engine)
    _seed_reviews(engine)


def reset_db(engine):
    """Remove every grant and restore seed users, miniapps, eligibility rules and review data."""
    _create_schema(engine)
    for table_name, column, sql_type in LATE_COLUMNS:
        _ensure_column(engine, table_name, column, sql_type)
    with engine.begin() as c:
        c.execute(delete(permission_log))
        c.execute(delete(miniapp_grants))
        c.execute(delete(system_grants))
        c.execute(delete(role_rules))
        for table in REVIEW_TABLES:
            c.execute(delete(table))
        for row in _seed_users():
            c.execute(update(users).where(users.c.username == row["username"]).values(**row))
        for row in SEED_MINIAPPS:
            c.execute(update(miniapps).where(miniapps.c.id == row["id"]).values(**row))
    init_db(engine)
