import pytest

from tests.conftest import ADMIN, U1


def test_end_to_end_flow(client):
    assert client.get("/me/miniapps", headers=U1).json()["miniapps"] == []
    r = client.post("/admin/system-access", json={"username": "user1", "miniapp_id": "leave"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["already_granted"] is False
    ms = client.get("/me/miniapps", headers=U1).json()["miniapps"]
    assert [(m["id"], m["can_use"]) for m in ms] == [("leave", False)]
    r = client.post("/miniapps/leave/use", headers=U1)
    assert r.status_code == 403 and r.json()["code"] == "NOT_MEMBER"
    assert client.post("/admin/miniapps/leave/members", json={"username": "user1"}, headers=ADMIN).status_code == 200
    assert client.post("/miniapps/leave/use", headers=U1).status_code == 200
    assert client.get("/admin/check", params={"username": "user1", "miniapp_id": "leave"}, headers=ADMIN).json() == {"username": "user1", "miniapp_id": "leave", "visible": True, "can_use": True}
    assert client.post("/admin/reset", headers=ADMIN).json() == {"reset": True}
    assert client.get("/me/miniapps", headers=U1).json()["miniapps"] == []


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
    assert client.get("/me/miniapps", headers=U1).json()["miniapps"] == []


def test_public_pages(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/")
    assert r.status_code == 200 and "user1" in r.text
    assert len(client.get("/admin/users", headers=ADMIN).json()["users"]) == 3


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
