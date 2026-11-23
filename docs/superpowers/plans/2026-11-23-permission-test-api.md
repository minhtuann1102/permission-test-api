# Permission Test API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Public HTTPS REST API on Vercel that Copilot Studio calls to grant two-tier (system → miniapp) permissions and verify them as a user.

**Architecture:** FastAPI app in root `app.py` (Vercel zero-config entrypoint) over a small `permapp/` package: `db.py` (SQLAlchemy Core schema, engine, seed/reset), `service.py` (permission rules, no HTTP), `swagger.py` (hand-written OpenAPI 2.0). SQLite locally/tests, Neon Postgres on Vercel.

**Tech Stack:** Python 3.11 local / 3.12 Vercel, FastAPI, SQLAlchemy 2 Core, psycopg[binary] 3, pytest + httpx TestClient, swagger-spec-validator.

**Spec:** `docs/superpowers/specs/2026-11-23-permission-test-api-design.md`

## Global Constraints

- Code must run on Python 3.11 and 3.12 (no 3.12-only syntax). `.python-version` contains `3.12`.
- Entrypoint: `app.py` at repo root exposing FastAPI instance `app`. Runtime deps in `requirements.txt` only: `fastapi`, `sqlalchemy>=2`, `psycopg[binary]>=3.1`. Dev deps in `requirements-dev.txt` (`-r requirements.txt`, `pytest`, `httpx`, `uvicorn`, `swagger-spec-validator`).
- DB URL: `DATABASE_URL` or else `POSTGRES_URL`; `postgres://` and `postgresql://` → `postgresql+psycopg://`; neither set → `sqlite:///./local.db`. Postgres engines use `NullPool`.
- Seed: admin `admin` key = env `ADMIN_API_KEY` default `admin-key-123`; users `user1`/`user1-key-123`, `user2`/`user2-key-123`; miniapps `leave` "Nghỉ phép", `expense` "Chi phí", `inventory` "Kho".
- Auth header is exactly `X-API-Key`.
- Every error body is JSON `{"detail": <str>, "code": <str>}`. Codes: `UNAUTHORIZED` 401, `ADMIN_REQUIRED` 403, `NOT_VISIBLE` 403, `NOT_MEMBER` 403, `USER_NOT_FOUND` 404, `MINIAPP_NOT_FOUND` 404, `SYSTEM_ACCESS_REQUIRED` 409, `VALIDATION_ERROR` 422.
- Successful writes return 200 (not 201). `/admin/check` always 200.
- Swagger: `swagger: "2.0"`, `schemes: ["https"]`, `host` without scheme; no `oneOf`/`anyOf`/`nullable`.
- Run commands from repo root using the venv: `.venv\Scripts\python -m pytest ...`.

## Review Focus

1. Missing or wrong `X-API-Key` → 401 JSON with `code: "UNAUTHORIZED"`, never HTML or 500. (Task 3 test)
2. Unknown username / miniapp_id in any grant or revoke → 404 JSON, not a 500 from a FK/None. (Tasks 2 & 3 tests)
3. Granting or revoking twice → 200, no IntegrityError 500. (Task 2 test)
4. Neon-style URL `postgres://u:p@h/db?sslmode=require` normalizes to `postgresql+psycopg://u:p@h/db?sslmode=require` (query kept). (Task 1 test)
5. Two cold starts seeding concurrently → no crash, no duplicate rows: seeding inserts row-by-row and ignores IntegrityError. (Task 1 test: calling `init_db` twice leaves exactly 3 users / 3 miniapps)

---

### Task 1: Project scaffold + database layer

**Files:**
- Create: `requirements.txt`, `requirements-dev.txt`, `.python-version`, `.gitignore` (`.venv/`, `__pycache__/`, `local.db`, `.vercel/`, `.pytest_cache/`), `.vercelignore` (`.venv`, `tests`, `local.db`, `docs`), `permapp/__init__.py`, `permapp/db.py`
- Test: `tests/conftest.py`, `tests/test_db.py`

