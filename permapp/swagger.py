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


DEFINITIONS = {
    "Error": {
        "type": "object",
        "required": ["detail", "code"],
        "properties": {
            "detail": _str("Human-readable error message (Vietnamese)."),
            "code": _str(
                "Machine-readable error code: UNAUTHORIZED, ADMIN_REQUIRED, NOT_VISIBLE, NOT_MEMBER, "
                "USER_NOT_FOUND, MINIAPP_NOT_FOUND, SYSTEM_ACCESS_REQUIRED, INVALID_ROLE, VALIDATION_ERROR, "
                "NOT_FOUND."
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
    "Reset": {"type": "object", "properties": {"reset": _bool("Always true.")}},
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


def _query(name, desc):
    return {"name": name, "in": "query", "required": True, "type": "string", "description": desc}


def _body(schema_name, desc):
    return {"name": "body", "in": "body", "required": True, "description": desc, "schema": _ref(schema_name)}


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


def _paths():
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
                "Safe to call twice (already_granted=true).",
                [ADMIN_KEY_PARAM, _body("SystemAccessIn", "Who gets access to which miniapp.")],
                "Grant", "System access granted (or already existed).", {**ADMIN_ERRORS, **E404, **E422},
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
                "the role. Safe to call twice (already_granted=true).",
                [ADMIN_KEY_PARAM, MINIAPP_PATH, _body("MemberIn", "The user to add, and the role for lms.")],
                "Grant", "Member added, role changed, or already a member with this role.",
                {**ADMIN_ERRORS, **E404,
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
        "/admin/reset": {
            "post": _op(
                "ResetAll", "Reset all permissions",
                "Admin only (admin key). Removes every system access and membership and restores the "
                "seeded users and miniapps. Call only when explicitly asked to reset the test data.",
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
                "learner or instructor. Admin operations (/admin/...) use the admin API key in X-API-Key; "
                "user operations (/me..., UseMiniapp) use that user's own key to verify the result."
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
