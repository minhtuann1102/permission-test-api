"""Hand-written OpenAPI 2.0 (Swagger) spec for Power Platform / Copilot Studio import.

Rules: swagger 2.0, https only, host without scheme, no oneOf/anyOf/nullable,
every operation has a unique alphanumeric operationId and an X-API-Key header.
"""
import copy


def _ref(name):
    return {"$ref": f"#/definitions/{name}"}


def _str(desc):
    return {"type": "string", "description": desc}


def _bool(desc):
    return {"type": "boolean", "description": desc}


def _int(desc):
    return {"type": "integer", "format": "int32", "description": desc}


def _arr(item, desc):
    return {"type": "array", "items": item, "description": desc}


RESULT_DESC = ("DONE (the change was made) or NO_CHANGE (it was already so, nothing written). "
               "Rule violations are 4xx errors instead, never a result value.")
MESSAGE_DESC = "One Vietnamese sentence describing what happened. Can be shown to the technician as is."


DEFINITIONS = {
    "Error": {
        "type": "object",
        "required": ["detail", "code"],
        "properties": {
            "detail": _str("Human-readable error message (Vietnamese)."),
            "code": _str(
                "Machine-readable error code: UNAUTHORIZED, ADMIN_REQUIRED, NOT_VISIBLE, NOT_MEMBER, "
                "USER_NOT_FOUND, MINIAPP_NOT_FOUND, SYSTEM_ACCESS_REQUIRED, NOT_ELIGIBLE, INVALID_ROLE, "
                "VALIDATION_ERROR, NOT_FOUND. Đánh giá (reviews): TICKET_REQUIRED, INVALID_DATE, "
                "INVALID_KIND, INVALID_DEADLINE, DEADLINE_REQUIRED, EXTENSION_TOO_LONG, PERIOD_NOT_FOUND, "
                "PERIOD_EXISTS, PERIOD_ALREADY_OPEN, PERIOD_OPEN, PERIOD_CLOSED, PERIOD_LOCKED, FORM_NOT_FOUND, "
                "FORM_APPROVED, FORM_LOCKED, EMPLOYEE_RESIGNED, GOAL_NOT_FOUND, EVALUATOR_NOT_FOUND, "
                "EVALUATOR_DUPLICATE, EVALUATOR_RESIGNED, OLD_EVALUATOR_REQUIRED, SELF_EVALUATOR, INVALID_ROWS."
            ),
        },
    },
    "Health": {"type": "object", "properties": {"status": _str("Always 'ok'.")}},
    "User": {
        "type": "object",
        "properties": {
            "username": _str("Username, e.g. 'user1'."),
            "role": _str("'admin' or 'user'."),
            "display_name": _str("Display name."),
            "email": _str("Email used as the (mock) identity, e.g. 'user1@demo.local'."),
            "department": _str("Department (đơn vị), e.g. 'Phòng Đào tạo (L&D)'. Empty if unknown."),
            "title": _str("Job title (chức danh), e.g. 'Chuyên viên đào tạo'. Empty if unknown."),
            "manager_email": _str("Email of the direct manager. Empty if none."),
            "status": _str("Employment status: 'ACTIVE' or 'RESIGNED'. RESIGNED users cannot be granted anything."),
        },
    },
    "Miniapp": {
        "type": "object",
        "properties": {
            "id": _str("Miniapp id, e.g. 'leave', 'expense', 'inventory', 'lms'."),
            "name": _str("Miniapp display name."),
            "description": _str("What the miniapp does."),
            "always_visible": _bool("True if every user sees this miniapp without system access (e.g. 'lms')."),
            "roles": {"type": "array", "items": {"type": "string"},
                      "description": "Member roles of this miniapp, lowest first (lms: learner, instructor). "
                                     "Empty if the miniapp has no roles."},
        },
    },
    "VisibleMiniapp": {
        "type": "object",
        "properties": {
            "id": _str("Miniapp id."),
            "name": _str("Miniapp display name."),
            "description": _str("What the miniapp does."),
            "always_visible": _bool("True if every user sees this miniapp without system access."),
            "roles": {"type": "array", "items": {"type": "string"}, "description": "Member roles of this miniapp."},
            "can_use": _bool("True if the caller is a member of this miniapp (tier 2) and can use it."),
            "role": _str("The caller's member role, e.g. 'learner' or 'instructor'. Empty if none."),
        },
    },
    "MyMiniapps": {
        "type": "object",
        "properties": {
            "username": _str("The caller's username."),
            "miniapps": {"type": "array", "items": _ref("VisibleMiniapp"),
                         "description": "Miniapps the caller can see (has system access to)."},
        },
    },
    "UserWithGrants": {
        "type": "object",
        "properties": {
            "username": _str("Username."),
            "role": _str("'admin' or 'user'."),
            "display_name": _str("Display name."),
            "email": _str("Email used as the (mock) identity, e.g. 'user1@demo.local'."),
            "department": _str("Department (đơn vị), e.g. 'Phòng Đào tạo (L&D)'. Empty if unknown."),
            "title": _str("Job title (chức danh), e.g. 'Chuyên viên đào tạo'. Empty if unknown."),
            "manager_email": _str("Email of the direct manager. Empty if none."),
            "status": _str("Employment status: 'ACTIVE' or 'RESIGNED'. RESIGNED users cannot be granted anything."),
            "system_access": {"type": "array", "items": {"type": "string"},
                              "description": "Miniapp ids this user has system access to (tier 1)."},
            "memberships": {"type": "array", "items": {"type": "string"},
                            "description": "Miniapp ids this user is a member of (tier 2)."},
            "member_roles": {"type": "array", "items": _ref("MemberRole"),
                             "description": "Member role per miniapp, only for miniapps with roles (lms)."},
        },
    },
    "MemberRole": {
        "type": "object",
        "properties": {
            "miniapp_id": _str("Miniapp id, e.g. 'lms'."),
            "role": _str("Member role, e.g. 'learner' or 'instructor'."),
        },
    },
    "UserList": {"type": "object", "properties": {"users": {"type": "array", "items": _ref("UserWithGrants")}}},
    "MiniappList": {"type": "object", "properties": {"miniapps": {"type": "array", "items": _ref("Miniapp")}}},
    "SystemAccessIn": {
        "type": "object",
        "required": ["username", "miniapp_id"],
        "properties": {
            "username": _str("Username to grant system access to, e.g. 'user1'."),
            "miniapp_id": _str("Miniapp id, e.g. 'leave'."),
        },
    },
    "MemberIn": {
        "type": "object",
        "required": ["username"],
        "properties": {
            "username": _str("Username to add as a member, e.g. 'user1'."),
            "role": _str("Member role, only for miniapps with roles. lms: 'learner' (Học viên, the default "
                         "when blank) or 'instructor' (Giảng viên). Leave blank for other miniapps."),
        },
    },
    "Grant": {
        "type": "object",
        "properties": {
            "username": _str("Username."),
            "miniapp_id": _str("Miniapp id."),
            "role": _str("Member role now held, e.g. 'instructor'. Empty for system access and role-less miniapps."),
            "already_granted": _bool("True if the permission already existed (nothing changed)."),
        },
    },
    "Revoke": {
        "type": "object",
        "properties": {
            "username": _str("Username."),
            "miniapp_id": _str("Miniapp id."),
            "revoked": _bool("True if a permission was removed; false if there was nothing to remove."),
        },
    },
    "Check": {
        "type": "object",
        "properties": {
            "username": _str("Username checked."),
            "miniapp_id": _str("Miniapp id checked."),
            "visible": _bool("True if the user can see the miniapp (has system access, tier 1)."),
            "can_use": _bool("True if the user can use the miniapp (is a member, tier 2)."),
            "role": _str("The user's member role, e.g. 'learner' or 'instructor'. Empty if none."),
        },
    },
    "UseResult": {
        "type": "object",
        "properties": {
            "miniapp_id": _str("Miniapp id."),
            "used_by": _str("Username that used the miniapp."),
            "message": _str("Confirmation message."),
        },
    },
    "Eligibility": {
        "type": "object",
        "properties": {
            "username": _str("Username checked."),
            "miniapp_id": _str("Miniapp id checked."),
            "role": _str("Role checked. For lms a blank role is checked as 'learner'. Empty for miniapps without roles."),
            "eligible": _bool("True if the user may be granted this miniapp/role. False: do not grant."),
            "reasons": {"type": "array", "items": {"type": "string"},
                        "description": "Vietnamese sentences: why not eligible, or the basis for eligibility. "
                                       "Show them as they are."},
            "status": _str("Employment status: 'ACTIVE' or 'RESIGNED'. Empty if the user is unknown."),
            "department": _str("The user's department. Empty if unknown."),
            "title": _str("The user's job title. Empty if unknown."),
            "manager_email": _str("Email of the user's direct manager. Empty if none."),
            "approver_checked": _bool("True if approver_email was given and compared."),
            "approver_ok": _bool("True if approver_email is the user's direct manager (manager_email)."),
        },
    },
    "Reset": {"type": "object", "properties": {"reset": _bool("Always true.")}},
    # ---------- Đánh giá (reviews) ----------
    "ReviewPeriod": {
        "type": "object",
        "properties": {
            "id": _str("Period id, e.g. 'VINFAST-Q4-2026', 'VINHOMES-T11-2026', 'VINFAST-360-2026'."),
            "name": _str("Display name, e.g. 'KPI quý 4/2026 - VinFast'."),
            "company": _str("Company / unit, e.g. 'VinFast'."),
            "kind": _str("KPI_MONTH, KPI_QUARTER, KPI_YEAR or REVIEW_360."),
            "kind_label": _str("Vietnamese label of kind."),
            "start_date": _str("Start date, YYYY-MM-DD."),
            "deadline": _str("Current deadline, YYYY-MM-DD."),
            "original_deadline": _str("Deadline before any extension (or the deadline set when reopened)."),
            "max_deadline": _str("Latest deadline an extension may set (original_deadline + 30 days)."),
            "status": _str("OPEN (đang mở), CLOSED (đã đóng, can be reopened) or LOCKED (đã chốt kết quả, final)."),
            "status_label": _str("Vietnamese label of status."),
            "extension_count": _int("How many times the deadline was extended."),
            "form_count": _int("Number of employee forms in this period."),
            "result_count": _int("Number of uploaded results (kết quả HQCV)."),
        },
    },
    "ReviewPeriodList": {"type": "object", "properties": {"periods": _arr(_ref("ReviewPeriod"), "Review periods.")}},
    "ReviewEvaluator": {
        "type": "object",
        "properties": {
            "email": _str("Evaluator email."),
            "relation": _str("manager, peer or subordinate."),
            "relation_label": _str("Vietnamese label of relation."),
        },
    },
    "ReviewGoal": {
        "type": "object",
        "properties": {
            "id": _str("Goal / criterion id, e.g. 'G-1001-3'."),
            "title": _str("Goal (mục tiêu) or criterion (tiêu chí) text."),
            "weight": _int("Weight in percent."),
            "target": _str("Target value, e.g. '12 khóa'."),
            "created_by": _str("employee (created by the employee) or manager."),
        },
    },
    "ReviewForm": {
        "type": "object",
        "properties": {
            "id": _str("Form id, e.g. 'RF-1001'."),
            "kind": _str("KPI, REVIEW_360, PROBATION (thử việc) or CONTRACT (hết hạn hợp đồng)."),
            "kind_label": _str("Vietnamese label of kind."),
            "period_id": _str("Period id. Empty for PROBATION and CONTRACT forms."),
            "period_name": _str("Period name. Empty if no period."),
            "period_status": _str("Status of the period (OPEN, CLOSED, LOCKED). Empty if no period."),
            "username": _str("Employee username."),
            "employee_name": _str("Employee display name."),
            "employee_email": _str("Employee email."),
            "employee_status": _str("ACTIVE or RESIGNED. Forms of RESIGNED employees cannot be changed."),
            "status": _str("DRAFT (đang nhập), SUBMITTED (đã nộp), APPROVED (đã phê duyệt) or LOCKED (đã chốt)."),
            "status_label": _str("Vietnamese label of status."),
            "deadline": _str("Deadline that applies to this form, YYYY-MM-DD."),
            "personal_deadline": _str("Personal deadline overriding the period's. Empty if none."),
            "max_deadline": _str("Latest deadline ExtendReviewForm may set."),
            "reopen_count": _int("How many times the form was reopened."),
            "extension_count": _int("How many times the form deadline was extended."),
            "evaluators": _arr(_ref("ReviewEvaluator"), "Evaluators (người đánh giá). 360 forms have several."),
            "goals": _arr(_ref("ReviewGoal"), "Goals / criteria on the form."),
            "total_weight": _int("Sum of goal weights in percent."),
            "weight_ok": _bool("True if total_weight is 100."),
        },
    },
    "ReviewFormList": {"type": "object", "properties": {"forms": _arr(_ref("ReviewForm"), "Matching forms.")}},
    "ReviewLogEntry": {
        "type": "object",
        "properties": {
            "id": _int("Entry id."),
            "at": _str("UTC timestamp."),
            "ticket": _str("SDP ticket, e.g. '#54'. Empty for changes made by hand on the operator screen."),
            "actor": _str("Who made the change: agent, or console (by hand on the operator screen)."),
            "action": _str("Operation, e.g. 'DeleteReviewGoal'."),
            "target": _str("Period, form or goal id."),
            "detail": _str("What changed (Vietnamese)."),
        },
    },
    "ReviewLog": {"type": "object", "properties": {"entries": _arr(_ref("ReviewLogEntry"), "Newest first, at most 200.")}},
    "ReviewPeriodIn": {
        "type": "object",
        "required": ["company", "kind", "year", "start_date", "deadline", "ticket"],
        "properties": {
            "company": _str("Company / unit, e.g. 'Vinhomes'. The period id is built from it."),
            "kind": _str("KPI_MONTH, KPI_QUARTER, KPI_YEAR or REVIEW_360."),
            "year": _int("Year, e.g. 2026."),
            "number": _int("Month 1-12 for KPI_MONTH, quarter 1-4 for KPI_QUARTER, 0 otherwise."),
            "start_date": _str("Start date YYYY-MM-DD."),
            "deadline": _str("Deadline YYYY-MM-DD, after start_date."),
            "ticket": _str("SDP ticket number, e.g. '#54'. Required."),
        },
    },
    "ReviewDeadlineIn": {
        "type": "object",
        "required": ["deadline", "ticket"],
        "properties": {
            "deadline": _str("New deadline YYYY-MM-DD."),
            "ticket": _str("SDP ticket number, e.g. '#54'. Required."),
        },
    },
    "ReviewFormReopenIn": {
        "type": "object",
        "required": ["ticket"],
        "properties": {
            "deadline": _str("Personal deadline YYYY-MM-DD. Required when the form's period is CLOSED; "
                             "otherwise leave empty."),
            "ticket": _str("SDP ticket number, e.g. '#54'. Required."),
        },
    },
    "ReviewEvaluatorIn": {
        "type": "object",
        "required": ["new_email", "ticket"],
        "properties": {
            "new_email": _str("Email of the new evaluator."),
            "old_email": _str("Email of the evaluator to replace. Required for forms with several evaluators "
                              "(360); may be empty when the form has one evaluator."),
            "ticket": _str("SDP ticket number, e.g. '#54'. Required."),
        },
    },
    "ReviewGoalIn": {
        "type": "object",
        "required": ["ticket"],
        "properties": {
            "title": _str("New text. Empty = unchanged."),
            "weight": _int("New weight 1-100. 0 = unchanged."),
            "target": _str("New target. Empty = unchanged."),
            "ticket": _str("SDP ticket number, e.g. '#54'. Required."),
        },
    },
    "ReviewResultRow": {
        "type": "object",
        "properties": {
            "email": _str("Employee email."),
            "score": _int("Score 0-100."),
            "grade": _str("Grade A, B, C or D."),
        },
    },
    "ReviewResultsIn": {
        "type": "object",
        "required": ["rows", "ticket"],
        "properties": {
            "rows": _arr(_ref("ReviewResultRow"), "One row per employee."),
            "ticket": _str("SDP ticket number, e.g. '#54'. Required."),
        },
    },
    "ReviewPeriodChange": {
        "type": "object",
        "properties": {"result": _str(RESULT_DESC), "message": _str(MESSAGE_DESC), "period": _ref("ReviewPeriod")},
    },
    "ReviewFormChange": {
        "type": "object",
        "properties": {"result": _str(RESULT_DESC), "message": _str(MESSAGE_DESC), "form": _ref("ReviewForm")},
    },
    "ReviewGoalChange": {
        "type": "object",
        "properties": {
            "result": _str(RESULT_DESC), "message": _str(MESSAGE_DESC),
            "goal": _ref("ReviewGoal"), "form": _ref("ReviewForm"),
        },
    },
    "ReviewResultsImport": {
        "type": "object",
        "properties": {
            "result": _str(RESULT_DESC), "message": _str(MESSAGE_DESC),
            "imported": _int("Rows imported."), "replaced": _int("Rows that overwrote an earlier result."),
            "period": _ref("ReviewPeriod"),
        },
    },
}

