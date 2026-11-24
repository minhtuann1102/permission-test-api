"""Mock appraisal system (Đánh giá). Each test maps to a ticket type from the ILVG analysis."""
import pytest
from sqlalchemy import select

from permapp.db import init_db, review_periods, reset_db
from tests.conftest import ADMIN, U1

R = "/admin/reviews"


def _form(client, form_id):
    return client.get(f"{R}/forms/{form_id}", headers=ADMIN).json()


def _period(client, period_id):
    return client.get(f"{R}/periods/{period_id}", headers=ADMIN).json()


def _err(r, status, code):
    assert r.status_code == status, r.json()
    assert r.json()["code"] == code, r.json()
    return r.json()["detail"]


# ---------- reads ----------

def test_seed_and_reads(client):
    periods = client.get(f"{R}/periods", headers=ADMIN).json()["periods"]
    assert {p["id"] for p in periods} >= {"VINFAST-Q4-2026", "VINHOMES-Q2-2026", "VINHOMES-Q1-2026", "VINFAST-360-2026"}
    assert [p["id"] for p in client.get(f"{R}/periods", params={"status": "LOCKED"}, headers=ADMIN).json()["periods"]] == ["VINHOMES-Q1-2026"]
    q4 = _period(client, "VINFAST-Q4-2026")
    assert q4["status"] == "OPEN" and q4["max_deadline"] == "2026-12-30" and q4["form_count"] == 3

    forms = client.get(f"{R}/forms", params={"email": "USER2@demo.local"}, headers=ADMIN).json()["forms"]
    assert {f["id"] for f in forms} == {"RF-1002", "RF-1004", "RF-1007", "RF-1008"}
    f = _form(client, "RF-1001")
    assert f["employee_email"] == "user1@demo.local" and f["deadline"] == "2026-11-30" and f["total_weight"] == 100
    assert [g["id"] for g in f["goals"]] == ["G-1001-1", "G-1001-2", "G-1001-3"]
    assert len(_form(client, "RF-1003")["evaluators"]) == 3


def test_reads_accept_empty_strings_from_copilot(client):
    r = client.get(f"{R}/forms", params={"email": "", "username": "", "period_id": "", "kind": ""}, headers=ADMIN)
    assert r.status_code == 200 and len(r.json()["forms"]) == 9
    assert client.get(f"{R}/periods", params={"company": "", "status": ""}, headers=ADMIN).status_code == 200


def test_unknown_ids(client):
    _err(client.get(f"{R}/forms", params={"email": "ghost@demo.local"}, headers=ADMIN), 404, "USER_NOT_FOUND")
    _err(client.get(f"{R}/forms/RF-0", headers=ADMIN), 404, "FORM_NOT_FOUND")
    _err(client.get(f"{R}/periods/NOPE", headers=ADMIN), 404, "PERIOD_NOT_FOUND")
    _err(client.delete(f"{R}/goals/G-0", params={"ticket": "#1"}, headers=ADMIN), 404, "GOAL_NOT_FOUND")


def test_admin_only(client):
    _err(client.get(f"{R}/periods", headers=U1), 403, "ADMIN_REQUIRED")
    _err(client.delete(f"{R}/goals/G-1001-3", params={"ticket": "#1"}, headers=U1), 403, "ADMIN_REQUIRED")


