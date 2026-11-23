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


# ---------- eligibility ----------

from permapp.service import check_eligibility  # noqa: E402


def test_eligibility_user1_lms_instructor_by_department(engine):
    r = check_eligibility(engine, "user1", "lms", "instructor")
    assert r["eligible"] is True and r["reasons"][0] == "Thuộc Phòng Đào tạo (L&D)"
    assert (r["status"], r["department"], r["title"]) == ("ACTIVE", "Phòng Đào tạo (L&D)", "Chuyên viên đào tạo")


def test_eligibility_user2_lms_instructor_is_refused(engine):
    r = check_eligibility(engine, "user2", "lms", "instructor")
    assert r["eligible"] is False
    assert r["reasons"] == ["Vai trò instructor của LMS chỉ dành cho Phòng Đào tạo (L&D) hoặc chức danh chứa 'giảng viên'"]


def test_eligibility_user2_lms_learner_and_blank_role(engine):
    assert check_eligibility(engine, "user2", "lms", "learner")["eligible"] is True
    blank = check_eligibility(engine, "user2", "lms", "")
    assert blank["eligible"] is True and blank["role"] == "learner"


def test_eligibility_by_title_keyword_case_insensitive(engine):
    from sqlalchemy import update

    from permapp.db import users
    with engine.begin() as c:
        c.execute(update(users).where(users.c.username == "user2").values(title="GIẢNG VIÊN nội bộ"))
    r = check_eligibility(engine, "user2", "lms", "instructor")
    assert r["eligible"] is True and r["reasons"][0] == "Chức danh 'GIẢNG VIÊN nội bộ' chứa 'giảng viên'"


@pytest.mark.parametrize("app,role", [("leave", ""), ("expense", ""), ("inventory", ""), ("lms", "learner"), ("lms", "instructor")])
def test_eligibility_resigned_user3_never_eligible(engine, app, role):
    r = check_eligibility(engine, "user3", app, role)
    assert r["eligible"] is False and r["status"] == "RESIGNED"
    assert r["reasons"][0].startswith("Nhân viên đã nghỉ việc")


def test_eligibility_open_miniapp_states_its_basis(engine):
    r = check_eligibility(engine, "user1", "leave")
    assert r["eligible"] is True and r["role"] == ""
    assert r["reasons"] == ["Miniapp Nghỉ phép không giới hạn đơn vị hay chức danh", "Nhân viên đang làm việc"]


@pytest.mark.parametrize("approver,checked,ok", [
    ("truongphong.daotao@demo.local", True, True),
    ("  TruongPhong.DaoTao@Demo.Local ", True, True),
    ("ai.do@demo.local", True, False),
    ("", False, False),
    (None, False, False),
])
def test_eligibility_approver(engine, approver, checked, ok):
    r = check_eligibility(engine, "user1", "leave", "", approver)
    assert (r["approver_checked"], r["approver_ok"]) == (checked, ok)
    assert r["manager_email"] == "truongphong.daotao@demo.local"


def test_eligibility_admin_without_manager_never_matches_approver(engine):
    r = check_eligibility(engine, "admin", "leave", "", "someone@demo.local")
    assert r["manager_email"] == "" and (r["approver_checked"], r["approver_ok"]) == (True, False)


def test_eligibility_unknown_ids_and_bad_role_are_results_not_errors(engine):
    r = check_eligibility(engine, "ghost", "lms", "instructor", "x@y.z")
    assert r["eligible"] is False and r["reasons"] == ["Không tìm thấy người dùng 'ghost'"]
    assert r["approver_ok"] is False and r["status"] == ""
    assert check_eligibility(engine, "user1", "ghost")["reasons"] == ["Không tìm thấy miniapp 'ghost'"]
    bad = check_eligibility(engine, "user1", "lms", "boss")
    assert bad["eligible"] is False and "boss" in bad["reasons"][0]


def _grants(engine):
    from sqlalchemy import select

    from permapp.db import miniapp_grants, system_grants
    with engine.connect() as c:
        return (c.execute(select(system_grants)).all(), c.execute(select(miniapp_grants)).all())


def test_add_member_not_eligible_403_writes_nothing(engine):
    with pytest.raises(ServiceError) as e:
        grant_membership(engine, "lms", "user2", "instructor")
    assert (e.value.status, e.value.code) == (403, "NOT_ELIGIBLE")
    assert e.value.detail == check_eligibility(engine, "user2", "lms", "instructor")["reasons"][0]
    assert _grants(engine) == ([], [])


def test_role_change_to_instructor_is_blocked_and_keeps_old_role(engine):
    grant_membership(engine, "lms", "user2", "learner")
    with pytest.raises(ServiceError) as e:
        grant_membership(engine, "lms", "user2", "instructor")
    assert e.value.code == "NOT_ELIGIBLE"
    assert check_access(engine, "user2", "lms")["role"] == "learner"


def test_resigned_user3_cannot_be_granted_anything(engine):
    for fn, args in [(grant_system_access, ("user3", "leave")), (grant_system_access, ("user3", "lms")),
                     (grant_membership, ("lms", "user3", "learner")), (grant_membership, ("leave", "user3"))]:
        with pytest.raises(ServiceError) as e:
            fn(engine, *args)
        assert (e.value.status, e.value.code) == (403, "NOT_ELIGIBLE")
    assert _grants(engine) == ([], [])


def test_revoke_still_works_for_resigned_user3(engine):
    from permapp.db import miniapp_grants, system_grants
    with engine.begin() as c:  # granted before the user resigned
        c.execute(system_grants.insert().values(username="user3", miniapp_id="leave"))
        c.execute(miniapp_grants.insert().values(username="user3", miniapp_id="leave", role=""))
        c.execute(miniapp_grants.insert().values(username="user3", miniapp_id="lms", role="learner"))
    assert revoke_membership(engine, "leave", "user3")["revoked"] is True
    assert revoke_system_access(engine, "user3", "leave")["revoked"] is True
    assert revoke_system_access(engine, "user3", "lms")["revoked"] is True
    assert _grants(engine) == ([], [])