**Interfaces:**
- Produces (`permapp/db.py`):
  - `normalize_db_url(url: str | None) -> str`
  - `make_engine(url: str) -> sqlalchemy.Engine` (NullPool for postgres; `check_same_thread=False` for sqlite)
  - `get_engine() -> Engine` — `functools.lru_cache`d, reads env via `normalize_db_url`
  - `metadata: MetaData`; `Table`s `users(username PK str, api_key str unique, role str 'admin'|'user', display_name str)`, `miniapps(id PK str, name str, description str)`, `system_grants(username FK, miniapp_id FK, PK both)`, `miniapp_grants(username FK, miniapp_id FK, PK both)`
  - `SEED_USERS: list[dict]`, `SEED_MINIAPPS: list[dict]` (values from Global Constraints; admin key read from env at seed time)
  - `init_db(engine) -> None` — `create_all` + insert each seed row if absent, ignoring `IntegrityError`
  - `reset_db(engine) -> None` — delete all grants, then ensure seed rows exist (users/miniapps restored to seed values)
- Produces (`tests/conftest.py`): fixture `engine(tmp_path)` → `make_engine(f"sqlite:///{tmp_path}/t.db")` after `init_db`.

- [ ] **Step 1: Create venv and install** — `python -m venv .venv` then `.venv\Scripts\python -m pip install -r requirements-dev.txt`. Expected: installs without error.
- [ ] **Step 2: Write failing tests in `tests/test_db.py`**

```python
def test_normalize_db_url():
    assert normalize_db_url(None) == "sqlite:///./local.db"
    assert normalize_db_url("postgres://u:p@h/db?sslmode=require") == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert normalize_db_url("postgresql://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_db_url("sqlite:///x.db") == "sqlite:///x.db"

def test_init_db_seeds_once(engine):
    init_db(engine)  # second call
    with engine.connect() as c:
        assert c.execute(select(func.count()).select_from(users)).scalar() == 3
        assert c.execute(select(func.count()).select_from(miniapps)).scalar() == 3
        roles = dict(c.execute(select(users.c.username, users.c.role)).all())
    assert roles == {"admin": "admin", "user1": "user", "user2": "user"}

def test_reset_clears_grants(engine):
    with engine.begin() as c:
        c.execute(system_grants.insert().values(username="user1", miniapp_id="leave"))
        c.execute(miniapp_grants.insert().values(username="user1", miniapp_id="leave"))
    reset_db(engine)
    with engine.connect() as c:
        assert c.execute(select(func.count()).select_from(system_grants)).scalar() == 0
        assert c.execute(select(func.count()).select_from(miniapp_grants)).scalar() == 0
        assert c.execute(select(func.count()).select_from(users)).scalar() == 3
```

- [ ] **Step 3: Run** `.venv\Scripts\python -m pytest tests/test_db.py -v` — Expected: FAIL (ImportError).
- [ ] **Step 4: Implement `permapp/db.py`** per Interfaces.
- [ ] **Step 5: Run** same command — Expected: 3 passed.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: database layer with seed and reset"`

---

### Task 2: Permission service

**Files:**
- Create: `permapp/service.py`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: Task 1 tables, `engine` fixture.
- Produces (`permapp/service.py`), all take `engine` first:
  - `class ServiceError(Exception)` with attrs `status: int`, `code: str`, `detail: str`; constructor `ServiceError(status, code, detail)`
  - `get_user_by_key(engine, api_key: str) -> dict | None` → `{"username","role","display_name"}`
  - `list_miniapps(engine) -> list[dict]` → `{"id","name","description"}` sorted by id
  - `list_visible_miniapps(engine, username: str) -> list[dict]` → miniapp dict + `"can_use": bool`; admin sees all with `can_use=True`; user sees only system-granted ones
  - `check_access(engine, username, miniapp_id) -> dict` → `{"username","miniapp_id","visible","can_use"}`; admin → both True; raises 404 errors for unknown user/miniapp
  - `grant_system_access(engine, username, miniapp_id) -> dict` → `{"username","miniapp_id","already_granted": bool}`
  - `revoke_system_access(engine, username, miniapp_id) -> dict` → `{"username","miniapp_id","revoked": bool}`; also deletes the matching `miniapp_grants` row
  - `grant_membership(engine, miniapp_id, username) -> dict` → `{"username","miniapp_id","already_granted"}`; raises `ServiceError(409,"SYSTEM_ACCESS_REQUIRED",...)` if the target has no system grant for that miniapp (same rule for every role)
  - `revoke_membership(engine, miniapp_id, username) -> dict` → `{"username","miniapp_id","revoked"}`
  - `use_miniapp(engine, username, miniapp_id) -> dict` → `{"miniapp_id","used_by","message": f"{username} đã sử dụng miniapp {name} thành công"}`; raises 404 `MINIAPP_NOT_FOUND`, 403 `NOT_VISIBLE`, 403 `NOT_MEMBER` (admin always allowed)
  - `list_users_with_grants(engine) -> list[dict]` → `{"username","role","display_name","system_access": [ids sorted],"memberships": [ids sorted]}` sorted by username
  - Unknown user → `ServiceError(404,"USER_NOT_FOUND",...)`; unknown miniapp → `ServiceError(404,"MINIAPP_NOT_FOUND",...)`. Details in Vietnamese or English, builder's call.

