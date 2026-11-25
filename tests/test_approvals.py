import base64
import html as html_lib
import re
from email.message import EmailMessage

import pytest
from sqlalchemy import update

from permapp import approvals
from permapp.db import org_people, reset_db
from permapp.service import ServiceError
from tests.conftest import ADMIN, U1

SEP = "\n\n________________________________\n"


def quote(frm, to, subject, body, keys=("From", "Sent", "To", "Subject")):
    k_from, k_sent, k_to, k_subj = keys
    return f"{SEP}{k_from}: {frm}\n{k_sent}: Tuesday, 24 November 2026 09:05\n{k_to}: {to}\n{k_subj}: {subject}\n\n{body}\n"


def eml(frm, to, subject, body, html=False):
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = frm, to, subject
    m["Date"] = "Tue, 24 Nov 2026 10:17:00 +0700"
    if html:  # like Outlook: escaped text, bold header labels, <br> line breaks
        text = html_lib.escape(body)
        text = re.sub(r"(?m)^(From|Sent|To|Subject|Từ|Đã gửi|Đến|Chủ đề):", r"<b>\1:</b>", text)
        m.set_content("<div>" + text.replace("\n", "<br>\n") + "</div>", subtype="html")
    else:
        m.set_content(body)
    return base64.b64encode(bytes(m)).decode()


USER1 = "Người dùng 1 <user1@demo.local>"
USER2 = "Người dùng 2 <user2@demo.local>"
TP_DAOTAO = "Nguyễn Thu Hà <truongphong.daotao@demo.local>"
TP_KD = "Đỗ Minh Khang <truongphong.kinhdoanh@demo.local>"
DIR_NS = "Lê Thị Mai <director.nhansu@demo.local>"
REQ = "Chị ơi, em xin quyền dùng miniapp Nghỉ phép. Chị duyệt giúp em ạ."


# ---------------------------------------------------------------- org chart

def test_direct_manager_t4_approves_miniapp(engine):
    r = approvals.check_org(engine, "user1@demo.local", "truongphong.daotao@demo.local", "MINIAPP")
    assert r["approved_by_org"] and r["relation"] == "direct_manager" and r["min_level"] == "T4"
    assert r["approver"]["level"] == "T4" and r["approver"]["level_name"] == "Trưởng phòng"
    assert [p["email"] for p in r["chain"]] == ["truongphong.daotao@demo.local", "director.nhansu@demo.local",
                                               "sd.vanhanh@demo.local"]


def test_t4_too_low_for_other_types_and_suggests_director(engine):
    r = approvals.check_org(engine, "user1@demo.local", "truongphong.daotao@demo.local", "KHAC")
    assert not r["approved_by_org"] and r["on_chain"] and not r["level_ok"] and r["min_level"] == "T3"
    assert r["suggested_approver"]["email"] == "director.nhansu@demo.local"
    assert any("cần T3" in x for x in r["reasons"])


def test_upper_manager_on_chain_is_enough(engine):
    r = approvals.check_org(engine, "user1@demo.local", "director.nhansu@demo.local", "KHAC")
    assert r["approved_by_org"] and r["relation"] == "upper_manager"


def test_director_of_another_chain_is_rejected(engine):
    r = approvals.check_org(engine, "user2@demo.local", "director.nhansu@demo.local", "KHAC")
    assert not r["approved_by_org"] and r["relation"] == "not_on_chain" and r["level_ok"]
    assert r["suggested_approver"]["email"] == "director.kinhdoanh@demo.local"


def test_resigned_approver_is_rejected(engine):
    with engine.begin() as c:  # put the resigned manager on user2's chain
        c.execute(update(org_people).where(org_people.c.email == "user2@demo.local")
                  .values(manager_email="truongphong.kinhdoanh.cu@demo.local"))
    r = approvals.check_org(engine, "user2@demo.local", "truongphong.kinhdoanh.cu@demo.local", "MINIAPP")
    assert not r["approved_by_org"] and r["on_chain"] and not r["approver_active"]
    assert any("nghỉ việc" in x for x in r["reasons"])


def test_resigned_former_manager_off_chain(engine):
    r = approvals.check_org(engine, "user2@demo.local", "TruongPhong.KinhDoanh.Cu@demo.local ", "MINIAPP")
    assert not r["approved_by_org"] and r["relation"] == "not_on_chain" and not r["approver_active"]


def test_self_unknown_and_blank(engine):
    assert approvals.check_org(engine, "user1@demo.local", "user1@demo.local", "MINIAPP")["relation"] == "self"
    r = approvals.check_org(engine, "user1@demo.local", "ai.do@demo.local", "MINIAPP")
    assert r["relation"] == "unknown" and not r["approver"]["found"] and not r["approved_by_org"]
    r = approvals.check_org(engine, "nobody@demo.local", "", "")
    assert not r["requester"]["found"] and r["request_type"] == "KHAC" and len(r["reasons"]) == 2


@pytest.mark.parametrize("raw,expected", [("MINIAPP", "MINIAPP"), ("miniapp", "MINIAPP"), ("KHÁC", "KHAC"),
                                          ("", "KHAC"), (None, "KHAC"), ("QTNS", "KHAC")])
def test_request_type_defaults_to_strict(raw, expected):
    assert approvals.normalize_request_type(raw) == expected


def test_reset_restores_org(engine):
    with engine.begin() as c:
        c.execute(update(org_people).where(org_people.c.email == "user1@demo.local").values(level="T1"))
    reset_db(engine)
    assert approvals.check_org(engine, "user1@demo.local", "", "")["requester"]["level"] == "T7"


# ---------------------------------------------------------------- approval mail

