"""Permission Test API — FastAPI entrypoint (Vercel zero-config: exposes `app`)."""
import html
import os
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from permapp import reviews, service
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


def actor(x_client: Optional[str] = Header(None, alias="X-Client")):
    """Who makes a change, for the change logs: the operator console sends X-Client: console."""
    return "console" if (x_client or "").strip().lower() == "console" else "agent"


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
    role: Optional[str] = ""  # member role for miniapps with roles (lms); blank = default role


class PeriodIn(BaseModel):
    company: str
    kind: str  # KPI_MONTH | KPI_QUARTER | KPI_YEAR | REVIEW_360
    year: int
    number: Optional[int] = 0  # month (1-12) or quarter (1-4); 0 for KPI_YEAR / REVIEW_360
    start_date: str
    deadline: str
    ticket: str


class DeadlineIn(BaseModel):
    deadline: str
    ticket: str


class FormReopenIn(BaseModel):
    deadline: Optional[str] = ""  # personal deadline; required when the form's period is closed
    ticket: str


class EvaluatorIn(BaseModel):
    new_email: str
    old_email: Optional[str] = ""  # required when the form has several evaluators (360)
    ticket: str


class GoalIn(BaseModel):
    title: Optional[str] = ""
    weight: Optional[int] = 0  # 0 / blank = unchanged
    target: Optional[str] = ""
    ticket: str


class ResultRowIn(BaseModel):
    email: Optional[str] = ""
    score: Optional[int] = None
    grade: Optional[str] = ""


class ResultsIn(BaseModel):
    rows: List[ResultRowIn]
    ticket: str


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
    # CORS only here, so a browser-based importer can fetch the spec. Never on /admin.
    return JSONResponse(build_swagger(host), headers={"Access-Control-Allow-Origin": "*"})


@app.get("/", include_in_schema=False)
def console_page():
    return FileResponse(STATIC_DIR / "console.html", media_type="text/html")