- [ ] **Step 1: Write failing tests in `tests/test_service.py`**

```python
def test_full_two_tier_flow(engine):
    assert check_access(engine, "user1", "leave") == {"username":"user1","miniapp_id":"leave","visible":False,"can_use":False}
    assert list_visible_miniapps(engine, "user1") == []
    assert grant_system_access(engine, "user1", "leave")["already_granted"] is False
    assert [m["id"] for m in list_visible_miniapps(engine, "user1")] == ["leave"]
    assert check_access(engine, "user1", "leave")["can_use"] is False
    with pytest.raises(ServiceError) as e: use_miniapp(engine, "user1", "leave")
    assert (e.value.status, e.value.code) == (403, "NOT_MEMBER")
    grant_membership(engine, "leave", "user1")
    assert check_access(engine, "user1", "leave") == {"username":"user1","miniapp_id":"leave","visible":True,"can_use":True}
    assert use_miniapp(engine, "user1", "leave")["used_by"] == "user1"
    assert check_access(engine, "user2", "leave")["visible"] is False  # isolation

def test_membership_requires_system_access(engine):
    with pytest.raises(ServiceError) as e: grant_membership(engine, "leave", "user1")
    assert (e.value.status, e.value.code) == (409, "SYSTEM_ACCESS_REQUIRED")

def test_use_not_visible(engine):
    with pytest.raises(ServiceError) as e: use_miniapp(engine, "user1", "leave")
    assert e.value.code == "NOT_VISIBLE"

def test_revoke_system_cascades(engine):
    grant_system_access(engine, "user1", "leave"); grant_membership(engine, "leave", "user1")
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
    with pytest.raises(ServiceError) as e: fn(engine, *args)
    assert (e.value.status, e.value.code) == (404, code)

def test_admin_sees_and_uses_all(engine):
    assert len(list_visible_miniapps(engine, "admin")) == 3
    assert use_miniapp(engine, "admin", "inventory")["used_by"] == "admin"

def test_get_user_by_key(engine):
    assert get_user_by_key(engine, "user1-key-123")["username"] == "user1"
    assert get_user_by_key(engine, "nope") is None
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_service.py -v` — Expected: FAIL (ImportError).
- [ ] **Step 3: Implement `permapp/service.py`** per Interfaces. Insert-if-absent via a select-then-insert inside `engine.begin()`, catching `IntegrityError` → `already_granted=True`.
- [ ] **Step 4: Run** — Expected: all passed.
- [ ] **Step 5: Commit** — `git commit -am`-style: `git add -A && git commit -m "feat: two-tier permission service"`

---

### Task 3: HTTP API (FastAPI app)

**Files:**
- Create: `app.py`
- Test: `tests/test_api.py`

**Interfaces:**
- Consumes: Task 1 `get_engine`, `init_db`, `reset_db`; Task 2 everything.
- Produces (`app.py`): `app: FastAPI` (title "Permission Test API"); dependency `current_user(x_api_key: str | None = Header(None, alias="X-API-Key")) -> dict` (401 `UNAUTHORIZED`); `require_admin(user=Depends(current_user)) -> dict` (403 `ADMIN_REQUIRED`). DB initialised lazily once per process (module-level flag) inside a dependency `db_engine() -> Engine` that calls `get_engine()` + `init_db`. Exception handlers turn `ServiceError`, `HTTPException`, and `RequestValidationError` into `{"detail","code"}` (validation → 422 `VALIDATION_ERROR`; HTTPException uses `exc.detail` dict if it already has a code).
- Routes exactly as the spec's Endpoints table, except `/swagger.json` (Task 4). Request bodies: `SystemAccessIn{username: str, miniapp_id: str}`, `MemberIn{username: str}`. Responses: service dicts; `/me/miniapps` → `{"username", "miniapps": [...]}`; `/admin/users` → `{"users": [...]}`; `/admin/miniapps` → `{"miniapps": [...]}`; `/admin/reset` → `{"reset": true}`; `/health` → `{"status": "ok"}`; `/me` → user dict.
- `GET /` returns `HTMLResponse`: a table of users × miniapps showing visible/can_use (from `list_users_with_grants`). Plain inline CSS, no JS.
- Test fixture: `client(tmp_path, monkeypatch)` sets `DATABASE_URL=sqlite:///{tmp_path}/api.db`, calls `get_engine.cache_clear()`, resets the app's init flag, yields `TestClient(app)`. Constants `ADMIN={"X-API-Key":"admin-key-123"}`, `U1={"X-API-Key":"user1-key-123"}`.

