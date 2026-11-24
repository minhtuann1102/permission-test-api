"""Two-tier permission rules (system access -> miniapp membership) and eligibility. No HTTP here."""
import unicodedata
from datetime import datetime, timezone

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.exc import IntegrityError

from permapp.db import miniapp_grants, miniapps, permission_log, role_rules, system_grants, users


class ServiceError(Exception):
    def __init__(self, status, code, detail):
        super().__init__(detail)
        self.status = status
        self.code = code
        self.detail = detail


# ---------- lookups ----------

_USER_COLS = (
    users.c.username, users.c.role, users.c.display_name, users.c.email,
    users.c.department, users.c.title, users.c.manager_email, users.c.status,
)
ACTIVE, RESIGNED = "ACTIVE", "RESIGNED"


def _user_dict(row):
    """Public shape of a user: blank text is "" (never null), a missing status counts as ACTIVE."""
    d = {k: (v or "") for k, v in dict(row).items()}
    d["status"] = (d["status"] or ACTIVE).upper()
    return d
_APP_COLS = (miniapps.c.id, miniapps.c.name, miniapps.c.description, miniapps.c.always_visible, miniapps.c.roles)


def _user_row(conn, username):
    row = conn.execute(select(*_USER_COLS).where(users.c.username == username)).mappings().first()
    if row is None:
        raise ServiceError(404, "USER_NOT_FOUND", f"Không tìm thấy người dùng '{username}'")
    return _user_dict(row)


def _app_dict(row):
    """Public shape of a miniapp: roles as a list, always_visible as a bool (never null)."""
    roles = [r.strip() for r in (row["roles"] or "").split(",") if r.strip()]
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "always_visible": bool(row["always_visible"]),
        "roles": roles,
    }


def _miniapp_row(conn, miniapp_id):
    row = conn.execute(select(*_APP_COLS).where(miniapps.c.id == miniapp_id)).mappings().first()
    if row is None:
        raise ServiceError(404, "MINIAPP_NOT_FOUND", f"Không tìm thấy miniapp '{miniapp_id}'")
    return _app_dict(row)


def _all_apps(conn):
    return [_app_dict(r) for r in conn.execute(select(*_APP_COLS).order_by(miniapps.c.id)).mappings().all()]


def _has(conn, table, username, miniapp_id):
    return conn.execute(
        select(table.c.username).where(
            and_(table.c.username == username, table.c.miniapp_id == miniapp_id)
        )
    ).first() is not None


def _member_role(conn, username, miniapp_id):
    """The member's role ("" if the miniapp has no roles), or None if not a member."""
    row = conn.execute(
        select(miniapp_grants.c.role).where(
            and_(miniapp_grants.c.username == username, miniapp_grants.c.miniapp_id == miniapp_id)
        )
    ).first()
    return None if row is None else (row[0] or "")


def resolve_role(app, role):
    """Normalise a requested member role. Blank means the first (lowest) role of a miniapp with roles."""
    role = (role or "").strip().lower()
    if app["roles"]:
        if not role:
            return app["roles"][0]
        if role not in app["roles"]:
            raise ServiceError(422, "INVALID_ROLE",
                               f"Vai trò '{role}' không có trong miniapp {app['name']} "
                               f"(chọn một trong: {', '.join(app['roles'])})")
        return role
    if role:
        raise ServiceError(422, "INVALID_ROLE", f"Miniapp {app['name']} không có vai trò, hãy bỏ trống role")
    return ""


def get_user_by_key(engine, api_key):
    if not api_key:
        return None
    with engine.connect() as c:
        row = c.execute(select(*_USER_COLS).where(users.c.api_key == api_key)).mappings().first()
    return _user_dict(row) if row else None


def list_miniapps(engine):
    with engine.connect() as c:
        return _all_apps(c)


def list_visible_miniapps(engine, username):
    with engine.connect() as c:
        user = _user_row(c, username)
        all_apps = _all_apps(c)
        if user["role"] == "admin":
            return [dict(a, can_use=True, role="") for a in all_apps]
        visible = set(c.execute(select(system_grants.c.miniapp_id).where(system_grants.c.username == username)).scalars())
        members = dict(c.execute(
            select(miniapp_grants.c.miniapp_id, miniapp_grants.c.role).where(miniapp_grants.c.username == username)
        ).all())
    return [
        dict(a, can_use=a["id"] in members, role=members.get(a["id"]) or "")
        for a in all_apps if a["always_visible"] or a["id"] in visible
    ]