@app.get("/status", response_class=HTMLResponse, include_in_schema=False)
def status_page(engine=Depends(db_engine)):
    apps = service.list_miniapps(engine)
    people = service.list_users_with_grants(engine)
    head = "".join(f"<th>{html.escape(a['name'])}<br><small>{html.escape(a['id'])}</small></th>" for a in apps)
    rows = []
    role_names = {"learner": "Học viên", "instructor": "Giảng viên"}
    for u in people:
        cells = []
        roles = {r["miniapp_id"]: r["role"] for r in u.get("member_roles", [])}
        for a in apps:
            if u["role"] == "admin":
                cell, cls = "admin", "all"
            elif a["id"] in u["memberships"]:
                cell, cls = "dùng được", "use"
                if roles.get(a["id"]):
                    cell += f"<br><small>{html.escape(role_names.get(roles[a['id']], roles[a['id']]))}</small>"
            elif a["always_visible"] or a["id"] in u["system_access"]:
                cell, cls = "chỉ thấy", "see"
            else:
                cell, cls = "—", "none"
            cells.append(f'<td class="{cls}">{cell}</td>')
        org = " · ".join(html.escape(x) for x in (u["department"], u["title"]) if x)
        badge = ' <span class="gone">Đã nghỉ việc</span>' if u["status"] == "RESIGNED" else ""
        rows.append(
            f"<tr><th>{html.escape(u['username'])}{badge}<br><small>{html.escape(u['display_name'])} · {u['role']}</small>"
            + (f"<br><small>{org}</small>" if org else "") + "</th>"
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
.gone{{font-size:.75rem;font-weight:600;color:#b42318;background:#fee4e2;border-radius:4px;padding:0 .35em}}
</style></head><body>
<h1>Permission Test API</h1>
<p>Trạng thái quyền hiện tại. <b>chỉ thấy</b> = đã có quyền hệ thống (tầng 1);
<b>dùng được</b> = đã là thành viên miniapp (tầng 2). LMS luôn hiển thị với mọi người,
thành viên có vai trò Học viên hoặc Giảng viên. Spec: <a href="/swagger.json"><code>/swagger.json</code></a> ·
Hệ thống đánh giá giả lập: <a href="/reviews"><code>/reviews</code></a></p>
<table><tr><th>Người dùng</th>{head}</tr>{''.join(rows)}</table>
</body></html>"""
    return HTMLResponse(body)


def _cell(text):
    return html.escape(str(text if text not in (None, "") else "—"))


@app.get("/reviews", response_class=HTMLResponse, include_in_schema=False)
def reviews_page(engine=Depends(db_engine)):
    periods = reviews.list_periods(engine)["periods"]
    forms = reviews.find_forms(engine)["forms"]
    log = reviews.list_log(engine)["entries"][:30]
    p_rows = "".join(
        f"<tr class='{p['status'].lower()}'><td><b>{_cell(p['id'])}</b><br><small>{_cell(p['name'])}</small></td>"
        f"<td>{_cell(p['status_label'])}</td><td>{_cell(p['start_date'])}</td><td>{_cell(p['deadline'])}</td>"
        f"<td>{_cell(p['original_deadline'])}</td><td>{p['extension_count']}</td><td>{p['form_count']}</td>"
        f"<td>{p['result_count']}</td></tr>"
        for p in periods
    )
    f_rows = []
    for f in forms:
        goals = "".join(f"<li><code>{_cell(g['id'])}</code> {_cell(g['title'])} · {g['weight']}% · {_cell(g['target'])}</li>"
                        for g in f["goals"])
        evs = "<br>".join(f"{_cell(e['email'])} <small>({_cell(e['relation_label'])})</small>" for e in f["evaluators"])
        gone = ' <span class="gone">Đã nghỉ việc</span>' if f["employee_status"] == "RESIGNED" else ""
        weight = "" if f["weight_ok"] or not f["goals"] else f' <span class="warn">tổng {f["total_weight"]}%</span>'
        f_rows.append(
            f"<tr class='{f['status'].lower()}'><td><b>{_cell(f['id'])}</b><br><small>{_cell(f['kind_label'])}</small></td>"
            f"<td>{_cell(f['username'])}{gone}<br><small>{_cell(f['employee_email'])}</small></td>"
            f"<td>{_cell(f['period_id'])}</td><td>{_cell(f['status_label'])}</td><td>{_cell(f['deadline'])}</td>"
            f"<td class='left'>{evs}</td><td class='left'><ul>{goals}</ul>{weight}</td></tr>"
        )
    l_rows = "".join(
        f"<tr><td><small>{_cell(e['at'])}</small></td><td>{_cell(e['ticket'])}</td><td>{_cell(e['action'])}</td>"
        f"<td>{_cell(e['target'])}</td><td class='left'>{_cell(e['detail'])}</td></tr>"
        for e in log
    ) or "<tr><td colspan='5'>Chưa có thao tác nào.</td></tr>"
    body = f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="10">
<title>Đánh giá (giả lập)</title>
<style>
body{{font-family:system-ui,sans-serif;margin:2rem;color:#1d2433;background:#fafafa}}
table{{border-collapse:collapse;background:#fff;margin-bottom:2rem}}
th,td{{border:1px solid #d5d9e0;padding:.45rem .7rem;text-align:center;vertical-align:top}}
th{{background:#f1f3f7}} td.left{{text-align:left}} small{{color:#6b7280}}
ul{{margin:0;padding-left:1.1rem}} code{{background:#eef;padding:0 .3em}}
tr.open td:nth-child(2){{background:#dcfce7}} tr.closed td:nth-child(2){{background:#fef9c3}}
tr.locked td:nth-child(2){{background:#fee4e2}}
tr.draft td:nth-child(4){{background:#dcfce7}} tr.submitted td:nth-child(4){{background:#e0e7ff}}
tr.approved td:nth-child(4){{background:#fef9c3}}
.gone{{font-size:.75rem;font-weight:600;color:#b42318;background:#fee4e2;border-radius:4px;padding:0 .35em}}
.warn{{font-size:.8rem;color:#b54708}}
</style></head><body>
<h1>Đánh giá (giả lập)</h1>
<p>Hệ thống đánh giá giả lập cho ticket <i>Đánh giá (KPI, thử việc, HĐ, 360)</i>. Chỉ đọc, tự tải lại mỗi 10 giây.
Thao tác qua API <code>/admin/reviews/...</code> (admin key). <a href="/status">Quyền miniapp</a> ·
<a href="/swagger.json"><code>/swagger.json</code></a></p>
<h2>Kỳ đánh giá</h2>
<table><tr><th>Kỳ</th><th>Trạng thái</th><th>Bắt đầu</th><th>Hạn</th><th>Hạn gốc</th><th>Số lần gia hạn</th><th>Phiếu</th><th>Kết quả HQCV</th></tr>{p_rows}</table>
<h2>Phiếu đánh giá</h2>
<table><tr><th>Phiếu</th><th>Nhân viên</th><th>Kỳ</th><th>Trạng thái</th><th>Hạn</th><th>Người đánh giá</th><th>Mục tiêu / tiêu chí</th></tr>{''.join(f_rows)}</table>
<h2>Nhật ký thao tác (30 dòng gần nhất)</h2>
<table><tr><th>Lúc (UTC)</th><th>Ticket</th><th>Thao tác</th><th>Đối tượng</th><th>Chi tiết</th></tr>{l_rows}</table>
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


@app.get("/admin/users/by-email")
def admin_user_by_email(
    email: Optional[str] = Query(None),
    _=Depends(require_admin),
    engine=Depends(db_engine),
):
    return service.find_user_by_email(engine, email)


@app.get("/admin/miniapps")
def admin_miniapps(_=Depends(require_admin), engine=Depends(db_engine)):
    return {"miniapps": service.list_miniapps(engine)}


@app.post("/admin/system-access")
def grant_system_access(body: SystemAccessIn, _=Depends(require_admin), engine=Depends(db_engine),
                        who=Depends(actor)):
    return service.grant_system_access(engine, body.username, body.miniapp_id, who)


@app.delete("/admin/system-access/{username}/{miniapp_id}")
def revoke_system_access(username: str, miniapp_id: str, _=Depends(require_admin), engine=Depends(db_engine),
                         who=Depends(actor)):
    return service.revoke_system_access(engine, username, miniapp_id, who)


@app.post("/admin/miniapps/{miniapp_id}/members")
def add_member(miniapp_id: str, body: MemberIn, _=Depends(require_admin), engine=Depends(db_engine),
               who=Depends(actor)):
    return service.grant_membership(engine, miniapp_id, body.username, body.role, who)


@app.delete("/admin/miniapps/{miniapp_id}/members/{username}")
def remove_member(miniapp_id: str, username: str, _=Depends(require_admin), engine=Depends(db_engine),
                  who=Depends(actor)):
    return service.revoke_membership(engine, miniapp_id, username, who)


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
        return {"username": username, "miniapp_id": miniapp_id, "visible": False, "can_use": False, "role": ""}


@app.get("/admin/eligibility")
def admin_eligibility(
    username: Optional[str] = Query(None),
    miniapp_id: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    approver_email: Optional[str] = Query(None),
    _=Depends(require_admin),
    engine=Depends(db_engine),
):
    """Always 200: a 'not eligible' answer is data for the agent, not a tool failure."""
    return service.check_eligibility(engine, username, miniapp_id, role, approver_email)


@app.get("/admin/permission-log")
def permission_log(username: Optional[str] = Query(None), _=Depends(require_admin), engine=Depends(db_engine)):
    """Console only (not in swagger): latest permission changes, newest first."""
    return service.list_permission_log(engine, username)


@app.post("/admin/reset")
def admin_reset(_=Depends(require_admin), engine=Depends(db_engine)):
    reset_db(engine)
    return {"reset": True}


# ---------- admin: Đánh giá (mock appraisal system) ----------

@app.get("/admin/reviews/periods")
def review_periods(company: Optional[str] = Query(None), status: Optional[str] = Query(None),
                   _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.list_periods(engine, company, status)


@app.post("/admin/reviews/periods")
def review_create_period(body: PeriodIn, _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.create_period(engine, body.company, body.kind, body.year, body.number,
                                 body.start_date, body.deadline, body.ticket)


@app.get("/admin/reviews/periods/{period_id}")
def review_period(period_id: str, _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.get_period(engine, period_id)


@app.post("/admin/reviews/periods/{period_id}/reopen")
def review_reopen_period(period_id: str, body: DeadlineIn, _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.reopen_period(engine, period_id, body.deadline, body.ticket)


@app.post("/admin/reviews/periods/{period_id}/extend")
def review_extend_period(period_id: str, body: DeadlineIn, _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.extend_period(engine, period_id, body.deadline, body.ticket)


@app.post("/admin/reviews/periods/{period_id}/results")
def review_import_results(period_id: str, body: ResultsIn, _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.import_results(engine, period_id, [r.model_dump() for r in body.rows], body.ticket)


@app.get("/admin/reviews/forms")
def review_forms(email: Optional[str] = Query(None), username: Optional[str] = Query(None),
                 period_id: Optional[str] = Query(None), kind: Optional[str] = Query(None),
                 _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.find_forms(engine, email, username, period_id, kind)


@app.get("/admin/reviews/forms/{form_id}")
def review_form(form_id: str, _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.get_form(engine, form_id)


@app.post("/admin/reviews/forms/{form_id}/reopen")
def review_reopen_form(form_id: str, body: FormReopenIn, _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.reopen_form(engine, form_id, body.deadline, body.ticket)


@app.post("/admin/reviews/forms/{form_id}/extend")
def review_extend_form(form_id: str, body: DeadlineIn, _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.extend_form(engine, form_id, body.deadline, body.ticket)


@app.put("/admin/reviews/forms/{form_id}/evaluator")
def review_update_evaluator(form_id: str, body: EvaluatorIn, _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.update_evaluator(engine, form_id, body.new_email, body.old_email, body.ticket)


@app.put("/admin/reviews/goals/{goal_id}")
def review_update_goal(goal_id: str, body: GoalIn, _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.update_goal(engine, goal_id, body.title, body.weight, body.target, body.ticket)


@app.delete("/admin/reviews/goals/{goal_id}")
def review_delete_goal(goal_id: str, ticket: Optional[str] = Query(None),
                       _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.delete_goal(engine, goal_id, ticket)


@app.get("/admin/reviews/log")
def review_log(ticket: Optional[str] = Query(None), _=Depends(require_admin), engine=Depends(db_engine)):
    return reviews.list_log(engine, ticket)


# check_dir=False: if the folder were missing from a deploy, only the UI breaks, never the API.
app.mount("/static", StaticFiles(directory=STATIC_DIR, check_dir=False), name="static")