ADMIN_KEY_PARAM = {
    "name": "X-API-Key",
    "in": "header",
    "required": True,
    "type": "string",
    "description": "API key of the ADMIN account (admin key). Required for every /admin endpoint.",
}

ANY_KEY_PARAM = {
    "name": "X-API-Key",
    "in": "header",
    "required": True,
    "type": "string",
    "description": "API key of the user acting (e.g. user1's key to act as user1). The admin key also works.",
}


def _path(name, desc):
    return {"name": name, "in": "path", "required": True, "type": "string", "description": desc}


def _query(name, desc, required=True):
    return {"name": name, "in": "query", "required": required, "type": "string", "description": desc}


def _body(schema_name, desc):
    return {"name": "body", "in": "body", "required": True, "description": desc, "schema": _ref(schema_name)}


PERIOD_PATH = _path("period_id", "Review period id, e.g. 'VINFAST-Q4-2026'. Find it with ListReviewPeriods.")
FORM_PATH = _path("form_id", "Review form id, e.g. 'RF-1001'. Find it with FindReviewForms.")
GOAL_PATH = _path("goal_id", "Goal / criterion id, e.g. 'G-1001-3'. Read it from the form's goals.")
MINIAPP_PATH = _path("miniapp_id", "Miniapp id, e.g. 'leave', 'expense', 'inventory' or 'lms'.")
USERNAME_PATH = _path("username", "Username, e.g. 'user1'.")