def check_access(engine, username, miniapp_id):
    with engine.connect() as c:
        app = _miniapp_row(c, miniapp_id)
        user = _user_row(c, username)
        role = ""
        if user["role"] == "admin":
            visible = can_use = True
        else:
            visible = app["always_visible"] or _has(c, system_grants, username, miniapp_id)
            member_role = _member_role(c, username, miniapp_id)
            can_use = visible and member_role is not None
            role = member_role or ""
    return {"username": username, "miniapp_id": miniapp_id, "visible": visible, "can_use": can_use, "role": role}


# ---------- eligibility ----------
# The API decides who may be granted what. Callers (the agent) only read and show the result.

def _fold(text):
    """Case- and accent-form-insensitive comparison key (Vietnamese titles, emails)."""
    return unicodedata.normalize("NFC", (text or "").strip()).casefold()


def _eligibility(conn, user, app, role):
    """(eligible, reasons) for granting `user` the (already validated) `role` in `app`.
    Reasons are Vietnamese sentences: why not, or on what basis."""
    subject = f"Vai trò {role} của {app['name']}" if role else f"Miniapp {app['name']}"
    rules = conn.execute(
        select(role_rules.c.department, role_rules.c.title_keyword)
        .where(role_rules.c.miniapp_id == app["id"], role_rules.c.role == role)
        .order_by(role_rules.c.id)
    ).all()
    failures, grounds = [], []
    if user["status"] == RESIGNED:
        failures.append("Nhân viên đã nghỉ việc (RESIGNED), không được cấp quyền mới")
    if rules:
        for department, keyword in rules:
            if department and _fold(user["department"]) == _fold(department):
                grounds.append(f"Thuộc {department}")
            if keyword and _fold(keyword) in _fold(user["title"]):
                grounds.append(f"Chức danh '{user['title']}' chứa '{keyword}'")
        if not grounds:
            allowed = [d for d, _ in rules if d] + [f"chức danh chứa '{k}'" for _, k in rules if k]
            failures.append(f"{subject} chỉ dành cho {' hoặc '.join(allowed)}")
    else:
        grounds.append(f"{subject} không giới hạn đơn vị hay chức danh")
    if failures:
        return False, failures
    return True, grounds + ["Nhân viên đang làm việc"]


def _require_eligible(conn, user, app, role):
    eligible, reasons = _eligibility(conn, user, app, role)
    if not eligible:
        raise ServiceError(403, "NOT_ELIGIBLE", reasons[0])


def check_eligibility(engine, username, miniapp_id, role="", approver_email=""):
    """Always returns a result (never raises for unknown ids): the caller shows `reasons` as is."""
    username = (username or "").strip()
    miniapp_id = (miniapp_id or "").strip()
    approver = (approver_email or "").strip()
    out = {
        "username": username, "miniapp_id": miniapp_id, "role": (role or "").strip().lower(),
        "eligible": False, "reasons": [],
        "status": "", "department": "", "title": "", "manager_email": "",
        "approver_checked": bool(approver), "approver_ok": False,
    }
    with engine.connect() as c:
        try:
            user = _user_row(c, username)
        except ServiceError as e:
            user = None
            out["reasons"].append(e.detail)
        if user:
            out.update({k: user[k] for k in ("status", "department", "title", "manager_email")})
            out["approver_ok"] = bool(approver) and bool(user["manager_email"]) and                 _fold(approver) == _fold(user["manager_email"])
        try:
            app = _miniapp_row(c, miniapp_id)
            out["role"] = resolve_role(app, role)
        except ServiceError as e:
            app = None
            out["reasons"].append(e.detail)
        if user and app:
            out["eligible"], out["reasons"] = _eligibility(c, user, app, out["role"])
    return out


# ---------- change log ----------

LEVEL_LABEL = {"none": "Chưa có quyền", "see": "Xem", "use": "Sử dụng",
               "learner": "Học viên", "instructor": "Giảng viên"}
ACTORS = ("console", "agent")


def level_of(conn, username, app):
    """none | see | use | <member role>: what `username` currently has in `app`."""
    role = _member_role(conn, username, app["id"])
    if role is not None:
        return role or "use"
    if app["always_visible"] or _has(conn, system_grants, username, app["id"]):
        return "see"
    return "none"


