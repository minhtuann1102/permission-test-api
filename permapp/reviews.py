"""Mock appraisal system (Đánh giá): periods, forms, goals, evaluators, results. No HTTP here.

Rules live here so the API, not the agent, decides what is allowed. Every change is written to review_log
with who made it (console | agent). The agent must give the SDP ticket number it works on (logged with
the change); the operator screen, like the real system, has no ticket field.
Writes return {"result": "DONE" | "NO_CHANGE", "message", ...};
rule violations raise ServiceError (4xx) with a Vietnamese detail that says what to do instead.
"""
import re
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.exc import IntegrityError

from permapp.db import (
    review_evaluators,
    review_forms,
    review_goals,
    review_log,
    review_periods,
    review_results,
    users,
)
from permapp.service import RESIGNED, ServiceError, _user_row

MAX_EXTENSION_DAYS = 30  # an extension may not go further than this past the first deadline
GRADES = ("A", "B", "C", "D")

PERIOD_KINDS = {"KPI_MONTH": "KPI tháng", "KPI_QUARTER": "KPI quý", "KPI_YEAR": "KPI năm",
                "REVIEW_360": "Đánh giá 360"}
PERIOD_STATUS = {"OPEN": "Đang mở", "CLOSED": "Đã đóng", "LOCKED": "Đã chốt kết quả"}
FORM_KINDS = {"KPI": "Phiếu KPI", "REVIEW_360": "Phiếu đánh giá 360", "PROBATION": "Đánh giá thử việc",
              "CONTRACT": "Đánh giá hết hạn hợp đồng"}
FORM_STATUS = {"DRAFT": "Đang nhập", "SUBMITTED": "Đã nộp, chờ phê duyệt", "APPROVED": "Đã phê duyệt",
               "LOCKED": "Đã chốt"}
RELATIONS = {"manager": "Quản lý trực tiếp", "peer": "Đồng nghiệp", "subordinate": "Cấp dưới"}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TICKET = re.compile(r"^#?\s*(\d+)$")


# ---------- small helpers ----------

def _s(value):
    return (value or "").strip() if isinstance(value, str) or value is None else str(value).strip()



def _ticket(value, actor):
    """'#54' for the agent (required); "" for the operator screen, which has no ticket field."""
    if actor == "console":
        return ""
    m = _TICKET.match(_s(value))
    if not m:
        raise ServiceError(422, "TICKET_REQUIRED", "Thiếu số ticket SDP (ví dụ '#54'). Mọi thao tác ghi của agent đều phải gắn ticket.")
    return "#" + m.group(1)


def _date(value, field):
    text = _s(value)
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ServiceError(422, "INVALID_DATE", f"{field}: '{text}' không phải ngày dạng YYYY-MM-DD") from None


def _vn(d):
    d = d if isinstance(d, date) else date.fromisoformat(d)
    return d.strftime("%d/%m/%Y")


def _log(conn, actor, ticket, action, target, detail):
    conn.execute(review_log.insert().values(
        at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ticket=ticket,
        actor=actor if actor in ("console", "agent") else "agent",
        action=action, target=target, detail=detail[:1024],
    ))


def _done(message, **payload):
    return {"result": "DONE", "message": message, **payload}


def _no_change(message, **payload):
    return {"result": "NO_CHANGE", "message": message, **payload}


# ---------- read models ----------

def _period_row(conn, period_id):
    row = conn.execute(select(review_periods).where(review_periods.c.id == _s(period_id))).mappings().first()
    if row is None:
        raise ServiceError(404, "PERIOD_NOT_FOUND", f"Không tìm thấy kỳ đánh giá '{_s(period_id)}'")
    return dict(row)


def _period_out(conn, p):
    forms = conn.execute(select(func.count()).select_from(review_forms)
                         .where(review_forms.c.period_id == p["id"])).scalar_one()
    results = conn.execute(select(func.count()).select_from(review_results)
                           .where(review_results.c.period_id == p["id"])).scalar_one()
    return {
        **p,
        "kind_label": PERIOD_KINDS.get(p["kind"], p["kind"]),
        "status_label": PERIOD_STATUS.get(p["status"], p["status"]),
        "max_deadline": (date.fromisoformat(p["original_deadline"]) + timedelta(days=MAX_EXTENSION_DAYS)).isoformat(),
        "form_count": forms,
        "result_count": results,
    }