def _err(desc):
    return {"description": desc, "schema": _ref("Error")}


def _op(op_id, summary, description, params, ok_schema, ok_desc, errors):
    responses = {"200": {"description": ok_desc, "schema": _ref(ok_schema)}}
    responses.update(errors)
    return {
        "operationId": op_id,
        "summary": summary,
        "description": description,
        "parameters": params,
        "responses": responses,
    }


E401 = {"401": _err("Missing or invalid X-API-Key.")}
E403_ADMIN = {"403": _err("The key is not the admin key (code ADMIN_REQUIRED).")}
E404 = {"404": _err("Unknown username (USER_NOT_FOUND) or miniapp id (MINIAPP_NOT_FOUND).")}
E422 = {"422": _err("Request body is missing a field (VALIDATION_ERROR).")}

ADMIN_ERRORS = {**E401, **E403_ADMIN}
# One 403 entry per operation (responses are keyed by status code), so both codes share it.
E403_GRANT = {"403": _err(
    "The key is not the admin key (ADMIN_REQUIRED), or the user is not eligible (NOT_ELIGIBLE: detail "
    "gives the reason, e.g. the user resigned or the role is limited to a department). Nothing was changed."
)}
GRANT_ERRORS = {**E401, **E403_GRANT}


TICKET_RULE = "Needs the SDP ticket number (TICKET_REQUIRED otherwise); every change is logged with it. "
E404_PERIOD = {"404": _err("Unknown period id (PERIOD_NOT_FOUND).")}
E404_FORM = {"404": _err("Unknown form id (FORM_NOT_FOUND), or old_email is not an evaluator (EVALUATOR_NOT_FOUND).")}
E422_REVIEW = {"422": _err("Bad input: TICKET_REQUIRED, INVALID_DATE, INVALID_DEADLINE (not after the current "
                           "deadline), EXTENSION_TOO_LONG, DEADLINE_REQUIRED or VALIDATION_ERROR. detail says what to fix.")}