def _label(level):
    return LEVEL_LABEL.get(level, level)


def _detail(action, username, app, before, after):
    name = app["name"]
    if action == "ChangeRole":
        return f"Đổi vai trò {name} của {username}: {_label(before)} → {_label(after)}"
    if action == "RevokeUse":
        return f"Thu hồi quyền dùng {name} của {username}"
    if action == "RevokeAll":
        return f"Thu hồi hết quyền {name} của {username}"
    kind = "vai trò" if after in app["roles"] else "quyền"
    return f"Cấp {kind} {_label(after)} {name} cho {username}"


def _record(conn, username, app, before, actor, action=None):
    """Write one log row if the level changed. Grants pass no action: Grant or ChangeRole is inferred."""
    after = level_of(conn, username, app)
    if after == before:
        return after
    if action is None:
        action = "ChangeRole" if before in app["roles"] and after in app["roles"] else "Grant"
    conn.execute(permission_log.insert().values(
        at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        actor=actor if actor in ACTORS else "agent", action=action, username=username,
        miniapp_id=app["id"], from_level=before, to_level=after,
        detail=_detail(action, username, app, before, after),
    ))
    return after


def list_permission_log(engine, username=""):
    q = select(permission_log).order_by(permission_log.c.id.desc()).limit(200)
    if (username or "").strip():
        q = q.where(permission_log.c.username == username.strip())
    with engine.connect() as c:
        return {"entries": [dict(r) for r in c.execute(q).mappings().all()]}


# ---------- grants ----------
# IntegrityError is caught outside the transaction block so a Postgres aborted
# transaction is fully rolled back first.

def grant_system_access(engine, username, miniapp_id, actor="agent"):
    try:
        with engine.begin() as c:
            app = _miniapp_row(c, miniapp_id)
            user = _user_row(c, username)
            _require_eligible(c, user, app, "")
            if app["always_visible"] or _has(c, system_grants, username, miniapp_id):
                already = True  # always-visible miniapps need no system access row
            else:
                before = level_of(c, username, app)
                c.execute(system_grants.insert().values(username=username, miniapp_id=miniapp_id))
                _record(c, username, app, before, actor)
                already = False
    except IntegrityError:
        already = True  # concurrent identical grant won the race
    return {"username": username, "miniapp_id": miniapp_id, "role": "", "already_granted": already}


def grant_membership(engine, miniapp_id, username, role="", actor="agent"):
    """Add a member, or change the member's role. already_granted=true only if nothing changed."""
    try:
        with engine.begin() as c:
            app = _miniapp_row(c, miniapp_id)
            user = _user_row(c, username)
            role = resolve_role(app, role)
            _require_eligible(c, user, app, role)  # also on a role change, before any write
            if not app["always_visible"] and not _has(c, system_grants, username, miniapp_id):
                raise ServiceError(
                    409,
                    "SYSTEM_ACCESS_REQUIRED",
                    f"'{username}' chưa được cấp quyền hệ thống cho miniapp '{miniapp_id}'. "
                    "Hãy cấp quyền hệ thống (system access) trước.",
                )
            before = level_of(c, username, app)
            current = _member_role(c, username, miniapp_id)
            if current is None:
                c.execute(miniapp_grants.insert().values(username=username, miniapp_id=miniapp_id, role=role))
                already = False
            elif current != role:
                c.execute(update(miniapp_grants).where(and_(
                    miniapp_grants.c.username == username, miniapp_grants.c.miniapp_id == miniapp_id,
                )).values(role=role))
                already = False
            else:
                already = True
            _record(c, username, app, before, actor)
    except IntegrityError:
        already = True  # concurrent identical grant won the race
    return {"username": username, "miniapp_id": miniapp_id, "role": role, "already_granted": already}


_RANK = {"none": 0, "see": 1, "use": 2}