- [ ] **Step 1: Write failing tests in `tests/test_api.py`**

```python
def test_end_to_end_flow(client):
    assert client.get("/me/miniapps", headers=U1).json()["miniapps"] == []
    r = client.post("/admin/system-access", json={"username":"user1","miniapp_id":"leave"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["already_granted"] is False
    ms = client.get("/me/miniapps", headers=U1).json()["miniapps"]
    assert [(m["id"], m["can_use"]) for m in ms] == [("leave", False)]
    r = client.post("/miniapps/leave/use", headers=U1)
    assert r.status_code == 403 and r.json()["code"] == "NOT_MEMBER"
    assert client.post("/admin/miniapps/leave/members", json={"username":"user1"}, headers=ADMIN).status_code == 200
    assert client.post("/miniapps/leave/use", headers=U1).status_code == 200
    assert client.get("/admin/check", params={"username":"user1","miniapp_id":"leave"}, headers=ADMIN).json() == {"username":"user1","miniapp_id":"leave","visible":True,"can_use":True}
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
    r = client.post("/admin/miniapps/leave/members", json={"username":"user1"}, headers=ADMIN)
    assert r.status_code == 409 and r.json()["code"] == "SYSTEM_ACCESS_REQUIRED"

def test_unknown_ids_404(client):
    r = client.post("/admin/system-access", json={"username":"ghost","miniapp_id":"leave"}, headers=ADMIN)
    assert r.status_code == 404 and r.json()["code"] == "USER_NOT_FOUND"
    r = client.delete("/admin/miniapps/ghost/members/user1", headers=ADMIN)
    assert r.status_code == 404 and r.json()["code"] == "MINIAPP_NOT_FOUND"

def test_validation_error_shape(client):
    r = client.post("/admin/system-access", json={"username":"user1"}, headers=ADMIN)
    assert r.status_code == 422 and r.json()["code"] == "VALIDATION_ERROR" and isinstance(r.json()["detail"], str)

def test_revoke_endpoints(client):
    client.post("/admin/system-access", json={"username":"user1","miniapp_id":"leave"}, headers=ADMIN)
    client.post("/admin/miniapps/leave/members", json={"username":"user1"}, headers=ADMIN)
    assert client.delete("/admin/miniapps/leave/members/user1", headers=ADMIN).json()["revoked"] is True
    assert client.delete("/admin/system-access/user1/leave", headers=ADMIN).json()["revoked"] is True
    assert client.get("/me/miniapps", headers=U1).json()["miniapps"] == []

def test_public_pages(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/"); assert r.status_code == 200 and "user1" in r.text
    assert len(client.get("/admin/users", headers=ADMIN).json()["users"]) == 3
```

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_api.py -v` — Expected: FAIL (ImportError).
- [ ] **Step 3: Implement `app.py`** per Interfaces.
- [ ] **Step 4: Run full suite** `.venv\Scripts\python -m pytest -v` — Expected: all passed.
- [ ] **Step 5: Smoke run** `.venv\Scripts\python -m uvicorn app:app --port 8000` in background, `curl -s http://127.0.0.1:8000/health` → `{"status":"ok"}`, then stop the server and delete `local.db`.
- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat: FastAPI endpoints for two-tier permissions"`

---

### Task 4: OpenAPI 2.0 (Swagger) for Copilot Studio

**Files:**
- Create: `permapp/swagger.py`
- Modify: `app.py` (add `GET /swagger.json`)
- Test: `tests/test_swagger.py`

