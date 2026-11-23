import pytest

from permapp.service import (
    ServiceError,
    check_access,
    get_user_by_key,
    grant_membership,
    grant_system_access,
    list_users_with_grants,
    list_visible_miniapps,
    revoke_membership,
    revoke_system_access,
    use_miniapp,
)


def test_full_two_tier_flow(engine):
    assert check_access(engine, "user1", "leave") == {"username": "user1", "miniapp_id": "leave", "visible": False, "can_use": False, "role": ""}
    assert [m["id"] for m in list_visible_miniapps(engine, "user1")] == ["lms"]  # always visible
    assert grant_system_access(engine, "user1", "leave")["already_granted"] is False
    assert [m["id"] for m in list_visible_miniapps(engine, "user1")] == ["leave", "lms"]
    assert check_access(engine, "user1", "leave")["can_use"] is False
    with pytest.raises(ServiceError) as e:
        use_miniapp(engine, "user1", "leave")
    assert (e.value.status, e.value.code) == (403, "NOT_MEMBER")
    grant_membership(engine, "leave", "user1")
    assert check_access(engine, "user1", "leave") == {"username": "user1", "miniapp_id": "leave", "visible": True, "can_use": True, "role": ""}
    assert use_miniapp(engine, "user1", "leave")["used_by"] == "user1"
    assert check_access(engine, "user2", "leave")["visible"] is False  # isolation


def test_membership_requires_system_access(engine):
    with pytest.raises(ServiceError) as e:
        grant_membership(engine, "leave", "user1")
    assert (e.value.status, e.value.code) == (409, "SYSTEM_ACCESS_REQUIRED")


def test_use_not_visible(engine):
    with pytest.raises(ServiceError) as e:
        use_miniapp(engine, "user1", "leave")
    assert e.value.code == "NOT_VISIBLE"


def test_revoke_system_cascades(engine):
    grant_system_access(engine, "user1", "leave")
    grant_membership(engine, "leave", "user1")
    assert revoke_system_access(engine, "user1", "leave")["revoked"] is True
    assert check_access(engine, "user1", "leave")["can_use"] is False
    assert list_users_with_grants(engine)[1]["memberships"] == []  # user1 is index 1 after admin


def test_idempotent_grant_and_revoke(engine):
    grant_system_access(engine, "user1", "leave")
    assert grant_system_access(engine, "user1", "leave")["already_granted"] is True
    grant_membership(engine, "leave", "user1")
    assert grant_membership(engine, "leave", "user1")["already_granted"] is True
    revoke_membership(engine, "leave", "user1")
    assert revoke_membership(engine, "leave", "user1")["revoked"] is False


@pytest.mark.parametrize("fn,args,code", [
    (grant_system_access, ("ghost", "leave"), "USER_NOT_FOUND"),
    (grant_system_access, ("user1", "ghost"), "MINIAPP_NOT_FOUND"),
    (grant_membership, ("ghost", "user1"), "MINIAPP_NOT_FOUND"),
    (check_access, ("ghost", "leave"), "USER_NOT_FOUND"),
])
def test_unknown_ids_404(engine, fn, args, code):
    with pytest.raises(ServiceError) as e:
        fn(engine, *args)
    assert (e.value.status, e.value.code) == (404, code)


def test_admin_sees_and_uses_all(engine):
    assert len(list_visible_miniapps(engine, "admin")) == 4
    assert use_miniapp(engine, "admin", "inventory")["used_by"] == "admin"


def test_get_user_by_key(engine):
    assert get_user_by_key(engine, "user1-key-123")["username"] == "user1"
    assert get_user_by_key(engine, "nope") is None


# ---------- mock LMS: always visible, member roles ----------

def test_lms_is_always_visible_and_needs_no_system_access(engine):
    assert check_access(engine, "user1", "lms") == {"username": "user1", "miniapp_id": "lms", "visible": True, "can_use": False, "role": ""}
    assert grant_system_access(engine, "user1", "lms")["already_granted"] is True  # nothing to grant
    r = grant_membership(engine, "lms", "user1")  # no system access row needed, blank role = learner
    assert (r["role"], r["already_granted"]) == ("learner", False)
    assert check_access(engine, "user1", "lms") == {"username": "user1", "miniapp_id": "lms", "visible": True, "can_use": True, "role": "learner"}
    assert use_miniapp(engine, "user1", "lms")["used_by"] == "user1"


def test_lms_role_change_and_same_role_is_idempotent(engine):
    grant_membership(engine, "lms", "user1", "learner")
    assert grant_membership(engine, "lms", "user1", "learner")["already_granted"] is True
    r = grant_membership(engine, "lms", "user1", " Instructor ")
    assert (r["role"], r["already_granted"]) == ("instructor", False)
    assert check_access(engine, "user1", "lms")["role"] == "instructor"
    user1 = next(u for u in list_users_with_grants(engine) if u["username"] == "user1")
    assert user1["memberships"] == ["lms"] and user1["member_roles"] == [{"miniapp_id": "lms", "role": "instructor"}]


@pytest.mark.parametrize("app,role", [("lms", "teacher"), ("leave", "learner")])
def test_invalid_role_422(engine, app, role):
    grant_system_access(engine, "user1", "leave")
    with pytest.raises(ServiceError) as e:
        grant_membership(engine, app, "user1", role)
    assert (e.value.status, e.value.code) == (422, "INVALID_ROLE")


def test_revoke_all_on_lms_removes_membership(engine):
    grant_membership(engine, "lms", "user1", "instructor")
    assert revoke_system_access(engine, "user1", "lms")["revoked"] is True
    assert check_access(engine, "user1", "lms")["can_use"] is False
    assert revoke_system_access(engine, "user1", "lms")["revoked"] is False
