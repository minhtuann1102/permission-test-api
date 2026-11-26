"""Approval check (thẩm định) for permission / account tickets.

Two pieces, both pure rules (no AI):
- check_org: is the approver on the requester's management chain, at or above the minimum level, still active?
- parse_approval_mail: read an approval mail (.eml) attached to a ticket: who approved (from the header when
  possible), what they wrote, and the quoted original request. The agent then judges with AI only whether the
  reply means "yes" and whether the original request matches the ticket.

Real approvals look like this: the requester mails their manager, the manager replies just "Ok", the requester
attaches that reply to the ticket. What was approved is only visible in the subject (RE: ...) and the quote.
"""
import base64
import binascii
import email
import html
import re
from email import policy
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from sqlalchemy import select

from permapp.db import org_people
from permapp.service import ServiceError

LEVELS = ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8", "T9"]
LEVEL_NAMES = {"T1": "Tổng giám đốc", "T2": "Senior Director", "T3": "Director", "T4": "Trưởng phòng",
               "T5": "Trưởng nhóm", "T6": "Senior", "T7": "Nhân viên", "T8": "Nhân viên", "T9": "Nhân viên"}
# Minimum approver level per request type. The agent never classifies tickets itself: Master passes MINIAPP when
# the ticket goes to Miniapp Permission Agent, anything else is KHAC (the stricter default).
MIN_LEVEL = {"MINIAPP": "T4", "KHAC": "T3"}
MAX_CHAIN = 20


def _norm_email(value):
    return (value or "").strip().lower()


def normalize_request_type(value):
    v = (value or "").strip().upper().replace("Á", "A")
    return "MINIAPP" if v == "MINIAPP" else "KHAC"


def _rank(level):
    return LEVELS.index(level) if level in LEVELS else len(LEVELS)


def _person(conn, email_addr):
    row = conn.execute(select(org_people).where(org_people.c.email == _norm_email(email_addr))).mappings().first()
    return dict(row) if row else None


def _brief(p):
    if not p:
        return {"found": False, "email": "", "name": "", "level": "", "level_name": "", "title": "",
                "department": "", "status": ""}
    return {"found": True, "email": p["email"], "name": p["name"], "level": p["level"],
            "level_name": LEVEL_NAMES.get(p["level"], ""), "title": p["title"], "department": p["department"],
            "status": p["status"]}


def management_chain(conn, person):
    """The requester's managers, nearest first. Stops at the top, at an unknown email or at a loop."""
    chain, seen = [], {person["email"]}
    nxt = person["manager_email"]
    while nxt and len(chain) < MAX_CHAIN:
        boss = _person(conn, nxt)
        if boss is None or boss["email"] in seen:
            break
        chain.append(boss)
        seen.add(boss["email"])
        nxt = boss["manager_email"]
    return chain


def list_org(engine):
    """Everyone in the org chart, most senior first, each with their direct reports' count."""
    with engine.connect() as conn:
        rows = [dict(r) for r in conn.execute(select(org_people)).mappings()]
    reports = {}
    for p in rows:
        if p["manager_email"]:
            reports[p["manager_email"]] = reports.get(p["manager_email"], 0) + 1
    emails = {p["email"] for p in rows}
    rows.sort(key=lambda p: (_rank(p["level"]), p["email"]))
    people = [{**_brief(p), "manager_email": p["manager_email"],
               "manager_found": not p["manager_email"] or p["manager_email"] in emails,
               "direct_reports": reports.get(p["email"], 0)} for p in rows]
    return {"count": len(people), "people": people}


def org_tree(people):
    """Group list_org people into trees: [(person, children), ...]. A person whose manager is unknown is a root.
    People caught in a manager loop have no root; they are returned as extra roots so nobody is hidden."""
    by_manager = {}
    for p in people:
        by_manager.setdefault(p["manager_email"] if p["manager_found"] else "", []).append(p)
    placed = set()

    def build(person):
        placed.add(person["email"])
        return person, [build(c) for c in by_manager.get(person["email"], []) if c["email"] not in placed]

    roots = [build(p) for p in by_manager.get("", [])]
    roots += [build(p) for p in people if p["email"] not in placed]
    return roots


