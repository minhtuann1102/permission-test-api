import pytest

from tests.conftest import ADMIN, U1


def _granted(client, headers):
    """Visible miniapps that needed a grant (the always-visible LMS is listed for everyone)."""
    return [m for m in client.get("/me/miniapps", headers=headers).json()["miniapps"] if not m["always_visible"]]


def test_end_to_end_flow(client):
    assert _granted(client, U1) == []
    r = client.post("/admin/system-access", json={"username": "user1", "miniapp_id": "leave"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["already_granted"] is False
    ms = client.get("/me/miniapps", headers=U1).json()["miniapps"]
    assert [(m["id"], m["can_use"]) for m in ms] == [("leave", False), ("lms", False)]
    r = client.post("/miniapps/leave/use", headers=U1)
    assert r.status_code == 403 and r.json()["code"] == "NOT_MEMBER"
    assert client.post("/admin/miniapps/leave/members", json={"username": "user1"}, headers=ADMIN).status_code == 200
    assert client.post("/miniapps/leave/use", headers=U1).status_code == 200
    assert client.get("/admin/check", params={"username": "user1", "miniapp_id": "leave"}, headers=ADMIN).json() == {"username": "user1", "miniapp_id": "leave", "visible": True, "can_use": True, "role": ""}
    assert client.post("/admin/reset", headers=ADMIN).json() == {"reset": True}
    assert _granted(client, U1) == []


@pytest.mark.parametrize("headers", [{}, {"X-API-Key": "wrong"}])
def test_bad_key_401_json(client, headers):
    r = client.get("/me", headers=headers)
    assert r.status_code == 401 and r.json()["code"] == "UNAUTHORIZED"


def test_user_cannot_call_admin(client):
    r = client.post("/admin/reset", headers=U1)
    assert r.status_code == 403 and r.json()["code"] == "ADMIN_REQUIRED"


def test_membership_before_system_409(client):
    r = client.post("/admin/miniapps/leave/members", json={"username": "user1"}, headers=ADMIN)
    assert r.status_code == 409 and r.json()["code"] == "SYSTEM_ACCESS_REQUIRED"


def test_unknown_ids_404(client):
    r = client.post("/admin/system-access", json={"username": "ghost", "miniapp_id": "leave"}, headers=ADMIN)
    assert r.status_code == 404 and r.json()["code"] == "USER_NOT_FOUND"
    r = client.delete("/admin/miniapps/ghost/members/user1", headers=ADMIN)
    assert r.status_code == 404 and r.json()["code"] == "MINIAPP_NOT_FOUND"


def test_validation_error_shape(client):
    r = client.post("/admin/system-access", json={"username": "user1"}, headers=ADMIN)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR" and isinstance(r.json()["detail"], str)


def test_revoke_endpoints(client):
    client.post("/admin/system-access", json={"username": "user1", "miniapp_id": "leave"}, headers=ADMIN)
    client.post("/admin/miniapps/leave/members", json={"username": "user1"}, headers=ADMIN)
    assert client.delete("/admin/miniapps/leave/members/user1", headers=ADMIN).json()["revoked"] is True
    assert client.delete("/admin/system-access/user1/leave", headers=ADMIN).json()["revoked"] is True
    assert _granted(client, U1) == []


def test_public_pages(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and 'id="app"' in r.text
    s = client.get("/status")
    assert s.status_code == 200 and "user1" in s.text
    assert client.get("/static/console.html").status_code == 200
    assert len(client.get("/admin/users", headers=ADMIN).json()["users"]) == 4


def test_unknown_route_is_json(client):
    r = client.get("/nope")
    assert r.status_code == 404 and r.json()["code"] == "NOT_FOUND"


def test_unhandled_error_is_json(client, monkeypatch):
    from fastapi.testclient import TestClient

    import app as app_module
    from permapp import service

    def boom(engine):
        raise RuntimeError("db down")

    monkeypatch.setattr(service, "list_miniapps", boom)
    with TestClient(app_module.app, raise_server_exceptions=False) as c:
        r = c.get("/admin/miniapps", headers=ADMIN)
    assert r.status_code == 500 and r.json()["code"] == "INTERNAL_ERROR"


def test_find_user_by_email(client):
    client.post("/admin/system-access", json={"username": "user1", "miniapp_id": "leave"}, headers=ADMIN)
    r = client.get("/admin/users/by-email", params={"email": "  USER1@Demo.Local "}, headers=ADMIN)
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "user1" and body["email"] == "user1@demo.local"
    assert body["system_access"] == ["leave"] and body["memberships"] == []


def test_find_user_by_email_unknown_is_404(client):
    r = client.get("/admin/users/by-email", params={"email": "nobody@demo.local"}, headers=ADMIN)
    assert r.status_code == 404 and r.json()["code"] == "USER_NOT_FOUND"


def test_find_user_by_email_blank_is_422(client):
    r = client.get("/admin/users/by-email", params={"email": "   "}, headers=ADMIN)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR"
    assert client.get("/admin/users/by-email", headers=ADMIN).status_code == 422


def test_find_user_by_email_needs_admin(client):
    r = client.get("/admin/users/by-email", params={"email": "user1@demo.local"}, headers=U1)
    assert r.status_code == 403 and r.json()["code"] == "ADMIN_REQUIRED"


def test_users_and_me_include_email(client):
    users = {u["username"]: u["email"] for u in client.get("/admin/users", headers=ADMIN).json()["users"]}
    assert users == {"admin": "admin@demo.local", "user1": "user1@demo.local", "user2": "user2@demo.local",
                     "user3": "user3@demo.local"}
    assert client.get("/me", headers=U1).json()["email"] == "user1@demo.local"


def test_lms_member_with_role_via_api(client):
    r = client.post("/admin/miniapps/lms/members", json={"username": "user1", "role": "instructor"}, headers=ADMIN)
    assert r.status_code == 200 and r.json() == {"username": "user1", "miniapp_id": "lms", "role": "instructor", "already_granted": False}
    lms = next(m for m in client.get("/me/miniapps", headers=U1).json()["miniapps"] if m["id"] == "lms")
    assert lms["can_use"] is True and lms["role"] == "instructor" and lms["roles"] == ["learner", "instructor"]
    r = client.post("/admin/miniapps/lms/members", json={"username": "user1", "role": "boss"}, headers=ADMIN)
    assert r.status_code == 422 and r.json()["code"] == "INVALID_ROLE"
    assert "Giảng viên" in client.get("/status").text


def test_cors_only_on_swagger(client):
    origin = {"Origin": "https://make.powerapps.com"}
    assert client.get("/swagger.json", headers=origin).headers.get("access-control-allow-origin") == "*"
    assert "access-control-allow-origin" not in client.get("/admin/users", headers={**ADMIN, **origin}).headers
    assert "access-control-allow-origin" not in client.get("/health", headers=origin).headers


# ---------- eligibility ----------

def _elig(client, **params):
    r = client.get("/admin/eligibility", params=params, headers=ADMIN)
    assert r.status_code == 200
    return r.json()


def test_check_eligibility_endpoint(client):
    assert _elig(client, username="user1", miniapp_id="lms", role="instructor")["eligible"] is True
    body = _elig(client, username="user2", miniapp_id="lms", role="instructor")
    assert body == {
        "username": "user2", "miniapp_id": "lms", "role": "instructor", "eligible": False,
        "reasons": ["Vai trò instructor của LMS chỉ dành cho Phòng Đào tạo (L&D) hoặc chức danh chứa 'giảng viên'"],
        "status": "ACTIVE", "department": "Phòng Kinh doanh", "title": "Nhân viên kinh doanh",
        "manager_email": "truongphong.kinhdoanh@demo.local", "approver_checked": False, "approver_ok": False,
    }
    assert _elig(client, username="user2", miniapp_id="lms", role="learner")["eligible"] is True
    assert _elig(client, username="user3", miniapp_id="leave")["eligible"] is False


def test_check_eligibility_empty_strings_from_copilot(client):
    """Copilot Studio sends "" for optional inputs it did not fill."""
    body = _elig(client, username="user1", miniapp_id="leave", role="", approver_email="")
    assert body["eligible"] is True and body["approver_checked"] is False


def test_check_eligibility_approver(client):
    ok = _elig(client, username="user1", miniapp_id="leave", approver_email="truongphong.daotao@demo.local")
    assert (ok["approver_checked"], ok["approver_ok"]) == (True, True)
    bad = _elig(client, username="user1", miniapp_id="leave", approver_email="ai.do@demo.local")
    assert (bad["approver_checked"], bad["approver_ok"]) == (True, False)


def test_check_eligibility_always_200_even_when_params_missing(client):
    body = _elig(client)
    assert body["eligible"] is False and body["reasons"]
    assert _elig(client, username="ghost", miniapp_id="nope")["eligible"] is False


def test_check_eligibility_needs_admin(client):
    r = client.get("/admin/eligibility", params={"username": "user1", "miniapp_id": "leave"}, headers=U1)
    assert r.status_code == 403 and r.json()["code"] == "ADMIN_REQUIRED"


def test_add_member_not_eligible_is_403_and_writes_nothing(client):
    r = client.post("/admin/miniapps/lms/members", json={"username": "user2", "role": "instructor"}, headers=ADMIN)
    assert r.status_code == 403 and r.json()["code"] == "NOT_ELIGIBLE"
    assert r.json()["detail"].startswith("Vai trò instructor của LMS chỉ dành cho")
    user2 = client.get("/admin/users/by-email", params={"email": "user2@demo.local"}, headers=ADMIN).json()
    assert user2["memberships"] == [] and user2["system_access"] == []


def test_grant_system_access_resigned_is_403(client):
    r = client.post("/admin/system-access", json={"username": "user3", "miniapp_id": "leave"}, headers=ADMIN)
    assert r.status_code == 403 and r.json()["code"] == "NOT_ELIGIBLE"
    assert r.json()["detail"].startswith("Nhân viên đã nghỉ việc")
    assert client.get("/admin/check", params={"username": "user3", "miniapp_id": "leave"}, headers=ADMIN).json()["visible"] is False


def test_user_fields_include_org_data(client):
    me = client.get("/me", headers=U1).json()
    assert (me["department"], me["title"], me["manager_email"], me["status"]) == (
        "Phòng Đào tạo (L&D)", "Chuyên viên đào tạo", "truongphong.daotao@demo.local", "ACTIVE")
    user3 = client.get("/admin/users/by-email", params={"email": "user3@demo.local"}, headers=ADMIN).json()
    assert user3["status"] == "RESIGNED"
    admin = next(u for u in client.get("/admin/users", headers=ADMIN).json()["users"] if u["username"] == "admin")
    assert admin["manager_email"] == ""  # never null
    assert client.get("/me", headers={"X-API-Key": "user3-key-123"}).json()["username"] == "user3"
    assert "Đã nghỉ việc" in client.get("/status").text and "Phòng Kinh doanh" in client.get("/status").text