def _review_paths():
    return {
        "/admin/reviews/periods": {
            "get": _op(
                "ListReviewPeriods", "List review periods (kỳ đánh giá)",
                "Admin only (admin key). Lists review periods with status, deadline and the latest allowed "
                "extension (max_deadline). Filter by company (e.g. 'VinFast') and status (OPEN, CLOSED, LOCKED). "
                "Use to find the period_id named in a ticket such as 'kỳ đánh giá quý 2.2026'.",
                [ADMIN_KEY_PARAM, _query("company", "Company, e.g. 'VinFast'. Empty = all.", required=False),
                 _query("status", "OPEN, CLOSED or LOCKED. Empty = all.", required=False)],
                "ReviewPeriodList", "Review periods.", ADMIN_ERRORS,
            ),
            "post": _op(
                "CreateReviewPeriod", "Create a review period",
                "Admin only (admin key). Creates an OPEN period; its id is built as COMPANY-Qn-YEAR, "
                "COMPANY-Tn-YEAR, COMPANY-Y-YEAR or COMPANY-360-YEAR. An existing id returns 409 PERIOD_EXISTS: "
                "extend or reopen it instead. " + TICKET_RULE,
                [ADMIN_KEY_PARAM, _body("ReviewPeriodIn", "The period to create.")],
                "ReviewPeriodChange", "Period created.",
                {**ADMIN_ERRORS, "409": _err("The period already exists (PERIOD_EXISTS)."),
                 "422": _err("Bad input: INVALID_KIND, INVALID_DATE, TICKET_REQUIRED or VALIDATION_ERROR.")},
            ),
        },
        "/admin/reviews/periods/{period_id}": {
            "get": _op(
                "GetReviewPeriod", "Get a review period",
                "Admin only (admin key). Returns one period with its status, deadlines and counts.",
                [ADMIN_KEY_PARAM, PERIOD_PATH], "ReviewPeriod", "The period.", {**ADMIN_ERRORS, **E404_PERIOD},
            )
        },
        "/admin/reviews/periods/{period_id}/reopen": {
            "post": _op(
                "ReopenReviewPeriod", "Reopen a closed review period for everyone",
                "Admin only (admin key). CLOSED -> OPEN with a new deadline after the old one, for every "
                "employee in the period. To reopen for ONE employee use ReopenReviewForm instead. "
                "LOCKED periods (results finalised) cannot be reopened (409 PERIOD_LOCKED); an OPEN period "
                "returns 409 PERIOD_ALREADY_OPEN (use ExtendReviewPeriod). " + TICKET_RULE,
                [ADMIN_KEY_PARAM, PERIOD_PATH, _body("ReviewDeadlineIn", "New deadline and ticket.")],
                "ReviewPeriodChange", "Period reopened.",
                {**ADMIN_ERRORS, **E404_PERIOD, **E422_REVIEW,
                 "409": _err("PERIOD_LOCKED or PERIOD_ALREADY_OPEN. Nothing was changed.")},
            )
        },
        "/admin/reviews/periods/{period_id}/extend": {
            "post": _op(
                "ExtendReviewPeriod", "Extend the deadline of an open review period",
                "Admin only (admin key). Moves the deadline of an OPEN period later, for every employee. "
                "The new deadline must be after the current one and at most 30 days after the original "
                "deadline (max_deadline), otherwise 422 EXTENSION_TOO_LONG. CLOSED periods return 409 "
                "PERIOD_CLOSED (use ReopenReviewPeriod), LOCKED ones 409 PERIOD_LOCKED. Same deadline = "
                "NO_CHANGE. " + TICKET_RULE,
                [ADMIN_KEY_PARAM, PERIOD_PATH, _body("ReviewDeadlineIn", "New deadline and ticket.")],
                "ReviewPeriodChange", "Deadline extended, or NO_CHANGE.",
                {**ADMIN_ERRORS, **E404_PERIOD, **E422_REVIEW,
                 "409": _err("PERIOD_CLOSED or PERIOD_LOCKED. Nothing was changed.")},
            )
        },
        "/admin/reviews/periods/{period_id}/results": {
            "post": _op(
                "ImportReviewResults", "Upload work performance results (kết quả HQCV)",
                "Admin only (admin key). Uploads score (0-100) and grade (A-D) per employee email into a CLOSED "
                "period; an employee who already has a result is overwritten. All or nothing: one bad row "
                "rejects the whole upload with 422 INVALID_ROWS listing every bad row. OPEN periods return 409 "
                "PERIOD_OPEN, LOCKED ones 409 PERIOD_LOCKED. " + TICKET_RULE,
                [ADMIN_KEY_PARAM, PERIOD_PATH, _body("ReviewResultsIn", "Result rows and ticket.")],
                "ReviewResultsImport", "Results imported.",
                {**ADMIN_ERRORS, **E404_PERIOD,
                 "409": _err("PERIOD_OPEN or PERIOD_LOCKED. Nothing was imported."),
                 "422": _err("INVALID_ROWS (detail lists each bad row), TICKET_REQUIRED or VALIDATION_ERROR.")},
            )
        },
        "/admin/reviews/forms": {
            "get": _op(
                "FindReviewForms", "Find an employee's review forms (phiếu đánh giá)",
                "Admin only (admin key). Lists forms with status, deadline, evaluators and goals/criteria (with "
                "their ids and weights). Filter by employee email (the person in the ticket), username, "
                "period_id and kind (KPI, REVIEW_360, PROBATION, CONTRACT). Use this FIRST to find the form_id "
                "and goal ids before any change. Unknown email returns 404 USER_NOT_FOUND: do not guess.",
                [ADMIN_KEY_PARAM,
                 _query("email", "Employee email, e.g. 'user2@demo.local'.", required=False),
                 _query("username", "Employee username, e.g. 'user2'.", required=False),
                 _query("period_id", "Period id, e.g. 'VINFAST-Q4-2026'.", required=False),
                 _query("kind", "KPI, REVIEW_360, PROBATION or CONTRACT.", required=False)],
                "ReviewFormList", "Matching forms (may be empty).",
                {**ADMIN_ERRORS, "404": _err("No employee has this email (USER_NOT_FOUND).")},
            )
        },
        "/admin/reviews/forms/{form_id}": {
            "get": _op(
                "GetReviewForm", "Get a review form",
                "Admin only (admin key). Returns one form with evaluators and goals. Use after a change to confirm it.",
                [ADMIN_KEY_PARAM, FORM_PATH], "ReviewForm", "The form.", {**ADMIN_ERRORS, **E404_FORM},
            )
        },
        "/admin/reviews/forms/{form_id}/reopen": {
            "post": _op(
                "ReopenReviewForm", "Reopen one employee's form",
                "Admin only (admin key). Sets the form back to DRAFT so the employee can edit it again "
                "('mở lại phiếu', 'mở hệ thống đánh giá KPI'). If the form's period is CLOSED, pass a personal "
                "deadline: this reopens the period for this employee only (422 DEADLINE_REQUIRED without it). "
                "Blocked for RESIGNED employees (409 EMPLOYEE_RESIGNED) and LOCKED periods or forms (409 "
                "PERIOD_LOCKED / FORM_LOCKED). Already DRAFT and nothing to change = NO_CHANGE. " + TICKET_RULE,
                [ADMIN_KEY_PARAM, FORM_PATH, _body("ReviewFormReopenIn", "Optional personal deadline and ticket.")],
                "ReviewFormChange", "Form reopened, or NO_CHANGE.",
                {**ADMIN_ERRORS, **E404_FORM, **E422_REVIEW,
                 "409": _err("EMPLOYEE_RESIGNED, PERIOD_LOCKED or FORM_LOCKED. Nothing was changed.")},
            )
        },
        "/admin/reviews/forms/{form_id}/extend": {
            "post": _op(
                "ExtendReviewForm", "Extend one employee's form deadline",
                "Admin only (admin key). Gives one form (KPI, 360, probation or contract) a later personal "
                "deadline, at most max_deadline (30 days after the original deadline), otherwise 422 "
                "EXTENSION_TOO_LONG. APPROVED forms return 409 FORM_APPROVED; a form in a CLOSED period returns "
                "409 PERIOD_CLOSED (use ReopenReviewForm with a deadline). Blocked for RESIGNED employees and "
                "LOCKED periods or forms. Same deadline = NO_CHANGE. " + TICKET_RULE,
                [ADMIN_KEY_PARAM, FORM_PATH, _body("ReviewDeadlineIn", "New deadline and ticket.")],
                "ReviewFormChange", "Deadline extended, or NO_CHANGE.",
                {**ADMIN_ERRORS, **E404_FORM, **E422_REVIEW,
                 "409": _err("FORM_APPROVED, PERIOD_CLOSED, EMPLOYEE_RESIGNED, PERIOD_LOCKED or FORM_LOCKED.")},
            )
        },
        "/admin/reviews/forms/{form_id}/evaluator": {
            "put": _op(
                "UpdateReviewEvaluator", "Change the evaluator of a form",
                "Admin only (admin key). Replaces an evaluator (người đánh giá), e.g. the manager on a probation "
                "or contract form, or one rater on a 360 form, keeping the relation. For forms with several "
                "evaluators (360) old_email is required (422 OLD_EVALUATOR_REQUIRED). The employee cannot "
                "evaluate themself (422 SELF_EVALUATOR); a resigned person cannot evaluate (422 "
                "EVALUATOR_RESIGNED); someone already on the form returns 409 EVALUATOR_DUPLICATE. APPROVED "
                "forms return 409 FORM_APPROVED. " + TICKET_RULE,
                [ADMIN_KEY_PARAM, FORM_PATH, _body("ReviewEvaluatorIn", "New (and old) evaluator email and ticket.")],
                "ReviewFormChange", "Evaluator changed, or NO_CHANGE.",
                {**ADMIN_ERRORS, **E404_FORM,
                 "409": _err("FORM_APPROVED, EVALUATOR_DUPLICATE, EMPLOYEE_RESIGNED, PERIOD_LOCKED or FORM_LOCKED."),
                 "422": _err("OLD_EVALUATOR_REQUIRED, SELF_EVALUATOR, EVALUATOR_RESIGNED, TICKET_REQUIRED or "
                             "VALIDATION_ERROR.")},
            )
        },
        "/admin/reviews/goals/{goal_id}": {
            "put": _op(
                "UpdateReviewGoal", "Edit a goal or criterion",
                "Admin only (admin key). Changes the text, weight or target of a goal (mục tiêu KPI) or criterion "
                "(tiêu chí thử việc / hợp đồng). Empty fields stay unchanged. The goal's form must not be "
                "APPROVED (409 FORM_APPROVED: reopen it first with ReopenReviewForm) or LOCKED, and the "
                "employee must not be RESIGNED. message warns when the weights no longer add up to 100%. "
                + TICKET_RULE,
                [ADMIN_KEY_PARAM, GOAL_PATH, _body("ReviewGoalIn", "Fields to change and ticket.")],
                "ReviewGoalChange", "Goal edited, or NO_CHANGE.",
                {**ADMIN_ERRORS, "404": _err("Unknown goal id (GOAL_NOT_FOUND)."),
                 "409": _err("FORM_APPROVED, EMPLOYEE_RESIGNED, PERIOD_LOCKED or FORM_LOCKED. Nothing was changed."),
                 "422": _err("TICKET_REQUIRED or VALIDATION_ERROR (weight not 1-100).")},
            ),
            "delete": _op(
                "DeleteReviewGoal", "Delete a goal or criterion",
                "Admin only (admin key). Deletes one goal or criterion created by mistake ('xóa tiêu chí do NLĐ "
                "tạo sai'). Call once per goal. The goal's form must not be APPROVED (409 FORM_APPROVED: reopen it "
                "first with ReopenReviewForm) or LOCKED, and the employee must not be RESIGNED. message warns "
                "when the remaining weights no longer add up to 100%. " + TICKET_RULE,
                [ADMIN_KEY_PARAM, GOAL_PATH, _query("ticket", "SDP ticket number, e.g. '#54'. Required.")],
                "ReviewGoalChange", "Goal deleted.",
                {**ADMIN_ERRORS, "404": _err("Unknown goal id (GOAL_NOT_FOUND)."),
                 "409": _err("FORM_APPROVED, EMPLOYEE_RESIGNED, PERIOD_LOCKED or FORM_LOCKED. Nothing was deleted."),
                 "422": _err("TICKET_REQUIRED.")},
            ),
        },
        "/admin/reviews/log": {
            "get": _op(
                "ListReviewLog", "List the review change log",
                "Admin only (admin key). Every change made through the review operations or by hand on the "
                "operator screen, newest first, with ticket, who made it (actor), operation, target and detail. "
                "Filter by ticket to show what was done for one ticket, or by target (period, form or goal id).",
                [ADMIN_KEY_PARAM, _query("ticket", "SDP ticket number, e.g. '#54'. Empty = all.", required=False),
                 _query("target", "Period, form or goal id, e.g. 'RF-1002'. Empty = all.", required=False)],
                "ReviewLog", "Log entries.", {**ADMIN_ERRORS, "422": _err("The ticket filter is not a ticket number (TICKET_REQUIRED).")},
            )
        },
    }