def _form_row(conn, form_id):
    row = conn.execute(select(review_forms).where(review_forms.c.id == _s(form_id))).mappings().first()
    if row is None:
        raise ServiceError(404, "FORM_NOT_FOUND", f"Không tìm thấy phiếu đánh giá '{_s(form_id)}'")
    return dict(row)


def _form_ctx(conn, form):
    """(form, period or None, employee) with the deadline and cap that apply to this form."""
    period = _period_row(conn, form["period_id"]) if form["period_id"] else None
    employee = _user_row(conn, form["username"])
    return period, employee


def _effective_deadline(form, period):
    return form["deadline"] or (period["deadline"] if period else "")


def _cap(form, period):
    # A personal deadline set when reopening becomes the new base; otherwise the period's first deadline.
    base = form["base_deadline"] or period["original_deadline"]
    return date.fromisoformat(base) + timedelta(days=MAX_EXTENSION_DAYS)


def _form_out(conn, form):
    period, employee = _form_ctx(conn, form)
    goals = [dict(g) for g in conn.execute(
        select(review_goals.c.id, review_goals.c.title, review_goals.c.weight, review_goals.c.target,
               review_goals.c.created_by)
        .where(review_goals.c.form_id == form["id"]).order_by(review_goals.c.id)).mappings().all()]
    evaluators = [dict(e, relation_label=RELATIONS.get(e["relation"], e["relation"])) for e in conn.execute(
        select(review_evaluators.c.email, review_evaluators.c.relation)
        .where(review_evaluators.c.form_id == form["id"])
        .order_by(review_evaluators.c.relation, review_evaluators.c.email)).mappings().all()]
    total = sum(g["weight"] for g in goals)
    return {
        "id": form["id"],
        "kind": form["kind"],
        "kind_label": FORM_KINDS.get(form["kind"], form["kind"]),
        "period_id": form["period_id"],
        "period_name": period["name"] if period else "",
        "period_status": period["status"] if period else "",
        "username": employee["username"],
        "employee_name": employee["display_name"],
        "employee_email": employee["email"],
        "employee_status": employee["status"],
        "status": form["status"],
        "status_label": FORM_STATUS.get(form["status"], form["status"]),
        "deadline": _effective_deadline(form, period),
        "personal_deadline": form["deadline"] if period else "",
        "max_deadline": _cap(form, period).isoformat(),
        "reopen_count": form["reopen_count"],
        "extension_count": form["extension_count"],
        "evaluators": evaluators,
        "goals": goals,
        "total_weight": total,
        "weight_ok": total == 100,
    }


def list_periods(engine, company="", status=""):
    q = select(review_periods).order_by(review_periods.c.company, review_periods.c.start_date)
    if _s(company):
        q = q.where(func.lower(review_periods.c.company) == _s(company).lower())
    if _s(status):
        q = q.where(review_periods.c.status == _s(status).upper())
    with engine.connect() as c:
        return {"periods": [_period_out(c, dict(p)) for p in c.execute(q).mappings().all()]}


def get_period(engine, period_id):
    with engine.connect() as c:
        return _period_out(c, _period_row(c, period_id))


def find_forms(engine, email="", username="", period_id="", kind=""):
    """Forms of one employee (by email or username), optionally narrowed by period and kind."""
    with engine.connect() as c:
        q = select(review_forms).order_by(review_forms.c.id)
        if _s(email):
            row = c.execute(select(users.c.username)
                            .where(func.lower(users.c.email) == _s(email).lower())).first()
            if row is None:
                raise ServiceError(404, "USER_NOT_FOUND", f"Không tìm thấy nhân viên có email '{_s(email)}'")
            q = q.where(review_forms.c.username == row[0])
        if _s(username):
            q = q.where(review_forms.c.username == _s(username))
        if _s(period_id):
            q = q.where(review_forms.c.period_id == _s(period_id))
        if _s(kind):
            q = q.where(review_forms.c.kind == _s(kind).upper())
        return {"forms": [_form_out(c, dict(f)) for f in c.execute(q).mappings().all()]}


