# Permission Test API — Design

## Intent
A public HTTPS REST API (Python, on Vercel) used as a target for testing an AI agent
built in **Copilot Studio** that automates two-tier permission granting:

1. **System tier** — a user can log in but cannot see a miniapp until an admin grants
   system access for that miniapp.
2. **Miniapp tier** — once visible, an admin goes "into" the miniapp and adds the user as a
   member; only then can the user actually use the miniapp.

Two roles: **admin** (grants/revokes) and **user** (used to verify the grants worked).

## Goals
- Stable public HTTPS URL on Vercel production domain (no tunnel).
- Hand-written **OpenAPI 2.0 (Swagger)** at `/swagger.json`, importable as a Power Platform
  custom connector / Copilot Studio REST API tool.
- Repeatable tests: `POST /admin/reset` restores the seeded state.

## Non-goals
- No admin UI. Only a minimal read-only HTML status page at `/`.
- No real login/OAuth. API keys only.

## Constraints
- Vercel serverless: no persistent local disk → Neon Postgres (pooled `DATABASE_URL`).
- Local dev/tests use SQLite via the same SQLAlchemy Core code.
- Copilot Studio treats non-2xx as tool failure → read-only check endpoints always return 200.

## Approaches considered
- **Tunnel to local backend** — rejected: URL changes, ngrok/devtunnel interstitials/auth broke it.
- **Vercel + FastAPI + Neon** — chosen: stable HTTPS, zero-config Python.
- Auth: two connectors with fixed keys vs **one connector with `X-API-Key` as a normal header
  parameter** — chosen the latter so the agent passes the admin key or a user key per call.

## Decisions
- Stack: FastAPI, SQLAlchemy Core (NullPool), psycopg[binary]; entrypoint `app.py` exposing `app`.
- DB URL: `DATABASE_URL` or `POSTGRES_URL`; `postgres://` → `postgresql+psycopg://`; absent →
  `sqlite:///./local.db`. Schema `CREATE TABLE IF NOT EXISTS` + seed if empty, on first request.
- Seed: admin `admin` (key `ADMIN_API_KEY` env, default `admin-key-123`), users `user1`
  (`user1-key-123`), `user2` (`user2-key-123`); miniapps `leave` (Nghỉ phép),
  `expense` (Chi phí), `inventory` (Kho).
- Tables: `users(username, api_key, role, display_name)`, `miniapps(id, name, description)`,
  `system_grants(username, miniapp_id)`, `miniapp_grants(username, miniapp_id)`.
- Rules: granting miniapp membership requires system access (else 409 `SYSTEM_ACCESS_REQUIRED`);
  revoking system access also removes membership; grants are idempotent
  (`already_granted: true`); admin sees all miniapps.
- Errors: JSON `{"detail": str, "code": str}`; 401 missing/invalid key, 403 wrong role or
  no permission, 404 unknown user/miniapp, 409 ordering violation.

## Endpoints (all JSON; auth via header `X-API-Key` unless noted)
| Method | Path | Role | Purpose |
|---|---|---|---|
| GET | `/health` | none | liveness |
| GET | `/` | none | HTML status page of grants |
| GET | `/swagger.json` | none | OpenAPI 2.0 spec |
| GET | `/me` | any | who am I |
| GET | `/me/miniapps` | any | miniapps visible to caller, each with `can_use` |
| POST | `/miniapps/{miniapp_id}/use` | any | 200 if caller can use; 403 `NOT_VISIBLE` / `NOT_MEMBER` |
| GET | `/admin/users` | admin | users with their grants |
| GET | `/admin/miniapps` | admin | all miniapps |
| POST | `/admin/system-access` | admin | body `{username, miniapp_id}` → grant tier 1 |
| DELETE | `/admin/system-access/{username}/{miniapp_id}` | admin | revoke tier 1 (+tier 2) |
| POST | `/admin/miniapps/{miniapp_id}/members` | admin | body `{username}` → grant tier 2 |
| DELETE | `/admin/miniapps/{miniapp_id}/members/{username}` | admin | revoke tier 2 |
| GET | `/admin/check?username=&miniapp_id=` | admin | always 200 `{visible, can_use}` |
| POST | `/admin/reset` | admin | wipe grants, reseed |

## Swagger 2.0 requirements
`swagger: "2.0"`, `schemes: ["https"]`, `host` = `PUBLIC_HOST` env or request
`x-forwarded-host`/`host` (no scheme). Each operation: unique alphanumeric `operationId`,
meaningful `summary` + `description`, `X-API-Key` header parameter (required where auth needed),
explicit response schemas; no `oneOf`/`anyOf`/`nullable`; path params `required: true`.
Validated with `swagger-spec-validator`. A test asserts every FastAPI route appears in the spec.

## Done criteria
- pytest (SQLite): full flow — tier 1 → visible; tier 2 → usable; reset → back to nothing.
- Swagger validates as 2.0.
- After deploy, `curl https://<project>.vercel.app/health` with no cookies returns JSON, not a
  Vercel login page.

## Left to the builder
Response field naming details, HTML status page styling, test organisation.
