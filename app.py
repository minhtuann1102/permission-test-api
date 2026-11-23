"""Permission Test API — FastAPI entrypoint (Vercel zero-config: exposes `app`)."""
import html
import os
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from permapp import service
from permapp.db import get_engine, init_db, reset_db
from permapp.service import ServiceError
from permapp.swagger import build_swagger

app = FastAPI(title="Permission Test API", version="1.0.0")

STATIC_DIR = Path(__file__).parent / "permapp" / "static"

_db_ready = False


def db_engine():
    """Lazily create schema + seed once per process. Flag is set only after success."""
    global _db_ready
    engine = get_engine()
    if not _db_ready:
        init_db(engine)
        _db_ready = True
    return engine


# ---------- errors ----------

def _error(status, code, detail):
    return JSONResponse(status_code=status, content={"detail": detail, "code": code})


_HTTP_CODES = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}


@app.exception_handler(ServiceError)
async def _service_error(request: Request, exc: ServiceError):
    return _error(exc.status, exc.code, exc.detail)


@app.exception_handler(StarletteHTTPException)
async def _http_error(request: Request, exc: StarletteHTTPException):
    if isinstance(exc.detail, dict) and "code" in exc.detail:
        return _error(exc.status_code, exc.detail["code"], str(exc.detail.get("detail", "")))
    code = _HTTP_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")
    return _error(exc.status_code, code, str(exc.detail))


@app.exception_handler(Exception)
async def _unhandled_error(request: Request, exc: Exception):
    return _error(500, "INTERNAL_ERROR", f"Lỗi máy chủ: {type(exc).__name__}")


@app.exception_handler(RequestValidationError)
async def _validation_error(request: Request, exc: RequestValidationError):
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg', 'invalid')}")
    return _error(422, "VALIDATION_ERROR", "; ".join(parts) or "Invalid request")


# ---------- auth ----------

def current_user(
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
    engine=Depends(db_engine),
):
    user = service.get_user_by_key(engine, x_api_key) if x_api_key else None
    if user is None:
        raise ServiceError(401, "UNAUTHORIZED", "Thiếu hoặc sai header X-API-Key")
    return user


def require_admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise ServiceError(403, "ADMIN_REQUIRED", "Chỉ admin mới được gọi endpoint này (dùng admin API key)")
    return user


# ---------- bodies ----------

class SystemAccessIn(BaseModel):
    username: str
    miniapp_id: str


class MemberIn(BaseModel):
    username: str


# ---------- public ----------

@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/swagger.json")
def swagger_json(request: Request):
    host = (
        os.environ.get("PUBLIC_HOST")
        or request.headers.get("x-forwarded-host")
        or request.headers.get("host", "")
    )
    return build_swagger(host)


@app.get("/", include_in_schema=False)
def console_page():
    return FileResponse(STATIC_DIR / "console.html", media_type="text/html")


@app.get("/status", response_class=HTMLResponse, include_in_schema=False)
def status_page(engine=Depends(db_engine)):
    apps = service.list_miniapps(engine)
    people = service.list_users_with_grants(engine)
    head = "".join(f"<th>{html.escape(a['name'])}<br><small>{html.escape(a['id'])}</small></th>" for a in apps)
    rows = []
    for u in people:
        cells = []
        for a in apps:
            if u["role"] == "admin":
                cell, cls = "admin", "all"
            elif a["id"] in u["memberships"]:
                cell, cls = "dùng được", "use"
            elif a["id"] in u["system_access"]:
                cell, cls = "chỉ thấy", "see"
            else:
                cell, cls = "—", "none"
            cells.append(f'<td class="{cls}">{cell}</td>')
        rows.append(
            f"<tr><th>{html.escape(u['username'])}<br><small>{html.escape(u['display_name'])} · {u['role']}</small></th>"
            + "".join(cells) + "</tr>"
        )
    body = f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Permission Test API</title>
<style>
body{{font-family:system-ui,sans-serif;margin:2rem;color:#1d2433;background:#fafafa}}
table{{border-collapse:collapse;background:#fff}}
th,td{{border:1px solid #d5d9e0;padding:.5rem .8rem;text-align:center}}
th small{{color:#6b7280;font-weight:normal}}
td.use{{background:#dcfce7}} td.see{{background:#fef9c3}} td.none{{color:#9ca3af}} td.all{{background:#e0e7ff}}
code{{background:#eef;padding:0 .3em}}
</style></head><body>
<h1>Permission Test API</h1>
<p>Trạng thái quyền hiện tại. <b>chỉ thấy</b> = đã có quyền hệ thống (tầng 1);
<b>dùng được</b> = đã là thành viên miniapp (tầng 2). Spec: <a href="/swagger.json"><code>/swagger.json</code></a></p>
<table><tr><th>Người dùng</th>{head}</tr>{''.join(rows)}</table>
</body></html>"""
    return HTMLResponse(body)


# ---------- any authenticated caller ----------

@app.get("/me")
def me(user=Depends(current_user)):
    return user


@app.get("/me/miniapps")
def my_miniapps(user=Depends(current_user), engine=Depends(db_engine)):
    return {"username": user["username"], "miniapps": service.list_visible_miniapps(engine, user["username"])}


@app.post("/miniapps/{miniapp_id}/use")
def use_miniapp(miniapp_id: str, user=Depends(current_user), engine=Depends(db_engine)):
    return service.use_miniapp(engine, user["username"], miniapp_id)


# ---------- admin ----------

@app.get("/admin/users")
def admin_users(_=Depends(require_admin), engine=Depends(db_engine)):
    return {"users": service.list_users_with_grants(engine)}


@app.get("/admin/miniapps")
def admin_miniapps(_=Depends(require_admin), engine=Depends(db_engine)):
    return {"miniapps": service.list_miniapps(engine)}


@app.post("/admin/system-access")
def grant_system_access(body: SystemAccessIn, _=Depends(require_admin), engine=Depends(db_engine)):
    return service.grant_system_access(engine, body.username, body.miniapp_id)


@app.delete("/admin/system-access/{username}/{miniapp_id}")
def revoke_system_access(username: str, miniapp_id: str, _=Depends(require_admin), engine=Depends(db_engine)):
    return service.revoke_system_access(engine, username, miniapp_id)


@app.post("/admin/miniapps/{miniapp_id}/members")
def add_member(miniapp_id: str, body: MemberIn, _=Depends(require_admin), engine=Depends(db_engine)):
    return service.grant_membership(engine, miniapp_id, body.username)


@app.delete("/admin/miniapps/{miniapp_id}/members/{username}")
def remove_member(miniapp_id: str, username: str, _=Depends(require_admin), engine=Depends(db_engine)):
    return service.revoke_membership(engine, miniapp_id, username)


@app.get("/admin/check")
def admin_check(
    username: str = Query(...),
    miniapp_id: str = Query(...),
    _=Depends(require_admin),
    engine=Depends(db_engine),
):
    """Always 200 so Copilot Studio never treats a 'no' as a tool failure."""
    try:
        return service.check_access(engine, username, miniapp_id)
    except ServiceError:
        return {"username": username, "miniapp_id": miniapp_id, "visible": False, "can_use": False}


@app.post("/admin/reset")
def admin_reset(_=Depends(require_admin), engine=Depends(db_engine)):
    reset_db(engine)
    return {"reset": True}


# check_dir=False: if the folder were missing from a deploy, only the UI breaks, never the API.
app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")