def get_form(engine, form_id):
    with engine.connect() as c:
        return _form_out(c, _form_row(c, form_id))


def list_log(engine, ticket="", target=""):
    cols = (review_log.c.id, review_log.c.at, review_log.c.ticket, review_log.c.actor, review_log.c.action,
            review_log.c.target, review_log.c.detail)
    q = select(*cols).order_by(review_log.c.id.desc()).limit(200)
    if _s(ticket):
        q = q.where(review_log.c.ticket == _ticket(ticket, "agent"))
    if _s(target):
        q = q.where(review_log.c.target == _s(target))
    with engine.connect() as c:
        return {"entries": [dict(r, actor=r["actor"] or "agent") for r in c.execute(q).mappings().all()]}


# ---------- periods ----------

def _slug(company):
    code = re.sub(r"[^A-Za-z0-9]", "", _s(company)).upper()
    if not code:
        raise ServiceError(422, "VALIDATION_ERROR", "company: thiếu tên công ty / đơn vị (ví dụ 'VinFast')")
    return code


def create_period(engine, company, kind, year, number, start_date, deadline, ticket="", actor="agent"):
    ticket = _ticket(ticket, actor)
    kind = _s(kind).upper()
    if kind not in PERIOD_KINDS:
        raise ServiceError(422, "INVALID_KIND", f"kind phải là một trong: {', '.join(PERIOD_KINDS)}")
    if not isinstance(year, int) or not 2020 <= year <= 2100:
        raise ServiceError(422, "VALIDATION_ERROR", "year: năm không hợp lệ (2020-2100)")
    number = number or 0
    if kind == "KPI_MONTH" and not 1 <= number <= 12:
        raise ServiceError(422, "VALIDATION_ERROR", "number: tháng phải từ 1 đến 12")
    if kind == "KPI_QUARTER" and not 1 <= number <= 4:
        raise ServiceError(422, "VALIDATION_ERROR", "number: quý phải từ 1 đến 4")
    start, end = _date(start_date, "start_date"), _date(deadline, "deadline")
    if end <= start:
        raise ServiceError(422, "INVALID_DATE", "deadline phải sau start_date")
    company = _s(company)
    suffix, label = {
        "KPI_MONTH": (f"T{number}", f"KPI tháng {number}/{year}"),
        "KPI_QUARTER": (f"Q{number}", f"KPI quý {number}/{year}"),
        "KPI_YEAR": ("Y", f"KPI năm {year}"),
        "REVIEW_360": ("360", f"Đánh giá 360 năm {year}"),
    }[kind]
    pid = f"{_slug(company)}-{suffix}-{year}"
    row = {"id": pid, "name": f"{label} - {company}", "company": company, "kind": kind,
           "start_date": start.isoformat(), "deadline": end.isoformat(), "original_deadline": end.isoformat(),
           "status": "OPEN", "extension_count": 0}
    try:
        with engine.begin() as c:
            if c.execute(select(review_periods.c.id).where(review_periods.c.id == pid)).first():
                raise ServiceError(409, "PERIOD_EXISTS", f"Kỳ {pid} đã có, không tạo trùng. Muốn đổi hạn thì gia hạn hoặc mở lại kỳ.")
            c.execute(review_periods.insert().values(**row))
            _log(c, actor, ticket, "CreateReviewPeriod", pid, f"Tạo {row['name']}, {_vn(start)} - {_vn(end)}")
            out = _period_out(c, row)
    except IntegrityError:
        raise ServiceError(409, "PERIOD_EXISTS", f"Kỳ {pid} đã có, không tạo trùng.") from None
    return _done(f"Đã tạo kỳ {row['name']} ({pid}), mở từ {_vn(start)} đến {_vn(end)}.", period=out)