def test_reply_ok_reads_header_and_quoted_request():
    body = "Ok" + quote(USER1, TP_DAOTAO, "Xin cấp quyền dùng miniapp Nghỉ phép", REQ)
    r = approvals.parse_approval_mail("RE.eml", eml(TP_DAOTAO, USER1, "RE: Xin cấp quyền dùng miniapp Nghỉ phép", body),
                                      "user1@demo.local")
    assert r["supported"] and r["kind"] == "reply" and r["trust"] == "high"
    assert r["approver"] == {"name": "Nguyễn Thu Hà", "email": "truongphong.daotao@demo.local", "source": "header"}
    assert r["reply_text"] == "Ok"
    assert r["original_request"]["from"]["email"] == "user1@demo.local"
    assert "Nghỉ phép" in r["original_request"]["body"]
    assert r["checks"] == {"approver_in_original_recipients": True, "original_from_requester": True}
    assert r["date"].startswith("2026-11-24T10:17") and r["warnings"] == []


def test_hedged_reply_text_is_returned_as_is():
    body = "Ok để anh xem lại đã nhé" + quote(USER2, TP_KD, "Xin quyền Chi phí", "Anh duyệt giúp em.")
    r = approvals.parse_approval_mail("a.eml", eml(TP_KD, USER2, "RE: Xin quyền Chi phí", body))
    assert r["reply_text"] == "Ok để anh xem lại đã nhé" and "original_from_requester" not in r["checks"]


def test_forward_takes_approver_from_quote_with_low_trust():
    inner = "Ok" + quote(USER2, TP_KD, "Xin quyền dùng miniapp Kho", "Anh duyệt giúp em.")
    body = "Em gửi mail anh Khang đã duyệt ạ." + quote(TP_KD, USER2, "RE: Xin quyền dùng miniapp Kho", inner)
    r = approvals.parse_approval_mail("fw.eml", eml(USER2, USER2, "FW: RE: Xin quyền dùng miniapp Kho", body),
                                      "user2@demo.local")
    assert r["kind"] == "forward" and r["trust"] == "low"
    assert r["approver"]["email"] == "truongphong.kinhdoanh@demo.local" and r["approver"]["source"] == "quoted"
    assert r["reply_text"] == "Ok"
    assert r["original_request"]["from"]["email"] == "user2@demo.local"
    assert r["checks"]["original_from_requester"] and any("forward" in w for w in r["warnings"])


def test_no_quote_warns_nothing_to_match():
    r = approvals.parse_approval_mail("ok.eml", eml(DIR_NS, USER1, "RE: Nhờ chị duyệt giúp em", "Ok\n"))
    assert r["original_request"] is None and r["checks"] == {}
    assert any("không biết người duyệt đồng ý việc gì" in w for w in r["warnings"])


def test_vietnamese_outlook_headers_and_html_body():
    body = "Đồng ý" + quote(USER1, DIR_NS, "Xin phân quyền QTNS", "Chị duyệt giúp em.",
                            keys=("Từ", "Đã gửi", "Đến", "Chủ đề"))
    r = approvals.parse_approval_mail("vi.eml", eml(DIR_NS, USER1, "TR: Xin phân quyền QTNS", body, html=True))
    assert r["kind"] == "reply" and r["reply_text"] == "Đồng ý"
    assert r["original_request"]["subject"] == "Xin phân quyền QTNS"
    assert r["original_request"]["to"][0]["email"] == "director.nhansu@demo.local"


def test_body_line_starting_with_from_is_not_a_quote():
    r = approvals.parse_approval_mail("x.eml", eml(DIR_NS, USER1, "RE: a", "Ok\nFrom: tháng sau em làm tiếp\n"))
    assert r["quoted"] == [] and "From: tháng sau" in r["reply_text"]


@pytest.mark.parametrize("name,fmt", [("chup.PNG", "image"), ("a.jpg", "image"), ("mail.msg", "msg")])
def test_images_and_msg_are_unsupported(name, fmt):
    r = approvals.parse_approval_mail(name, base64.b64encode(b"\x89PNG....").decode())
    assert r["format"] == fmt and r["supported"] is False and r["warnings"]


def test_not_a_mail_and_bad_input():
    r = approvals.parse_approval_mail("note.eml", base64.b64encode(b"just some text").decode())
    assert r["supported"] is False and r["format"] == "unknown"
    with pytest.raises(ServiceError) as e:
        approvals.parse_approval_mail("a.eml", "")
    assert e.value.code == "VALIDATION_ERROR"


# ---------------------------------------------------------------- endpoints

def test_org_check_endpoint(client):
    r = client.get("/admin/org/check", headers=ADMIN, params={
        "requester_email": "user1@demo.local", "approver_email": "director.nhansu@demo.local", "request_type": "KHAC"})
    assert r.status_code == 200 and r.json()["approved_by_org"] is True
    r = client.get("/admin/org/check", headers=ADMIN, params={"requester_email": "x@y.z"})
    assert r.status_code == 200 and r.json()["approved_by_org"] is False
    assert client.get("/admin/org/check", headers=U1).status_code == 403


def test_parse_endpoint(client):
    body = "Ok" + quote(USER1, TP_DAOTAO, "Xin quyền Nghỉ phép", REQ)
    payload = {"file_name": "RE.eml", "content_base64": eml(TP_DAOTAO, USER1, "RE: Xin quyền Nghỉ phép", body),
               "requester_email": "user1@demo.local"}
    r = client.post("/admin/approvals/parse", headers=ADMIN, json=payload)
    assert r.status_code == 200 and r.json()["approver"]["email"] == "truongphong.daotao@demo.local"
    r = client.post("/admin/approvals/parse", headers=ADMIN, json={"file_name": "a.eml", "content_base64": ""})
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    assert client.post("/admin/approvals/parse", headers=U1, json=payload).status_code == 403