def check_org(engine, requester_email, approver_email, request_type):
    """Always returns data (never raises for unknown people): a 'no' is an answer for the agent, not a failure."""
    rtype = normalize_request_type(request_type)
    min_level = MIN_LEVEL[rtype]
    reasons = []
    with engine.connect() as conn:
        req = _person(conn, requester_email)
        appr = _person(conn, approver_email) if _norm_email(approver_email) else None
        chain = management_chain(conn, req) if req else []

    relation = "unknown"
    if req is None:
        reasons.append(f"Không tìm thấy requester {requester_email or '(trống)'} trong sơ đồ tổ chức.")
    if not _norm_email(approver_email):
        reasons.append("Chưa có người duyệt.")
    elif appr is None:
        reasons.append(f"Không tìm thấy người duyệt {approver_email} trong sơ đồ tổ chức.")

    if req and appr:
        if appr["email"] == req["email"]:
            relation = "self"
            reasons.append("Người duyệt chính là requester.")
        elif chain and appr["email"] == chain[0]["email"]:
            relation = "direct_manager"
        elif any(p["email"] == appr["email"] for p in chain):
            relation = "upper_manager"
        else:
            relation = "not_on_chain"
            reasons.append(f"{appr['name']} không nằm trên tuyến quản lý của {req['name']}.")

    level_ok = bool(appr) and _rank(appr["level"]) <= _rank(min_level)
    if appr and not level_ok:
        reasons.append(f"{appr['name']} là {appr['level']} ({LEVEL_NAMES.get(appr['level'], '')}), "
                       f"loại yêu cầu này cần {min_level} ({LEVEL_NAMES[min_level]}) trở lên.")
    active = bool(appr) and appr["status"] == "ACTIVE"
    if appr and not active:
        reasons.append(f"{appr['name']} đã nghỉ việc.")

    approved = relation in ("direct_manager", "upper_manager") and level_ok and active
    suggested = next((p for p in chain if _rank(p["level"]) <= _rank(min_level) and p["status"] == "ACTIVE"), None)
    if approved:
        rel_text = "quản lý trực tiếp" if relation == "direct_manager" else "cấp trên của quản lý trực tiếp"
        reasons = [f"{appr['name']} ({appr['level']}) là {rel_text} của {req['name']}, đạt bậc tối thiểu {min_level}."]
    return {
        "request_type": rtype,
        "min_level": min_level,
        "requester": _brief(req),
        "approver": _brief(appr),
        "relation": relation,
        "on_chain": relation in ("direct_manager", "upper_manager"),
        "level_ok": level_ok,
        "approver_active": active,
        "approved_by_org": approved,
        "chain": [{"email": p["email"], "name": p["name"], "level": p["level"], "status": p["status"]} for p in chain],
        "suggested_approver": _brief(suggested),
        "reasons": reasons,
    }


# ---------------------------------------------------------------- approval mail (.eml)

_QUOTE_KEYS = {
    "from": "from", "từ": "from",
    "sent": "sent", "date": "sent", "đã gửi": "sent", "ngày gửi": "sent", "ngày": "sent",
    "to": "to", "đến": "to", "gửi đến": "to",
    "cc": "cc",
    "subject": "subject", "chủ đề": "subject", "tiêu đề": "subject",
}
_HEADER_LINE = re.compile(r"^\s*\*?\s*([A-Za-zÀ-ỹ ]{2,12})\s*\*?\s*:\s*(.*)$")
_SEPARATOR = re.compile(r"^\s*(_{5,}|-{5,}\s*(original message|thư gốc)?\s*-*)\s*$", re.IGNORECASE)
_FORWARD = re.compile(r"^\s*(fw|fwd|tl|chuyển tiếp)\s*:", re.IGNORECASE)
_REPLY = re.compile(r"^\s*(re|tr|trả lời)\s*:", re.IGNORECASE)
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp")
MAX_TEXT = 1500


def _html_to_text(value):
    value = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", value)
    value = re.sub(r"\s+", " ", value)  # newlines in HTML source are just spaces; only tags break lines
    value = re.sub(r"(?i)\s*(<br\s*/?>|</p>|</div>|</tr>|<hr[^>]*>)\s*", "\n", value)
    value = re.sub(r"<[^>]+>", "", value)
    return html.unescape(value).replace("\xa0", " ")


def _body_text(msg):
    part = msg.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    text = part.get_content()
    if part.get_content_type() == "text/html":
        text = _html_to_text(text)
    return text.replace("\r\n", "\n")


def _addr(value):
    name, addr = parseaddr(value or "")
    return {"name": name.strip().strip('"'), "email": _norm_email(addr)}


def _addrs(value):
    return [{"name": n.strip().strip('"'), "email": _norm_email(a)} for n, a in getaddresses([value or ""]) if a]


def _quote_header_at(lines, i):
    """If a quoted header block (From / Sent / To / Subject) starts at line i, return (headers, next_line)."""
    m = _HEADER_LINE.match(lines[i])
    if not m or _QUOTE_KEYS.get(m.group(1).strip().lower()) != "from":
        return None
    headers, j = {}, i
    while j < len(lines) and lines[j].strip():
        hm = _HEADER_LINE.match(lines[j])
        if not hm:
            break
        key = _QUOTE_KEYS.get(hm.group(1).strip().lower())
        if key:
            headers[key] = hm.group(2).strip()
        j += 1
    if "sent" not in headers and "subject" not in headers:
        return None  # a line that merely starts with "From:" in normal text
    return headers, j


