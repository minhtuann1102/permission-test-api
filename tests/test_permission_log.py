"""Permission change log: one row per real change, with who made it (console or agent)."""
from tests.conftest import ADMIN, U1

CONSOLE = {**ADMIN, "X-Client": "console"}


def _log(client, **params):
    r = client.get("/admin/permission-log", params=params, headers=ADMIN)
    assert r.status_code == 200, r.json()
    return r.json()["entries"]


def _rows(client):
    return [(e["action"], e["from_level"], e["to_level"], e["actor"]) for e in _log(client)]


def _sys(client, user, app, headers=ADMIN):
    return client.post("/admin/system-access", json={"username": user, "miniapp_id": app}, headers=headers)


def _member(client, user, app, role="", headers=ADMIN):
    return client.post(f"/admin/miniapps/{app}/members", json={"username": user, "role": role}, headers=headers)


def test_grant_via_existing_endpoints_logs_agent(client):
    assert _sys(client, "user2", "inventory").status_code == 200
    assert _member(client, "user2", "inventory").status_code == 200
    assert _rows(client) == [("Grant", "see", "use", "agent"), ("Grant", "none", "see", "agent")]
    e = _log(client)[0]
    assert e["username"] == "user2" and e["miniapp_id"] == "inventory" and e["detail"] and e["at"]


def test_console_header_sets_actor(client):
    _sys(client, "user2", "inventory", headers=CONSOLE)
    assert _rows(client) == [("Grant", "none", "see", "console")]


def test_no_row_on_noop(client):
    _sys(client, "user2", "inventory")
    _sys(client, "user2", "inventory")
    assert len(_log(client)) == 1
    client.delete("/admin/miniapps/leave/members/user2", headers=ADMIN)
    client.delete("/admin/system-access/user2/leave", headers=ADMIN)
    assert len(_log(client)) == 1


def test_role_change_and_revokes(client):
    _member(client, "user1", "lms", "learner")
    _member(client, "user1", "lms", "instructor")
    client.delete("/admin/miniapps/lms/members/user1", headers=ADMIN)
    _sys(client, "user1", "leave")
    _member(client, "user1", "leave")
    client.delete("/admin/system-access/user1/leave", headers=ADMIN)
    assert _rows(client) == [
        ("RevokeAll", "use", "none", "agent"),
        ("Grant", "see", "use", "agent"),
        ("Grant", "none", "see", "agent"),
        ("RevokeUse", "instructor", "see", "agent"),
        ("ChangeRole", "learner", "instructor", "agent"),
        ("Grant", "see", "learner", "agent"),
    ]


def test_refusal_writes_no_row(client):
    r = _member(client, "user2", "lms", "instructor")
    assert r.status_code == 403 and r.json()["code"] == "NOT_ELIGIBLE"
    assert _log(client) == []


def test_log_filter_and_admin_only(client):
    _sys(client, "user1", "leave")
    _sys(client, "user2", "leave")
    assert [e["username"] for e in _log(client, username="user1")] == ["user1"]
    r = client.get("/admin/permission-log", headers=U1)
    assert r.status_code == 403 and r.json()["code"] == "ADMIN_REQUIRED"


def test_reset_clears_permission_log(client):
    _sys(client, "user1", "leave")
    client.post("/admin/reset", headers=ADMIN)
    assert _log(client) == []


# ---------- multi-grant (console) ----------

def _grants(client, user, items, headers=ADMIN):
    return client.post(f"/admin/users/{user}/grants",
                       json={"grants": [{"miniapp_id": m, "level": lv} for m, lv in items]}, headers=headers)


def _results(r):
    assert r.status_code == 200, r.json()
    return r.json()["results"]


def test_grants_use_is_one_row(client):
    [res] = _results(_grants(client, "user2", [("expense", "use")]))
    assert res["ok"] and res["changed"] and (res["from_level"], res["to_level"]) == ("none", "use")
    assert _rows(client) == [("Grant", "none", "use", "agent")]
    check = client.get("/admin/check", params={"username": "user2", "miniapp_id": "expense"}, headers=ADMIN).json()
    assert check["can_use"] is True


def test_grants_partial_success(client):
    res = _results(_grants(client, "user2", [("expense", "use"), ("lms", "instructor"), ("inventory", "see")]))
    assert [r["ok"] for r in res] == [True, False, True]
    assert res[1]["code"] == "NOT_ELIGIBLE" and res[1]["detail"]
    assert [r["miniapp_id"] for r in res] == ["expense", "lms", "inventory"]
    assert [e["miniapp_id"] for e in _log(client)] == ["inventory", "expense"]


def test_grants_never_downgrade(client):
    _results(_grants(client, "user1", [("leave", "use")]))
    [res] = _results(_grants(client, "user1", [("leave", "see")]))
    assert res["ok"] is True and res["changed"] is False and res["to_level"] == "use"
    assert len(_log(client)) == 1


def test_grants_lms_role_both_ways(client):
    _results(_grants(client, "user1", [("lms", "instructor")]))
    [res] = _results(_grants(client, "user1", [("lms", "learner")]))
    assert (res["from_level"], res["to_level"]) == ("instructor", "learner")
    assert _rows(client)[0] == ("ChangeRole", "instructor", "learner", "agent")


def test_grants_invalid_level_and_unknown_user(client):
    [res] = _results(_grants(client, "user1", [("leave", "learner")]))
    assert res["ok"] is False and res["code"] == "INVALID_LEVEL"
    [res] = _results(_grants(client, "user1", [("lms", "see")]))
    assert res["code"] == "INVALID_LEVEL"
    r = _grants(client, "ghost", [("leave", "use")])
    assert r.status_code == 404 and r.json()["code"] == "USER_NOT_FOUND"


def test_grants_console_actor(client):
    _results(_grants(client, "user1", [("leave", "see")], headers=CONSOLE))
    assert _rows(client) == [("Grant", "none", "see", "console")]
