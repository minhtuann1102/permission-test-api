"""Two-tier permission rules (system access -> miniapp membership). No HTTP here."""
from sqlalchemy import and_, delete, func, select
from sqlalchemy.exc import IntegrityError

from permapp.db import miniapp_grants, miniapps, system_grants, users


class ServiceError(Exception):
    def __init__(self, status, code, detail):
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


# ---------- lookups ----------

def _user_row(conn, username):
    row = conn.execute(
        select(users.c.username, users.c.role, users.c.display_name, users.c.email).where(users.c.username == username)
    ).mappings().first()
    if row is None:
        raise ServiceError(404, "USER_NOT_FOUND", f"Không tìm thấy người dùng '{username}'")
    return dict(row)


def _miniapp_row(conn, miniapp_id):
    row = conn.execute(
        select(miniapps.c.id, miniapps.c.name, miniapps.c.description).where(miniapps.c.id == miniapp_id)
    ).mappings().first()
    if row is None:
        raise ServiceError(404, "MINIAPP_NOT_FOUND", f"Không tìm thấy miniapp '{miniapp_id}'")
    return dict(row)


def _has(conn, table, username, miniapp_id):
    return conn.execute(
        select(table.c.username).where(
            and_(table.c.username == username, table.c.miniapp_id == miniapp_id)
        )
    ).first() is not None


def get_user_by_key(engine, api_key):
    if not api_key:
        return None
    with engine.connect() as c:
        row = c.execute(
            select(users.c.username, users.c.role, users.c.display_name, users.c.email).where(users.c.api_key == api_key)
        ).mappings().first()
    return dict(row) if row else None


def list_miniapps(engine):
    with engine.connect() as c:
        rows = c.execute(
            select(miniapps.c.id, miniapps.c.name, miniapps.c.description).order_by(miniapps.c.id)
        ).mappings().all()
    return [dict(r) for r in rows]


def list_visible_miniapps(engine, username):
    with engine.connect() as c:
        user = _user_row(c, username)
        all_apps = c.execute(
            select(miniapps.c.id, miniapps.c.name, miniapps.c.description).order_by(miniapps.c.id)
        ).mappings().all()
        if user["role"] == "admin":
            return [dict(a, can_use=True) for a in all_apps]
        visible = set(c.execute(select(system_grants.c.miniapp_id).where(system_grants.c.username == username)).scalars())
        members = set(c.execute(select(miniapp_grants.c.miniapp_id).where(miniapp_grants.c.username == username)).scalars())
    return [dict(a, can_use=a["id"] in members) for a in all_apps if a["id"] in visible]


def check_access(engine, username, miniapp_id):
    with engine.connect() as c:
        _miniapp_row(c, miniapp_id)
        user = _user_row(c, username)
        if user["role"] == "admin":
            visible = can_use = True
        else:
            visible = _has(c, system_grants, username, miniapp_id)
            can_use = visible and _has(c, miniapp_grants, username, miniapp_id)
    return {"username": username, "miniapp_id": miniapp_id, "visible": visible, "can_use": can_use}


# ---------- grants ----------

def _grant(engine, table, username, miniapp_id, precondition=None):
    """Insert-if-absent. IntegrityError is caught outside the transaction block
    so a Postgres aborted transaction is fully rolled back first."""
    try:
        with engine.begin() as c:
            _miniapp_row(c, miniapp_id)
            _user_row(c, username)
            if precondition:
                precondition(c)
            if _has(c, table, username, miniapp_id):
                already = True
            else:
                c.execute(table.insert().values(username=username, miniapp_id=miniapp_id))
                already = False
    except IntegrityError:
        already = True  # concurrent identical grant won the race
    return {"username": username, "miniapp_id": miniapp_id, "already_granted": already}


def grant_system_access(engine, username, miniapp_id):
    return _grant(engine, system_grants, username, miniapp_id)


def grant_membership(engine, miniapp_id, username):
    def require_system(c):
        if not _has(c, system_grants, username, miniapp_id):
            raise ServiceError(
                409,
                "SYSTEM_ACCESS_REQUIRED",
                f"'{username}' chưa được cấp quyền hệ thống cho miniapp '{miniapp_id}'. "
                "Hãy cấp quyền hệ thống (system access) trước.",
            )
    return _grant(engine, miniapp_grants, username, miniapp_id, precondition=require_system)


def revoke_system_access(engine, username, miniapp_id):
    with engine.begin() as c:
        _miniapp_row(c, miniapp_id)
        _user_row(c, username)
        c.execute(delete(miniapp_grants).where(
            and_(miniapp_grants.c.username == username, miniapp_grants.c.miniapp_id == miniapp_id)))
        res = c.execute(delete(system_grants).where(
            and_(system_grants.c.username == username, system_grants.c.miniapp_id == miniapp_id)))
    return {"username": username, "miniapp_id": miniapp_id, "revoked": res.rowcount > 0}


def revoke_membership(engine, miniapp_id, username):
    with engine.begin() as c:
        _miniapp_row(c, miniapp_id)
        _user_row(c, username)
        res = c.execute(delete(miniapp_grants).where(
            and_(miniapp_grants.c.username == username, miniapp_grants.c.miniapp_id == miniapp_id)))
    return {"username": username, "miniapp_id": miniapp_id, "revoked": res.rowcount > 0}


# ---------- use / overview ----------

def use_miniapp(engine, username, miniapp_id):
    with engine.connect() as c:
        app = _miniapp_row(c, miniapp_id)
        user = _user_row(c, username)
        if user["role"] != "admin":
            if not _has(c, system_grants, username, miniapp_id):
                raise ServiceError(403, "NOT_VISIBLE",
                                   f"'{username}' không nhìn thấy miniapp '{miniapp_id}' (chưa có quyền hệ thống)")
            if not _has(c, miniapp_grants, username, miniapp_id):
                raise ServiceError(403, "NOT_MEMBER",
                                   f"'{username}' chưa là thành viên của miniapp '{miniapp_id}'")
    return {
        "miniapp_id": miniapp_id,
        "used_by": username,
        "message": f"{username} đã sử dụng miniapp {app['name']} thành công",
    }


def list_users_with_grants(engine):
    with engine.connect() as c:
        rows = c.execute(
            select(users.c.username, users.c.role, users.c.display_name, users.c.email).order_by(users.c.username)
        ).mappings().all()
        sys_rows = c.execute(select(system_grants.c.username, system_grants.c.miniapp_id)).all()
        mem_rows = c.execute(select(miniapp_grants.c.username, miniapp_grants.c.miniapp_id)).all()
    result = []
    for r in rows:
        u = r["username"]
        result.append(dict(
            r,
            system_access=sorted(m for (n, m) in sys_rows if n == u),
            memberships=sorted(m for (n, m) in mem_rows if n == u),
        ))
    return result


def find_user_by_email(engine, email):
    """Mock identity: resolve a requester email (e.g. from a ticket) to an account with its grants."""
    wanted = (email or "").strip().lower()
    if not wanted:
        raise ServiceError(422, "VALIDATION_ERROR", "email: thiếu email cần tìm")
    with engine.connect() as c:
        row = c.execute(
            select(users.c.username).where(func.lower(users.c.email) == wanted)
        ).first()
    if row is None:
        raise ServiceError(404, "USER_NOT_FOUND", f"Không tìm thấy người dùng có email '{wanted}'")
    return next(u for u in list_users_with_grants(engine) if u["username"] == row[0])