def _paths():
    return {**_permission_paths(), **_review_paths()}


def _permission_paths():
    return {
        "/health": {
            "get": {
                "operationId": "HealthCheck",
                "summary": "Check the API is up",
                "description": "Liveness check. No API key needed. Call only to confirm the service is reachable.",
                "parameters": [],
                "responses": {"200": {"description": "Service is up.", "schema": _ref("Health")}},
            }
        },
        "/me": {
            "get": _op(
                "GetMe", "Who am I",
                "Returns the account that owns the given API key. Use to confirm which user a key belongs to.",
                [ANY_KEY_PARAM], "User", "The caller's account.", E401,
            )
        },
        "/me/miniapps": {
            "get": _op(
                "ListMyMiniapps", "List miniapps visible to a user",
                "Acting AS A USER (pass that user's own key), lists the miniapps the user can see after "
                "system access was granted (tier 1). Each item has can_use=true only if the user was also "
                "added as a member (tier 2). Use this to verify, from the user's side, that grants worked.",
                [ANY_KEY_PARAM], "MyMiniapps", "Miniapps the caller can see.", E401,
            )
        },
        "/miniapps/{miniapp_id}/use": {
            "post": _op(
                "UseMiniapp", "Use a miniapp as a user",
                "Acting AS A USER (pass that user's own key), tries to use the miniapp. Returns 200 only if "
                "the user has both system access and membership. Returns 403 NOT_VISIBLE if system access "
                "is missing, 403 NOT_MEMBER if membership is missing. Use as the final proof that both "
                "permission tiers are in place.",
                [ANY_KEY_PARAM, MINIAPP_PATH], "UseResult", "The user used the miniapp successfully.",
                {**E401, "403": _err("NOT_VISIBLE (no system access) or NOT_MEMBER (not a member)."),
                 "404": _err("Unknown miniapp id (MINIAPP_NOT_FOUND).")},
            )
        },
        "/admin/users": {
            "get": _op(
                "ListUsers", "List all users and their permissions",
                "Admin only (admin key). Lists every user with the miniapps they have system access to "
                "(system_access) and the miniapps they are members of (memberships). Use to look up valid "
                "usernames or review current permissions.",
                [ADMIN_KEY_PARAM], "UserList", "All users with their grants.", ADMIN_ERRORS,
            )
        },
        "/admin/users/by-email": {
            "get": _op(
                "FindUserByEmail", "Find a user by email",
                "Admin only (admin key). Resolves a requester's email (for example the requester of a "
                "ticket) to their account: username, display name, email and current permissions "
                "(system_access, memberships). Case-insensitive. Use this FIRST when a request names a "
                "person by email, then use the returned username in the other operations. Unknown email "
                "returns 404 USER_NOT_FOUND: do not guess a username.",
                [ADMIN_KEY_PARAM, _query("email", "Requester email, e.g. 'user1@demo.local'.")],
                "UserWithGrants", "The user with this email and their permissions.",
                {**ADMIN_ERRORS, "404": _err("No user has this email (USER_NOT_FOUND)."),
                 "422": _err("The email parameter is missing or blank (VALIDATION_ERROR).")},
            )
        },
        "/admin/miniapps": {
            "get": _op(
                "ListMiniapps", "List all miniapps",
                "Admin only (admin key). Lists every miniapp with its id. Use to find the miniapp_id for a "
                "miniapp name, e.g. 'Nghỉ phép' is 'leave'.",
                [ADMIN_KEY_PARAM], "MiniappList", "All miniapps.", ADMIN_ERRORS,
            )
        },
        "/admin/system-access": {
            "post": _op(
                "GrantSystemAccess", "Grant system access to a miniapp (step 1)",
                "Admin only (admin key). STEP 1 of 2: grants a user system-level access so the miniapp "
                "becomes VISIBLE to them. The user still cannot use it until step 2 (AddMiniappMember). "
                "Always-visible miniapps (lms) need no system access: the call returns already_granted=true. "
                "Call CheckEligibility before granting: a user who is not eligible gets 403 NOT_ELIGIBLE. "
                "Safe to call twice (already_granted=true).",
                [ADMIN_KEY_PARAM, _body("SystemAccessIn", "Who gets access to which miniapp.")],
                "Grant", "System access granted (or already existed).", {**GRANT_ERRORS, **E404, **E422},
            )
        },
        "/admin/system-access/{username}/{miniapp_id}": {
            "delete": _op(
                "RevokeSystemAccess", "Revoke system access to a miniapp",
                "Admin only (admin key). Removes a user's system access to a miniapp. This ALSO removes "
                "their membership of that miniapp. revoked=false means there was nothing to remove.",
                [ADMIN_KEY_PARAM, USERNAME_PATH, MINIAPP_PATH],
                "Revoke", "System access removed (or did not exist).", {**ADMIN_ERRORS, **E404},
            )
        },
        "/admin/miniapps/{miniapp_id}/members": {
            "post": _op(
                "AddMiniappMember", "Add a user as a miniapp member (step 2)",
                "Admin only (admin key). STEP 2 of 2: inside the miniapp, adds the user as a member so they "
                "can USE it. Requires step 1 (GrantSystemAccess) first, otherwise returns 409 "
                "SYSTEM_ACCESS_REQUIRED, except for always-visible miniapps (lms). For lms pass role "
                "'learner' (Học viên) or 'instructor' (Giảng viên); calling again with another role changes "
                "the role. Call CheckEligibility before granting: a user who is not eligible for this role "
                "gets 403 NOT_ELIGIBLE (also when changing the role). Safe to call twice (already_granted=true).",
                [ADMIN_KEY_PARAM, MINIAPP_PATH, _body("MemberIn", "The user to add, and the role for lms.")],
                "Grant", "Member added, role changed, or already a member with this role.",
                {**GRANT_ERRORS, **E404,
                 "422": _err("A body field is missing (VALIDATION_ERROR) or the role is not valid for this "
                             "miniapp (INVALID_ROLE)."),
                 "409": _err("The user has no system access to this miniapp yet (SYSTEM_ACCESS_REQUIRED).")},
            )
        },
        "/admin/miniapps/{miniapp_id}/members/{username}": {
            "delete": _op(
                "RemoveMiniappMember", "Remove a user from a miniapp",
                "Admin only (admin key). Removes the user's membership of the miniapp; their system access "
                "stays, so the miniapp is still visible but not usable. revoked=false means they were not a "
                "member.",
                [ADMIN_KEY_PARAM, MINIAPP_PATH, USERNAME_PATH],
                "Revoke", "Membership removed (or did not exist).", {**ADMIN_ERRORS, **E404},
            )
        },
        "/admin/check": {
            "get": _op(
                "CheckAccess", "Check a user's access to a miniapp",
                "Admin only (admin key). Always returns 200 with visible (tier 1), can_use (tier 2) and the "
                "member role (lms) for the given user and miniapp. Use after granting to confirm the result. "
                "Unknown user or miniapp returns visible=false, can_use=false.",
                [ADMIN_KEY_PARAM,
                 _query("username", "Username to check, e.g. 'user1'."),
                 _query("miniapp_id", "Miniapp id to check, e.g. 'leave'.")],
                "Check", "Access status.", ADMIN_ERRORS,
            )
        },
        "/admin/eligibility": {
            "get": _op(
                "CheckEligibility", "Check if a user may be granted a miniapp or role",
                "Admin only (admin key). Call this BEFORE GrantSystemAccess or AddMiniappMember. Always "
                "returns 200. eligible=false means do not grant; reasons says why, in Vietnamese, and must be "
                "shown as is. Rules: a RESIGNED user is never eligible; some roles are limited, e.g. lms "
                "instructor is only for the L&D department or a job title containing 'giảng viên'. Pass "
                "approver_email (the approver named in the ticket) to check that the approver is the user's "
                "direct manager: approver_checked=true and approver_ok=false means the approver is not the "
                "direct manager. Revoking never needs this check.",
                [ADMIN_KEY_PARAM,
                 _query("username", "Username to check, e.g. 'user1'."),
                 _query("miniapp_id", "Miniapp id to grant, e.g. 'leave' or 'lms'."),
                 _query("role", "Role to grant, for lms only: 'learner' or 'instructor'. Leave empty otherwise.",
                        required=False),
                 _query("approver_email", "Email of the approver in the ticket. Leave empty if the ticket has none.",
                        required=False)],
                "Eligibility", "Eligibility result (also for unknown users or miniapps: eligible=false).",
                ADMIN_ERRORS,
            )
        },
        "/admin/reset": {
            "post": _op(
                "ResetAll", "Reset all permissions",
                "Admin only (admin key). Removes every system access and membership and restores the "
                "seeded users and miniapps, and restores the review data (periods, forms, goals, evaluators) "
                "and clears review results and the review log. Call only when explicitly asked to reset the test data.",
                [ADMIN_KEY_PARAM], "Reset", "All permissions cleared.", ADMIN_ERRORS,
            )
        },
    }


