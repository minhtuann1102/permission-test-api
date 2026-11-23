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
    assert check_access(engine, "user1", "leave") == {"username": "user1", "miniapp_id": "leave", "visible": False, "can_use": False}
    assert list_visible_miniapps(engine, "user1") == []
    assert grant_system_access(engine, "user1", "leave")["already_granted"] is False
    assert [m["id"] for m in list_visible_miniapps(engine, "user1")] == ["leave"]
    assert check_access(engine, "user1", "leave")["can_use"] is False
    with pytest.raises(ServiceError) as e:
        use_miniapp(engine, "user1", "leave")
    assert (e.value.status, e.value.code) == (403, "NOT_MEMBER")
    grant_membership(engine, "leave", "user1")
    assert check_access(engine, "user1", "leave") == {"username": "user1", "miniapp_id": "leave", "visible": True, "can_use": True}
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
    assert len(list_visible_miniapps(engine, "admin")) == 3
    assert use_miniapp(engine, "admin", "inventory")["used_by"] == "admin"


def test_get_user_by_key(engine):
    assert get_user_by_key(engine, "user1-key-123")["username"] == "user1"
    assert get_user_by_key(engine, "nope") is None