**Interfaces:**
- Consumes: `app` routes from Task 3 (paths/methods), response shapes from Task 3.
- Produces: `build_swagger(host: str) -> dict` in `permapp/swagger.py`; route `GET /swagger.json` returning it with `host = os.environ.get("PUBLIC_HOST") or request.headers.get("x-forwarded-host") or request.headers["host"]` (strip any `https://` prefix).
- Spec content: `info.title "Permission Test API"`, `info.version "1.0.0"`, `info.description` explaining the two tiers and that admin uses the admin key and users their own key; `basePath "/"`; `consumes`/`produces` `["application/json"]`; `definitions` for every response/body object (Error, Miniapp, VisibleMiniapp, User, UserWithGrants, Grant, Revoke, Check, UseResult, and list wrappers); every operation has `operationId` (camel-case alphanumeric, e.g. `GrantSystemAccess`, `AddMiniappMember`, `CheckAccess`, `ListMyMiniapps`, `UseMiniapp`, `ResetAll`), `summary`, `description` (written for an LLM choosing tools: say when to call it and which key to use), `X-API-Key` header param (`required: true`, `type: string`, description says admin key for /admin, user key otherwise) on every authed op, `responses` for 200 plus relevant error codes referencing `#/definitions/Error`. Exclude `/`, `/swagger.json` from the spec; include `/health`.

- [ ] **Step 1: Write failing tests in `tests/test_swagger.py`**

```python
EXCLUDED = {"/", "/swagger.json", "/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}

def test_valid_swagger_20():
    spec = build_swagger("example.vercel.app")
    swagger_spec_validator.validator20.validate_spec(spec)
    assert spec["swagger"] == "2.0" and spec["schemes"] == ["https"] and spec["host"] == "example.vercel.app"

def test_every_route_documented():
    spec = build_swagger("h")
    for r in app.routes:
        if isinstance(r, APIRoute) and r.path not in EXCLUDED:
            for m in r.methods - {"HEAD"}:
                assert m.lower() in spec["paths"][r.path], (m, r.path)

def test_operation_rules():
    spec = build_swagger("h"); ids = []
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            ids.append(op["operationId"])
            assert re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", op["operationId"])
            assert op["summary"] and op["description"] and "200" in op["responses"]
            if path != "/health":
                assert any(p["in"] == "header" and p["name"] == "X-API-Key" and p["required"] for p in op["parameters"])
            for p in op.get("parameters", []):
                if p["in"] == "path": assert p["required"] is True
    assert len(ids) == len(set(ids))
    text = json.dumps(spec)
    for banned in ('"oneOf"', '"anyOf"', '"nullable"'): assert banned not in text

def test_endpoint_uses_forwarded_host(client):
    r = client.get("/swagger.json", headers={"x-forwarded-host": "perm.vercel.app"})
    assert r.status_code == 200 and r.json()["host"] == "perm.vercel.app"
```

(`client` fixture: move it from `tests/test_api.py` into `tests/conftest.py`.)

- [ ] **Step 2: Run** `.venv\Scripts\python -m pytest tests/test_swagger.py -v` — Expected: FAIL (ImportError).
- [ ] **Step 3: Implement `permapp/swagger.py` and the route.**
- [ ] **Step 4: Run full suite** `.venv\Scripts\python -m pytest -v` — Expected: all passed.
- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat: OpenAPI 2.0 spec for Copilot Studio"`

---

### Task 5: Deploy to Vercel (controller does this, needs the user)

- [ ] **Step 1:** User runs `npx vercel login`. Verify: `npx vercel whoami` prints a username.
- [ ] **Step 2:** `npx vercel link --yes` (creates project). User adds Neon Postgres in Vercel Dashboard → Storage and connects it to the project (Production env). Verify: `npx vercel env ls` lists `DATABASE_URL`.
- [ ] **Step 3:** `npx vercel --prod --yes`. Note the production domain `<project>.vercel.app`.
- [ ] **Step 4:** Verify without cookies:
  - `curl -s https://<project>.vercel.app/health` → `{"status":"ok"}` (if HTML login page → disable Deployment Protection for production / use production domain)
  - `curl -s https://<project>.vercel.app/swagger.json` → `"host": "<project>.vercel.app"`
  - Run the end-to-end flow with curl (grant tier 1 → `/me/miniapps` shows `leave` with `can_use:false` → add member → `/miniapps/leave/use` 200 → `/admin/reset`).
- [ ] **Step 5:** Write `README.md` (Vietnamese): base URL, API keys, flow, how to import `/swagger.json` into Copilot Studio (REST API tool / custom connector "Import from OpenAPI URL"). Commit.