def clean_host(host):
    host = (host or "").strip()
    for prefix in ("https://", "http://"):
        if host.lower().startswith(prefix):
            host = host[len(prefix):]
    return host.split("/", 1)[0]


def build_swagger(host):
    return {
        "swagger": "2.0",
        "info": {
            "title": "Permission Test API",
            "version": "1.0.0",
            "description": (
                "Test API for two-tier miniapp permissions. Tier 1 (system access): an admin grants a user "
                "access so a miniapp becomes visible to them (GrantSystemAccess). Tier 2 (membership): the "
                "admin then adds the user as a member inside the miniapp so they can use it "
                "(AddMiniappMember). The mock LMS (lms) is always visible and its members have a role: "
                "learner or instructor. Grants are blocked (403 NOT_ELIGIBLE) "
                "for users who are not eligible: call CheckEligibility first. Admin operations (/admin/...) use the admin API key in X-API-Key; "
                "user operations (/me..., UseMiniapp) use that user's own key to verify the result. "
                "It also mocks an appraisal system (Đánh giá, /admin/reviews/...): review periods, each "
                "employee's KPI / 360 / probation / contract form with goals and evaluators, result uploads and "
                "a change log. Every review change needs an SDP ticket number."
            ),
        },
        "host": clean_host(host),
        "basePath": "/",
        "schemes": ["https"],
        "consumes": ["application/json"],
        "produces": ["application/json"],
        "paths": _paths(),
        "definitions": copy.deepcopy(DEFINITIONS),
    }