def _clean(lines):
    kept = [ln.rstrip() for ln in lines if not _SEPARATOR.match(ln)]
    text = "\n".join(kept).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text[:MAX_TEXT]


def split_quotes(text):
    """Split a mail body into the top text and the quoted messages below it, nearest quote first."""
    lines = text.split("\n")
    top, quotes, cur_lines, cur_headers = [], [], None, None
    i = 0
    while i < len(lines):
        found = _quote_header_at(lines, i)
        if found:
            if cur_headers is not None:
                quotes.append((cur_headers, cur_lines))
            cur_headers, i = found
            cur_lines = []
            continue
        (top if cur_headers is None else cur_lines).append(lines[i])
        i += 1
    if cur_headers is not None:
        quotes.append((cur_headers, cur_lines))
    out = []
    for headers, body in quotes:
        out.append({
            "from": _addr(headers.get("from")),
            "to": _addrs(headers.get("to")),
            "cc": _addrs(headers.get("cc")),
            "sent": headers.get("sent", ""),
            "subject": headers.get("subject", ""),
            "body": _clean(body),
        })
    return _clean(top), out


def _empty_result(file_name, fmt, supported, warning):
    return {"file_name": file_name, "format": fmt, "supported": supported, "kind": "", "trust": "", "subject": "",
            "date": "", "header_from": _addr(""), "header_to": [], "approver": {"name": "", "email": "", "source": ""},
            "reply_text": "", "original_request": None, "quoted": [], "checks": {}, "warnings": [warning]}


def parse_approval_mail(file_name, content_base64, requester_email=""):
    file_name = (file_name or "").strip()
    if not content_base64:
        raise ServiceError(422, "VALIDATION_ERROR", "Thiếu nội dung file (content_base64).")
    try:
        raw = base64.b64decode(content_base64, validate=False)
    except (binascii.Error, ValueError):
        raise ServiceError(422, "INVALID_FILE", "content_base64 không phải base64 hợp lệ.")
    lower = file_name.lower()
    if lower.endswith(_IMAGE_EXT):
        return _empty_result(file_name, "image", False,
                             "Ảnh chụp màn hình: API không đọc ảnh. Agent đọc chữ trong ảnh, độ tin cậy luôn thấp.")
    if lower.endswith(".msg"):
        return _empty_result(file_name, "msg", False,
                             "File .msg của Outlook chưa đọc được trong bản giả lập. Lưu mail dạng .eml rồi đính kèm lại.")

    msg = email.message_from_bytes(raw, policy=policy.default)
    if not msg.get("From"):
        return _empty_result(file_name, "unknown", False, "File không phải là mail (.eml).")

    subject = str(msg.get("Subject", "") or "")
    try:
        date = parsedate_to_datetime(str(msg.get("Date"))).isoformat() if msg.get("Date") else ""
    except (TypeError, ValueError):
        date = ""
    top, quoted = split_quotes(_body_text(msg))
    header_from = _addr(str(msg.get("From", "")))
    warnings = []

    if _FORWARD.match(subject):
        kind, trust = "forward", "low"
        first = quoted[0] if quoted else None
        approver = {**(first["from"] if first else {"name": "", "email": ""}), "source": "quoted"}
        reply_text = first["body"] if first else ""
        rest = quoted[1:]
        warnings.append("Mail forward: người duyệt lấy từ phần trích, có thể bị sửa. Technician cần xác nhận lại.")
    else:
        kind = "reply" if _REPLY.match(subject) else "other"
        trust = "high"
        approver = {**header_from, "source": "header"}
        reply_text = top
        rest = quoted

    original = next((q for q in rest if q["from"]["email"] and q["from"]["email"] != approver["email"]), None)
    if original is None:
        warnings.append("Không có phần trích mail gốc: không biết người duyệt đồng ý việc gì.")

    checks = {}
    if original is not None:
        checks["approver_in_original_recipients"] = approver["email"] in {
            a["email"] for a in original["to"] + original["cc"]}
        if _norm_email(requester_email):
            checks["original_from_requester"] = original["from"]["email"] == _norm_email(requester_email)

    return {
        "file_name": file_name,
        "format": "eml",
        "supported": True,
        "kind": kind,
        "trust": trust,
        "subject": subject,
        "date": date,
        "header_from": header_from,
        "header_to": _addrs(str(msg.get("To", "") or "")),
        "approver": approver,
        "reply_text": reply_text,
        "original_request": original,
        "quoted": quoted,
        "checks": checks,
        "warnings": warnings,
    }