def _grant_one(engine, username, miniapp_id, level, actor):
    """One console pick in its own transaction: see | use | <role>. Never lowers use to see."""
    try:
        with engine.begin() as c:
            app = _miniapp_row(c, miniapp_id)
            user = _user_row(c, username)
            allowed = app["roles"] or ["see", "use"]
            if level not in allowed:
                raise ServiceError(422, "INVALID_LEVEL",
                                   f"Mức quyền '{level}' không hợp lệ cho {app['name']} (chọn: {', '.join(allowed)})")
            before = level_of(c, username, app)
            role = level if app["roles"] else ""
            _require_eligible(c, user, app, role)
            if app["roles"]:
                if _member_role(c, username, miniapp_id) is None:
                    c.execute(miniapp_grants.insert().values(username=username, miniapp_id=miniapp_id, role=role))
                elif before != role:
                    c.execute(update(miniapp_grants).where(and_(
                        miniapp_grants.c.username == username, miniapp_grants.c.miniapp_id == miniapp_id,
                    )).values(role=role))
            elif _RANK[before] < _RANK[level]:
                if not app["always_visible"] and not _has(c, system_grants, username, miniapp_id):
                    c.execute(system_grants.insert().values(username=username, miniapp_id=miniapp_id))
                if level == "use":
                    c.execute(miniapp_grants.insert().values(username=username, miniapp_id=miniapp_id, role=""))
            after = _record(c, username, app, before, actor)
        return {"ok": True, "changed": after != before, "from_level": before, "to_level": after,
                "code": "", "detail": ""}
    except ServiceError as e:
        return {"ok": False, "changed": False, "from_level": "", "to_level": "", "code": e.code, "detail": e.detail}
    except IntegrityError:  # a concurrent identical grant won the race
        return {"ok": True, "changed": False, "from_level": "", "to_level": "", "code": "", "detail": ""}


def grant_permissions(engine, username, items, actor="agent"):
    """Console multi-grant: each pick applied on its own, so one refusal does not undo the others."""
    username = (username or "").strip()
    with engine.connect() as c:
        _user_row(c, username)
    results = []
    for item in items or []:
        miniapp_id = (item.get("miniapp_id") or "").strip()
        level = (item.get("level") or "").strip().lower()
        results.append({"miniapp_id": miniapp_id, "level": level,
                        **_grant_one(engine, username, miniapp_id, level, actor)})
    return {"username": username, "results": results}


def revoke_system_access(engine, username, miniapp_id, actor="agent"):
    with engine.begin() as c:
        app = _miniapp_row(c, miniapp_id)
        _user_row(c, username)
        before = level_of(c, username, app)
        mem = c.execute(delete(miniapp_grants).where(
            and_(miniapp_grants.c.username == username, miniapp_grants.c.miniapp_id == miniapp_id)))
        res = c.execute(delete(system_grants).where(
            and_(system_grants.c.username == username, system_grants.c.miniapp_id == miniapp_id)))
        _record(c, username, app, before, actor, "RevokeAll")
    # Always-visible miniapps have no system access row: revoking all removes the membership.
    return {"username": username, "miniapp_id": miniapp_id, "revoked": res.rowcount > 0 or mem.rowcount > 0}


def revoke_membership(engine, miniapp_id, username, actor="agent"):
    with engine.begin() as c:
        app = _miniapp_row(c, miniapp_id)
        _user_row(c, username)
        before = level_of(c, username, app)
        res = c.execute(delete(miniapp_grants).where(
            and_(miniapp_grants.c.username == username, miniapp_grants.c.miniapp_id == miniapp_id)))
        _record(c, username, app, before, actor, "RevokeUse")
    return {"username": username, "miniapp_id": miniapp_id, "revoked": res.rowcount > 0}


# ---------- use / overview ----------

def use_miniapp(engine, username, miniapp_id):
    with engine.connect() as c:
        app = _miniapp_row(c, miniapp_id)
        user = _user_row(c, username)
        if user["role"] != "admin":
            if not app["always_visible"] and not _has(c, system_grants, username, miniapp_id):
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
        rows = [_user_dict(r) for r in c.execute(select(*_USER_COLS).order_by(users.c.username)).mappings().all()]
        sys_rows = c.execute(select(system_grants.c.username, system_grants.c.miniapp_id)).all()
        mem_rows = c.execute(
            select(miniapp_grants.c.username, miniapp_grants.c.miniapp_id, miniapp_grants.c.role)
        ).all()
    result = []
    for r in rows:
        u = r["username"]
        mine = sorted((m, role or "") for (n, m, role) in mem_rows if n == u)
        result.append(dict(
            r,
            system_access=sorted(m for (n, m) in sys_rows if n == u),
            memberships=[m for (m, _) in mine],
            member_roles=[{"miniapp_id": m, "role": role} for (m, role) in mine if role],
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