def reopen_period(engine, period_id, deadline, ticket="", actor="agent"):
    ticket = _ticket(ticket, actor)
    new = _date(deadline, "deadline")
    with engine.begin() as c:
        p = _period_row(c, period_id)
        if p["status"] == "LOCKED":
            raise ServiceError(409, "PERIOD_LOCKED", f"Kỳ {p['name']} đã chốt kết quả, không mở lại được.")
        if p["status"] == "OPEN":
            raise ServiceError(409, "PERIOD_ALREADY_OPEN",
                               f"Kỳ {p['name']} đang mở (hạn {_vn(p['deadline'])}). Muốn lùi hạn thì dùng ExtendReviewPeriod.")
        if new <= date.fromisoformat(p["deadline"]):
            raise ServiceError(422, "INVALID_DEADLINE", f"Hạn mới phải sau hạn cũ {_vn(p['deadline'])}.")
        c.execute(update(review_periods).where(review_periods.c.id == p["id"])
                  .values(status="OPEN", deadline=new.isoformat(), original_deadline=new.isoformat()))
        _log(c, actor, ticket, "ReopenReviewPeriod", p["id"], f"Mở lại kỳ, hạn {_vn(p['deadline'])} -> {_vn(new)}")
        out = _period_out(c, _period_row(c, p["id"]))
    return _done(f"Đã mở lại kỳ {p['name']}, hạn mới {_vn(new)}.", period=out)


def extend_period(engine, period_id, deadline, ticket="", actor="agent"):
    ticket = _ticket(ticket, actor)
    new = _date(deadline, "deadline")
    with engine.begin() as c:
        p = _period_row(c, period_id)
        if p["status"] == "LOCKED":
            raise ServiceError(409, "PERIOD_LOCKED", f"Kỳ {p['name']} đã chốt kết quả, không gia hạn được.")
        if p["status"] == "CLOSED":
            raise ServiceError(409, "PERIOD_CLOSED", f"Kỳ {p['name']} đã đóng. Dùng ReopenReviewPeriod để mở lại kèm hạn mới.")
        old = date.fromisoformat(p["deadline"])
        if new == old:
            return _no_change(f"Kỳ {p['name']} đã có hạn {_vn(old)}.", period=_period_out(c, p))
        if new < old:
            raise ServiceError(422, "INVALID_DEADLINE", f"Hạn mới phải sau hạn hiện tại {_vn(old)}.")
        cap = date.fromisoformat(p["original_deadline"]) + timedelta(days=MAX_EXTENSION_DAYS)
        if new > cap:
            raise ServiceError(422, "EXTENSION_TOO_LONG",
                               f"Chỉ gia hạn tối đa {MAX_EXTENSION_DAYS} ngày so với hạn gốc, tức đến {_vn(cap)}.")
        c.execute(update(review_periods).where(review_periods.c.id == p["id"])
                  .values(deadline=new.isoformat(), extension_count=p["extension_count"] + 1))
        _log(c, actor, ticket, "ExtendReviewPeriod", p["id"], f"Gia hạn kỳ {_vn(old)} -> {_vn(new)}")
        out = _period_out(c, _period_row(c, p["id"]))
    return _done(f"Đã gia hạn kỳ {p['name']} từ {_vn(old)} đến {_vn(new)}.", period=out)


def import_results(engine, period_id, rows, ticket="", actor="agent"):
    """All or nothing: any bad row rejects the whole upload, so nothing half-imported is left behind."""
    ticket = _ticket(ticket, actor)
    rows = rows or []
    if not rows:
        raise ServiceError(422, "VALIDATION_ERROR", "rows: danh sách kết quả đang trống")
    with engine.begin() as c:
        p = _period_row(c, period_id)
        if p["status"] == "OPEN":
            raise ServiceError(409, "PERIOD_OPEN", f"Kỳ {p['name']} đang mở. Chỉ tải kết quả khi kỳ đã đóng.")
        if p["status"] == "LOCKED":
            raise ServiceError(409, "PERIOD_LOCKED", f"Kỳ {p['name']} đã chốt kết quả, không tải lại được.")
        errors, clean, seen = [], [], set()
        for i, r in enumerate(rows, 1):
            email = _s(r.get("email")).lower()
            grade = _s(r.get("grade")).upper()
            score = r.get("score")
            u = c.execute(select(users.c.username, users.c.role)
                          .where(func.lower(users.c.email) == email)).first() if email else None
            if u is None or u[1] == "admin":
                errors.append(f"dòng {i}: không có nhân viên '{email}'")
            elif email in seen:
                errors.append(f"dòng {i}: '{email}' bị lặp")
            elif not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
                errors.append(f"dòng {i}: điểm phải là số nguyên 0-100")
            elif grade not in GRADES:
                errors.append(f"dòng {i}: xếp loại phải là {'/'.join(GRADES)}")
            else:
                seen.add(email)
                clean.append({"period_id": p["id"], "username": u[0], "score": score, "grade": grade})
        if errors:
            raise ServiceError(422, "INVALID_ROWS", "Không tải kết quả nào. " + "; ".join(errors))
        replaced = 0
        for r in clean:
            res = c.execute(delete(review_results).where(and_(
                review_results.c.period_id == r["period_id"], review_results.c.username == r["username"])))
            replaced += res.rowcount
            c.execute(review_results.insert().values(**r))
        _log(c, actor, ticket, "ImportReviewResults", p["id"], f"Tải {len(clean)} kết quả HQCV ({replaced} dòng ghi đè)")
        out = _period_out(c, p)
    return _done(f"Đã tải {len(clean)} kết quả HQCV vào kỳ {p['name']}"
                 + (f", trong đó {replaced} người đã có kết quả cũ và được ghi đè." if replaced else "."),
                 imported=len(clean), replaced=replaced, period=out)