def test_writes_need_no_ticket(client):
    """Real systems know nothing about SDP tickets; an old agent still sending one is not refused."""
    r = client.delete(f"{R}/goals/G-1001-3", headers=ADMIN)
    assert r.status_code == 200 and r.json()["result"] == "DONE"
    r = client.post(f"{R}/periods/VINFAST-Q4-2026/extend", json={"deadline": "2026-12-05", "ticket": "abc"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["result"] == "DONE"
    assert all("ticket" not in e for e in client.get(f"{R}/log", headers=ADMIN).json()["entries"])


def test_review_actor_from_header(client):
    client.post(f"{R}/periods/VINFAST-Q4-2026/extend", json={"deadline": "2026-12-05"},
                headers={**ADMIN, "X-Client": "console"})
    client.delete(f"{R}/goals/G-1001-3", headers=ADMIN)
    log = client.get(f"{R}/log", headers=ADMIN).json()["entries"]
    assert [(e["action"], e["actor"]) for e in log] == [("DeleteReviewGoal", "agent"), ("ExtendReviewPeriod", "console")]


# ---------- Tạo / mở lại / gia hạn kỳ ----------

def test_extend_period(client):
    """'Hỗ trợ gia hạn thêm thời hạn Kỳ đánh giá'"""
    r = client.post(f"{R}/periods/VINFAST-Q4-2026/extend", json={"deadline": "2026-12-10", "ticket": "54"}, headers=ADMIN)
    body = r.json()
    assert r.status_code == 200 and body["result"] == "DONE" and "10/12/2026" in body["message"]
    assert body["period"]["deadline"] == "2026-12-10" and body["period"]["extension_count"] == 1
    assert _form(client, "RF-1001")["deadline"] == "2026-12-10"  # forms follow the period
    same = client.post(f"{R}/periods/VINFAST-Q4-2026/extend", json={"deadline": "2026-12-10", "ticket": "#54"}, headers=ADMIN)
    assert same.json()["result"] == "NO_CHANGE"
    _err(client.post(f"{R}/periods/VINFAST-Q4-2026/extend", json={"deadline": "2026-12-01", "ticket": "#54"},
                     headers=ADMIN), 422, "INVALID_DEADLINE")
    detail = _err(client.post(f"{R}/periods/VINFAST-Q4-2026/extend", json={"deadline": "2026-12-31", "ticket": "#54"},
                              headers=ADMIN), 422, "EXTENSION_TOO_LONG")
    assert "30/12/2026" in detail


def test_extend_closed_or_locked_period_is_refused(client):
    _err(client.post(f"{R}/periods/VINHOMES-Q2-2026/extend", json={"deadline": "2026-12-01", "ticket": "#1"},
                     headers=ADMIN), 409, "PERIOD_CLOSED")
    _err(client.post(f"{R}/periods/VINHOMES-Q1-2026/extend", json={"deadline": "2026-12-01", "ticket": "#1"},
                     headers=ADMIN), 409, "PERIOD_LOCKED")


def test_reopen_period(client):
    """'Mở lại kỳ đánh giá quý 2.2026'"""
    r = client.post(f"{R}/periods/VINHOMES-Q2-2026/reopen", json={"deadline": "2026-12-05", "ticket": "#60"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["result"] == "DONE"
    p = r.json()["period"]
    assert p["status"] == "OPEN" and p["deadline"] == "2026-12-05" and p["max_deadline"] == "2027-01-04"
    _err(client.post(f"{R}/periods/VINHOMES-Q2-2026/reopen", json={"deadline": "2026-12-20", "ticket": "#60"},
                     headers=ADMIN), 409, "PERIOD_ALREADY_OPEN")
    _err(client.post(f"{R}/periods/VINHOMES-Q1-2026/reopen", json={"deadline": "2026-12-20", "ticket": "#61"},
                     headers=ADMIN), 409, "PERIOD_LOCKED")
    _err(client.post(f"{R}/periods/VINFAST-Q3-2026/reopen", json={"deadline": "2026-10-01", "ticket": "#62"},
                     headers=ADMIN), 422, "INVALID_DEADLINE")


def test_create_period(client):
    """'Lập sẵn lịch kỳ đánh giá tháng / quý'"""
    body = {"company": "Vinhomes", "kind": "KPI_MONTH", "year": 2026, "number": 12,
            "start_date": "2026-12-01", "deadline": "2027-01-05", "ticket": "#70"}
    r = client.post(f"{R}/periods", json=body, headers=ADMIN)
    assert r.status_code == 200 and r.json()["period"]["id"] == "VINHOMES-T12-2026"
    assert r.json()["period"]["name"] == "KPI tháng 12/2026 - Vinhomes"
    _err(client.post(f"{R}/periods", json=body, headers=ADMIN), 409, "PERIOD_EXISTS")
    _err(client.post(f"{R}/periods", json={**body, "number": 13}, headers=ADMIN), 422, "VALIDATION_ERROR")
    _err(client.post(f"{R}/periods", json={**body, "kind": "WEEKLY"}, headers=ADMIN), 422, "INVALID_KIND")
    _err(client.post(f"{R}/periods", json={**body, "number": 11, "deadline": "2026-11-01"}, headers=ADMIN), 422, "INVALID_DATE")
    y = client.post(f"{R}/periods", json={**body, "kind": "KPI_YEAR", "year": 2027, "number": 0}, headers=ADMIN)
    assert y.json()["period"]["id"] == "VINHOMES-Y-2027"


# ---------- KPI / mục tiêu ----------

def test_delete_goal_created_by_mistake(client):
    """'Hỗ trợ xóa tiêu chí do NLĐ tạo sai' (form still DRAFT)"""
    r = client.delete(f"{R}/goals/G-1001-3", params={"ticket": "#80"}, headers=ADMIN)
    body = r.json()
    assert r.status_code == 200 and body["result"] == "DONE" and body["goal"]["id"] == "G-1001-3"
    assert body["form"]["total_weight"] == 80 and body["form"]["weight_ok"] is False
    assert "80%" in body["message"]
    assert [g["id"] for g in _form(client, "RF-1001")["goals"]] == ["G-1001-1", "G-1001-2"]


def test_delete_goal_on_approved_form_needs_reopen_first(client):
    """Approved form: reopen it, then delete (two steps the agent bundles into one plan)."""
    detail = _err(client.delete(f"{R}/goals/G-1002-3", params={"ticket": "#81"}, headers=ADMIN), 409, "FORM_APPROVED")
    assert "ReopenReviewForm" in detail
    assert len(_form(client, "RF-1002")["goals"]) == 3
    r = client.post(f"{R}/forms/RF-1002/reopen", json={"ticket": "#81"}, headers=ADMIN)
    assert r.json()["result"] == "DONE" and r.json()["form"]["status"] == "DRAFT" and r.json()["form"]["reopen_count"] == 1
    assert client.delete(f"{R}/goals/G-1002-3", params={"ticket": "#81"}, headers=ADMIN).status_code == 200


def test_update_goal(client):
    r = client.put(f"{R}/goals/G-1001-3", json={"title": "Tổ chức hội thảo chuyên môn", "weight": 0, "target": "2 hội thảo",
                                                "ticket": "#82"}, headers=ADMIN)
    body = r.json()
    assert r.status_code == 200 and body["result"] == "DONE"
    assert body["goal"]["title"] == "Tổ chức hội thảo chuyên môn" and body["goal"]["weight"] == 20
    nothing = client.put(f"{R}/goals/G-1001-3", json={"title": "", "weight": 0, "target": "", "ticket": "#82"}, headers=ADMIN)
    assert nothing.json()["result"] == "NO_CHANGE"
    _err(client.put(f"{R}/goals/G-1001-3", json={"weight": 150, "ticket": "#82"}, headers=ADMIN), 422, "VALIDATION_ERROR")
    w = client.put(f"{R}/goals/G-1001-3", json={"weight": 30, "ticket": "#82"}, headers=ADMIN).json()
    assert w["form"]["total_weight"] == 110 and "110%" in w["message"]


def test_reopen_submitted_form(client):
    """'Hỗ trợ mở hệ thống đánh giá KPI' for an employee who already submitted"""
    r = client.post(f"{R}/forms/RF-1009/reopen", json={"deadline": "", "ticket": "#83"}, headers=ADMIN)
    assert r.json()["result"] == "DONE" and r.json()["form"]["status"] == "DRAFT"
    again = client.post(f"{R}/forms/RF-1009/reopen", json={"ticket": "#83"}, headers=ADMIN)
    assert again.json()["result"] == "NO_CHANGE"


def test_reopen_form_in_closed_period_for_one_employee(client):
    """Reopen a closed period for ONE employee: personal deadline required."""
    _err(client.post(f"{R}/forms/RF-1008/reopen", json={"ticket": "#84"}, headers=ADMIN), 422, "DEADLINE_REQUIRED")
    _err(client.post(f"{R}/forms/RF-1008/extend", json={"deadline": "2026-12-01", "ticket": "#84"}, headers=ADMIN),
         409, "PERIOD_CLOSED")
    r = client.post(f"{R}/forms/RF-1008/reopen", json={"deadline": "2026-12-01", "ticket": "#84"}, headers=ADMIN)
    f = r.json()["form"]
    assert r.json()["result"] == "DONE" and f["deadline"] == "2026-12-01" and f["personal_deadline"] == "2026-12-01"
    assert f["max_deadline"] == "2026-12-31"
    assert _period(client, "VINHOMES-Q2-2026")["status"] == "CLOSED"  # the period stays closed for others
    ok = client.post(f"{R}/forms/RF-1008/extend", json={"deadline": "2026-12-15", "ticket": "#84"}, headers=ADMIN)
    assert ok.json()["result"] == "DONE"


def test_locked_period_blocks_every_form_change(client):
    _err(client.post(f"{R}/forms/RF-1007/reopen", json={"deadline": "2026-12-01", "ticket": "#85"}, headers=ADMIN),
         409, "PERIOD_LOCKED")
    _err(client.delete(f"{R}/goals/G-1007-1", params={"ticket": "#85"}, headers=ADMIN), 409, "PERIOD_LOCKED")


def test_resigned_employee_blocks_changes(client):
    detail = _err(client.delete(f"{R}/goals/G-1006-1", params={"ticket": "#86"}, headers=ADMIN), 409, "EMPLOYEE_RESIGNED")
    assert "nghỉ việc" in detail
    _err(client.post(f"{R}/forms/RF-1006/extend", json={"deadline": "2026-12-05", "ticket": "#86"}, headers=ADMIN),
         409, "EMPLOYEE_RESIGNED")


# ---------- Thử việc / hợp đồng ----------

def test_update_probation_evaluator(client):
    """'Cập nhật email đánh giá HĐ của nhân viên' (single evaluator: old_email may be empty)"""
    r = client.put(f"{R}/forms/RF-1004/evaluator",
                   json={"new_email": "truongphong.kinhdoanh@demo.local", "old_email": "", "ticket": "#90"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["result"] == "DONE"
    assert [e["email"] for e in r.json()["form"]["evaluators"]] == ["truongphong.kinhdoanh@demo.local"]
    assert "pham.van.cu@demo.local" in r.json()["message"]
    same = client.put(f"{R}/forms/RF-1004/evaluator", json={"new_email": "truongphong.kinhdoanh@demo.local", "ticket": "#90"},
                      headers=ADMIN)
    assert same.json()["result"] == "NO_CHANGE"


def test_evaluator_rules(client):
    _err(client.put(f"{R}/forms/RF-1004/evaluator", json={"new_email": "user2@demo.local", "ticket": "#91"}, headers=ADMIN),
         422, "SELF_EVALUATOR")
    _err(client.put(f"{R}/forms/RF-1004/evaluator", json={"new_email": "user3@demo.local", "ticket": "#91"}, headers=ADMIN),
         422, "EVALUATOR_RESIGNED")
    _err(client.put(f"{R}/forms/RF-1004/evaluator", json={"new_email": "not-an-email", "ticket": "#91"}, headers=ADMIN),
         422, "VALIDATION_ERROR")
    _err(client.put(f"{R}/forms/RF-1002/evaluator", json={"new_email": "a@demo.local", "ticket": "#91"}, headers=ADMIN),
         409, "FORM_APPROVED")


def test_delete_wrong_contract_criteria(client):
    """'Xóa các tiêu chí đánh giá hợp đồng sai' (two criteria, submitted form)"""
    for gid in ("G-1005-3", "G-1005-4"):
        assert client.delete(f"{R}/goals/{gid}", params={"ticket": "#92"}, headers=ADMIN).status_code == 200
    f = _form(client, "RF-1005")
    assert [g["id"] for g in f["goals"]] == ["G-1005-1", "G-1005-2"] and f["total_weight"] == 70
    log = client.get(f"{R}/log", params={"target": "G-1005-4"}, headers=ADMIN).json()["entries"]
    assert [e["target"] for e in log] == ["G-1005-4"] and log[0]["actor"] == "agent" and "ticket" not in log[0]


def test_extend_probation_form(client):
    r = client.post(f"{R}/forms/RF-1004/extend", json={"deadline": "2026-12-15", "ticket": "#93"}, headers=ADMIN)
    assert r.json()["result"] == "DONE" and r.json()["form"]["deadline"] == "2026-12-15"
    _err(client.post(f"{R}/forms/RF-1004/extend", json={"deadline": "2027-01-15", "ticket": "#93"}, headers=ADMIN),
         422, "EXTENSION_TOO_LONG")


# ---------- 360 ----------

def test_extend_360_period(client):
    """'Yêu cầu gia hạn biểu mẫu đánh giá 360 - VinFast'"""
    r = client.post(f"{R}/periods/VINFAST-360-2026/extend", json={"deadline": "2026-12-05", "ticket": "#100"}, headers=ADMIN)
    assert r.json()["result"] == "DONE" and _form(client, "RF-1003")["deadline"] == "2026-12-05"


def test_update_360_rater(client):
    """'Hỗ trợ cập nhật thông tin người đánh giá 360' (several raters: old_email required)"""
    _err(client.put(f"{R}/forms/RF-1003/evaluator", json={"new_email": "tran.thi.b@demo.local", "ticket": "#101"},
                    headers=ADMIN), 422, "OLD_EVALUATOR_REQUIRED")
    _err(client.put(f"{R}/forms/RF-1003/evaluator",
                    json={"new_email": "tran.thi.b@demo.local", "old_email": "ai.do@demo.local", "ticket": "#101"},
                    headers=ADMIN), 404, "EVALUATOR_NOT_FOUND")
    _err(client.put(f"{R}/forms/RF-1003/evaluator",
                    json={"new_email": "user2@demo.local", "old_email": "nguyen.van.a@demo.local", "ticket": "#101"},
                    headers=ADMIN), 409, "EVALUATOR_DUPLICATE")
    r = client.put(f"{R}/forms/RF-1003/evaluator",
                   json={"new_email": "Tran.Thi.B@demo.local", "old_email": "nguyen.van.a@demo.local", "ticket": "#101"},
                   headers=ADMIN)
    evs = {e["email"]: e["relation"] for e in r.json()["form"]["evaluators"]}
    assert evs == {"truongphong.daotao@demo.local": "manager", "user2@demo.local": "peer", "tran.thi.b@demo.local": "peer"}


# ---------- Upload kết quả HQCV ----------

def test_import_results(client):
    rows = [{"email": "user1@demo.local", "score": 92, "grade": "a"}, {"email": "user2@demo.local", "score": 75, "grade": "B"}]
    r = client.post(f"{R}/periods/VINFAST-Q3-2026/results", json={"rows": rows, "ticket": "#110"}, headers=ADMIN)
    assert r.json()["result"] == "DONE" and r.json()["imported"] == 2 and r.json()["period"]["result_count"] == 2
    again = client.post(f"{R}/periods/VINFAST-Q3-2026/results", json={"rows": rows[:1], "ticket": "#111"}, headers=ADMIN)
    assert again.json()["replaced"] == 1 and _period(client, "VINFAST-Q3-2026")["result_count"] == 2


def test_import_results_all_or_nothing(client):
    rows = [{"email": "user1@demo.local", "score": 92, "grade": "A"}, {"email": "ghost@demo.local", "score": 50, "grade": "C"},
            {"email": "user2@demo.local", "score": 75, "grade": "E"}]
    detail = _err(client.post(f"{R}/periods/VINFAST-Q3-2026/results", json={"rows": rows, "ticket": "#112"}, headers=ADMIN),
                  422, "INVALID_ROWS")
    assert "dòng 2" in detail and "dòng 3" in detail
    assert _period(client, "VINFAST-Q3-2026")["result_count"] == 0
    _err(client.post(f"{R}/periods/VINFAST-Q4-2026/results", json={"rows": rows[:1], "ticket": "#112"}, headers=ADMIN),
         409, "PERIOD_OPEN")
    _err(client.post(f"{R}/periods/VINHOMES-Q1-2026/results", json={"rows": rows[:1], "ticket": "#112"}, headers=ADMIN),
         409, "PERIOD_LOCKED")


# ---------- reset, migration, page ----------

def test_reset_restores_review_data(client):
    client.delete(f"{R}/goals/G-1001-3", params={"ticket": "#120"}, headers=ADMIN)
    client.post(f"{R}/periods/VINFAST-Q4-2026/extend", json={"deadline": "2026-12-10", "ticket": "#120"}, headers=ADMIN)
    assert client.post("/admin/reset", headers=ADMIN).json() == {"reset": True}
    assert len(_form(client, "RF-1001")["goals"]) == 3
    assert _period(client, "VINFAST-Q4-2026")["deadline"] == "2026-11-30"
    assert client.get(f"{R}/log", headers=ADMIN).json()["entries"] == []


def test_init_twice_and_reset_keep_one_seed(engine):
    init_db(engine)
    with engine.connect() as c:
        assert len(c.execute(select(review_periods.c.id)).all()) == 6
    reset_db(engine)
    with engine.connect() as c:
        assert len(c.execute(select(review_periods.c.id)).all()) == 6


def test_reviews_page(client):
    client.delete(f"{R}/goals/G-1001-3", params={"ticket": "#130"}, headers=ADMIN)
    r = client.get("/reviews")
    assert r.status_code == 200 and "VINFAST-Q4-2026" in r.text and "DeleteReviewGoal" in r.text and "#130" not in r.text


@pytest.mark.parametrize("path", ["/admin/reviews/periods", "/admin/reviews/forms", "/admin/reviews/log"])
def test_reads_need_a_key(client, path):
    _err(client.get(path), 401, "UNAUTHORIZED")