# ---------- forms ----------

def _editable(form, period, employee, action):
    """Checks shared by every change to a form, in the order a technician would want to hear them."""
    if employee["status"] == RESIGNED:
        raise ServiceError(409, "EMPLOYEE_RESIGNED",
                           f"{employee['display_name']} ({employee['email']}) đã nghỉ việc, không {action}.")
    if period and period["status"] == "LOCKED":
        raise ServiceError(409, "PERIOD_LOCKED", f"Kỳ {period['name']} đã chốt kết quả, không {action}.")
    if form["status"] == "LOCKED":
        raise ServiceError(409, "FORM_LOCKED", f"Phiếu {form['id']} đã chốt, không {action}.")


def reopen_form(engine, form_id, deadline, ticket="", actor="agent"):
    """Back to DRAFT so the employee can edit again ('mở lại phiếu'). A form whose period is closed needs
    a personal deadline: that reopens the period for this employee only."""
    ticket = _ticket(ticket, actor)
    with engine.begin() as c:
        f = _form_row(c, form_id)
        period, emp = _form_ctx(c, f)
        _editable(f, period, emp, "mở lại phiếu được")
        changes, notes = {}, []
        if _s(deadline):
            new = _date(deadline, "deadline")
            current = date.fromisoformat(_effective_deadline(f, period))
            if new <= current:
                raise ServiceError(422, "INVALID_DEADLINE", f"Hạn riêng phải sau hạn hiện tại {_vn(current)}.")
            changes.update(deadline=new.isoformat(), base_deadline=new.isoformat())
            notes.append(f"hạn riêng {_vn(new)}")
        elif period and period["status"] == "CLOSED" and not f["deadline"]:
            raise ServiceError(422, "DEADLINE_REQUIRED",
                               f"Kỳ {period['name']} đã đóng: cần hạn riêng (deadline) cho phiếu này, "
                               "hoặc mở lại cả kỳ bằng ReopenReviewPeriod.")
        if f["status"] != "DRAFT":
            changes.update(status="DRAFT", reopen_count=f["reopen_count"] + 1)
            notes.insert(0, f"{FORM_STATUS[f['status']]} -> {FORM_STATUS['DRAFT']}")
        if not changes:
            return _no_change(f"Phiếu {f['id']} đang ở trạng thái {FORM_STATUS['DRAFT']}, nhân viên sửa được ngay.",
                              form=_form_out(c, f))
        c.execute(update(review_forms).where(review_forms.c.id == f["id"]).values(**changes))
        _log(c, actor, ticket, "ReopenReviewForm", f["id"], "Mở lại phiếu: " + ", ".join(notes))
        out = _form_out(c, _form_row(c, f["id"]))
    return _done(f"Đã mở lại {FORM_KINDS[f['kind']].lower()} {f['id']} của {emp['display_name']}: "
                 + ", ".join(notes) + ".", form=out)


def extend_form(engine, form_id, deadline, ticket="", actor="agent"):
    ticket = _ticket(ticket, actor)
    new = _date(deadline, "deadline")
    with engine.begin() as c:
        f = _form_row(c, form_id)
        period, emp = _form_ctx(c, f)
        _editable(f, period, emp, "gia hạn được")
        if f["status"] == "APPROVED":
            raise ServiceError(409, "FORM_APPROVED", f"Phiếu {f['id']} đã phê duyệt, không cần gia hạn. "
                                                     "Muốn sửa nội dung thì mở lại phiếu (ReopenReviewForm).")
        if period and period["status"] == "CLOSED" and not f["deadline"]:
            raise ServiceError(409, "PERIOD_CLOSED", f"Kỳ {period['name']} đã đóng. Dùng ReopenReviewForm kèm hạn riêng, "
                                                     "hoặc ReopenReviewPeriod để mở lại cả kỳ.")
        old = date.fromisoformat(_effective_deadline(f, period))
        if new == old:
            return _no_change(f"Phiếu {f['id']} đã có hạn {_vn(old)}.", form=_form_out(c, f))
        if new < old:
            raise ServiceError(422, "INVALID_DEADLINE", f"Hạn mới phải sau hạn hiện tại {_vn(old)}.")
        cap = _cap(f, period)
        if new > cap:
            raise ServiceError(422, "EXTENSION_TOO_LONG",
                               f"Chỉ gia hạn tối đa {MAX_EXTENSION_DAYS} ngày so với hạn gốc, tức đến {_vn(cap)}.")
        c.execute(update(review_forms).where(review_forms.c.id == f["id"])
                  .values(deadline=new.isoformat(), extension_count=f["extension_count"] + 1))
        _log(c, actor, ticket, "ExtendReviewForm", f["id"], f"Gia hạn phiếu {_vn(old)} -> {_vn(new)}")
        out = _form_out(c, _form_row(c, f["id"]))
    return _done(f"Đã gia hạn {FORM_KINDS[f['kind']].lower()} {f['id']} của {emp['display_name']} "
                 f"từ {_vn(old)} đến {_vn(new)}.", form=out)


def update_evaluator(engine, form_id, new_email, old_email, ticket="", actor="agent"):
    ticket = _ticket(ticket, actor)
    new, old = _s(new_email).lower(), _s(old_email).lower()
    if not _EMAIL.match(new):
        raise ServiceError(422, "VALIDATION_ERROR", f"new_email: '{new}' không phải email hợp lệ")
    with engine.begin() as c:
        f = _form_row(c, form_id)
        period, emp = _form_ctx(c, f)
        _editable(f, period, emp, "đổi người đánh giá được")
        if f["status"] == "APPROVED":
            raise ServiceError(409, "FORM_APPROVED", f"Phiếu {f['id']} đã phê duyệt, không đổi người đánh giá. "
                                                     "Cần đổi thì mở lại phiếu trước (ReopenReviewForm).")
        if new == (emp["email"] or "").lower():
            raise ServiceError(422, "SELF_EVALUATOR", "Nhân viên không thể là người đánh giá phiếu của chính mình.")
        known = c.execute(select(users.c.status, users.c.display_name)
                          .where(func.lower(users.c.email) == new)).first()
        if known is not None and (known[0] or "").upper() == RESIGNED:
            raise ServiceError(422, "EVALUATOR_RESIGNED", f"{known[1]} ({new}) đã nghỉ việc, không làm người đánh giá được.")
        current = {e: r for e, r in c.execute(
            select(review_evaluators.c.email, review_evaluators.c.relation)
            .where(review_evaluators.c.form_id == f["id"])).all()}
        if not old:
            if len(current) > 1:
                raise ServiceError(422, "OLD_EVALUATOR_REQUIRED",
                                   f"Phiếu {f['id']} có {len(current)} người đánh giá ({', '.join(sorted(current))}). "
                                   "Cho biết old_email là người cần thay.")
            old = next(iter(current), "")
        if old and old not in current:
            raise ServiceError(404, "EVALUATOR_NOT_FOUND", f"'{old}' không phải người đánh giá của phiếu {f['id']}.")
        if new == old:
            return _no_change(f"{new} đã là người đánh giá của phiếu {f['id']}.", form=_form_out(c, f))
        if new in current:
            raise ServiceError(409, "EVALUATOR_DUPLICATE", f"{new} đã là người đánh giá khác của phiếu {f['id']}.")
        relation = current.get(old, "manager")
        if old:
            c.execute(delete(review_evaluators).where(and_(
                review_evaluators.c.form_id == f["id"], review_evaluators.c.email == old)))
        c.execute(review_evaluators.insert().values(form_id=f["id"], email=new, relation=relation))
        _log(c, actor, ticket, "UpdateReviewEvaluator", f["id"], f"Người đánh giá ({relation}): {old or '(trống)'} -> {new}")
        out = _form_out(c, _form_row(c, f["id"]))
    return _done(f"Đã đổi người đánh giá {RELATIONS.get(relation, relation).lower()} của phiếu {f['id']} "
                 f"({emp['display_name']}) từ {old or '(trống)'} sang {new}.", form=out)


# ---------- goals / criteria ----------

def _goal_ctx(conn, goal_id, action):
    row = conn.execute(select(review_goals).where(review_goals.c.id == _s(goal_id))).mappings().first()
    if row is None:
        raise ServiceError(404, "GOAL_NOT_FOUND", f"Không tìm thấy mục tiêu / tiêu chí '{_s(goal_id)}'")
    goal = dict(row)
    f = _form_row(conn, goal["form_id"])
    period, emp = _form_ctx(conn, f)
    _editable(f, period, emp, action)
    if f["status"] == "APPROVED":
        raise ServiceError(409, "FORM_APPROVED", f"Phiếu {f['id']} đã phê duyệt nên không {action}. "
                                                 "Mở lại phiếu (ReopenReviewForm) trước, rồi làm lại.")
    return goal, f, emp


def _weight_note(form_out):
    if form_out["weight_ok"]:
        return ""
    return f" Tổng trọng số còn {form_out['total_weight']}%, cần điều chỉnh lại cho đủ 100%."


def update_goal(engine, goal_id, title, weight, target, ticket="", actor="agent"):
    ticket = _ticket(ticket, actor)
    with engine.begin() as c:
        g, f, emp = _goal_ctx(c, goal_id, "sửa mục tiêu được")
        changes = {}
        if _s(title) and _s(title) != g["title"]:
            changes["title"] = _s(title)
        if weight:  # 0 / blank = unchanged (Copilot Studio sends 0 for an empty integer)
            if not isinstance(weight, int) or not 1 <= weight <= 100:
                raise ServiceError(422, "VALIDATION_ERROR", "weight: trọng số phải là số nguyên 1-100")
            if weight != g["weight"]:
                changes["weight"] = weight
        if _s(target) and _s(target) != g["target"]:
            changes["target"] = _s(target)
        if not changes:
            out = _form_out(c, f)
            return _no_change(f"Mục tiêu {g['id']} không có gì thay đổi.", goal=g, form=out)
        c.execute(update(review_goals).where(review_goals.c.id == g["id"]).values(**changes))
        detail = ", ".join(f"{k}: {g[k]} -> {v}" for k, v in changes.items())
        _log(c, actor, ticket, "UpdateReviewGoal", g["id"], detail)
        goal = dict(c.execute(select(review_goals).where(review_goals.c.id == g["id"])).mappings().first())
        out = _form_out(c, f)
    return _done(f"Đã sửa mục tiêu {g['id']} trong phiếu {f['id']} của {emp['display_name']} ({detail})."
                 + _weight_note(out), goal=goal, form=out)


def delete_goal(engine, goal_id, ticket="", actor="agent"):
    ticket = _ticket(ticket, actor)
    with engine.begin() as c:
        g, f, emp = _goal_ctx(c, goal_id, "xóa mục tiêu được")
        c.execute(delete(review_goals).where(review_goals.c.id == g["id"]))
        _log(c, actor, ticket, "DeleteReviewGoal", g["id"], f"Xóa '{g['title']}' ({g['weight']}%) khỏi phiếu {f['id']}")
        out = _form_out(c, f)
    return _done(f"Đã xóa mục tiêu '{g['title']}' ({g['weight']}%) khỏi phiếu {f['id']} của {emp['display_name']}."
                 + _weight_note(out), goal=g, form=out)
