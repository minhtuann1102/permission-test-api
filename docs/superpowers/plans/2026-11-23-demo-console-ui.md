# Demo Console UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Vietnamese web console at `/` to demo the two-tier permission flow by hand (admin + user1/user2), styled to the Hallmark Cobalt theme, sharing the API the Copilot Studio agent uses.

**Architecture:** FastAPI serves a static page (`permapp/static/`) at `/` and mounts the folder at `/static`; the old status table moves to `/status`. The page is vanilla JS: a pure logic file (`console-logic.js`, unit-tested with `node --test`) and a DOM/fetch file (`console.js`) that calls the existing JSON endpoints with `X-API-Key`.

**Tech Stack:** FastAPI + Starlette `StaticFiles`, vanilla HTML/CSS/JS, Google Fonts (Familjen Grotesk, IBM Plex Sans), pytest, Node 22 `node --test`, Hallmark `theme.mjs` + `sloplint.mjs`.

**Spec:** `docs/superpowers/specs/2026-11-23-demo-console-ui-design.md`

Hallmark scripts dir (below: `$HM`): `C:/Users/NITRO/.claude/plugins/cache/hallmark/hallmark/2.0.0/hallmark/scripts`

## Global Constraints

- No API rule or response changes; the UI only calls existing endpoints.
- User keys pre-filled: `user1-key-123`, `user2-key-123`. Admin key is never in the repo or page source; entered once, stored in `localStorage`.
- `/` and `/status` are not in `swagger.json`.
- All UI copy in Vietnamese. Status labels exactly: `Không có quyền` / `Chỉ nhìn thấy` / `Dùng được`; switches `Quyền hệ thống`, `Thành viên`; actions `Đổi admin key`, `Reset dữ liệu`, `Mở miniapp`; waiting state `Chờ admin thêm bạn vào`.
- Admin table rows: accounts with `role == "user"` only.
- Poll every 3000 ms; skip polls while a UI request is in flight; refetch after each request; highlight only changes the UI did not cause.
- Hallmark Floor, app scope: every colour/font via `:root` tokens; no emoji icons, no uppercase/tracked labels or table heads, no decorative status dot, no `transition: all`, `:focus-visible` on every control, `prefers-reduced-motion` fallback. Stamp `theme: cobalt (by request)`, `shape: app screen`.
- No new Python dependencies.

## Review Focus

1. A poll response that was requested before a click finishes arrives after it and flips the switch back → poll results are discarded if a UI request started after the poll was sent (sequence guard); covered by `shouldApplyPoll` tests (Task 2).
2. A stored admin key that is wrong (or changed on Vercel) → first 401 clears it and shows the key form again; polling as admin stops until a key is entered, no repeated error notices (Task 4 browser check).
3. A poll fails (Neon cold start, network, 500) → keep showing last good data with a quiet inline "Không cập nhật được, đang thử lại" line; next poll retries; no notice spam (Task 3 browser check).
4. Double-clicking a switch → the switch is disabled while its own request is in flight (Task 4 browser check).
5. `localStorage` unavailable (private window) → every read/write in try/catch; key and role kept in memory for the session (Task 2 `safeStore` test).

---

### Task 1: Routes — console at `/`, status table at `/status`, static mount

**Files:**
- Modify: `app.py` (the `status_page` route, imports, add mount)
- Create: `permapp/static/console.html` (placeholder for now: valid HTML with `<main id="app">`)
- Test: `tests/test_api.py` (`test_public_pages`), `tests/test_swagger.py` (`EXCLUDED`)

**Interfaces:**
- Produces: `GET /` → `console.html` (text/html); `GET /status` → the existing status table HTML; `GET /static/<file>` → files in `permapp/static/`. Static dir resolved as `Path(__file__).parent / "permapp" / "static"`.

- [ ] **Step 1: Update tests**

```python
def test_public_pages(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html") and 'id="app"' in r.text
    s = client.get("/status")
    assert s.status_code == 200 and "user1" in s.text
    assert client.get("/static/console.html").status_code == 200
    assert len(client.get("/admin/users", headers=ADMIN).json()["users"]) == 3
```
In `tests/test_swagger.py` add `"/status"` to `EXCLUDED`, and add `test_ui_routes_not_in_swagger`: `"/" not in spec["paths"] and "/status" not in spec["paths"]`.

- [ ] **Step 2: Run** `.venv/Scripts/python -m pytest -q` — Expected: `test_public_pages` FAILS (no `id="app"` at `/`).
- [ ] **Step 3: Implement** — rename the current `status_page` route path to `/status` (`include_in_schema=False`); add `@app.get("/", include_in_schema=False)` returning `FileResponse(STATIC_DIR / "console.html")`; `app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")` after all routes. Status page's swagger link text unchanged.
- [ ] **Step 4: Run** `.venv/Scripts/python -m pytest -q` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: serve console at / and move status table to /status`

### Task 2: Pure console logic

**Files:**
- Create: `permapp/static/console-logic.js`
- Test: `tests/console-logic.test.cjs`

**Interfaces:**
- Produces (attached to `globalThis.ConsoleLogic`, and `module.exports` when `module` exists):
  - `cellState(user, miniappId) -> "none"|"see"|"use"` — `user` is an `/admin/users` item (`system_access`, `memberships` arrays).
  - `adminSnapshot(users, miniapps) -> {[ "username|miniappId" ]: state}` — only `role === "user"`.
  - `userSnapshot(miniapps) -> {[id]: "use"|"see"}` — from `/me/miniapps` items (`can_use`).
  - `diffSnapshots(prev, next) -> string[]` — keys added, removed or changed; `prev == null` → `[]`.
  - `shouldApplyPoll(pollSeq, lastMutationStartSeq) -> boolean` — true iff `pollSeq > lastMutationStartSeq` (both from one shared counter incremented when any request starts).
  - `safeStore(storage) -> {get(k), set(k, v), remove(k)}` — wraps a Storage-like object; any throw (or `storage` null) falls back to an in-memory map.
  - `STATE_LABEL = {none: "Không có quyền", see: "Chỉ nhìn thấy", use: "Dùng được"}`.

- [ ] **Step 1: Write failing tests** (`node:test` + `node:assert/strict`, `require("../permapp/static/console-logic.js")`):
  - `cellState`: membership+system → `"use"`; system only → `"see"`; neither → `"none"`.
  - `adminSnapshot` with admin, user1 (leave: use), user2 (inventory: see) over 3 miniapps → 6 keys, no `admin|…` key, `user1|leave` = `"use"`, `user2|inventory` = `"see"`, `user2|leave` = `"none"`.
  - `userSnapshot([{id:"leave",can_use:true},{id:"expense",can_use:false}])` → `{leave:"use",expense:"see"}`.
  - `diffSnapshots(null, {a:"x"})` → `[]`; `diffSnapshots({a:"x",b:"y"},{a:"z",c:"y"})` sorted → `["a","b","c"]`.
  - `shouldApplyPoll(5, 4)` → true; `shouldApplyPoll(5, 6)` → false; `shouldApplyPoll(5, 5)` → false.
  - `safeStore` with a storage whose methods throw → `set("k","v")` then `get("k")` returns `"v"`; `safeStore(null)` same.
- [ ] **Step 2: Run** `node --test tests/` — Expected: FAIL (module not found).
- [ ] **Step 3: Implement** `console-logic.js` as a plain script (no `import`/`export`), wrapped in an IIFE.
- [ ] **Step 4: Run** `node --test tests/` — Expected: all pass.
- [ ] **Step 5: Commit** `feat: console pure logic with node tests`

### Task 3: Page shell, Cobalt tokens, top bar and user view

**Files:**
- Create: `permapp/static/tokens.css`, `permapp/static/base.css` (Hallmark scaffold), `permapp/static/console.css`, `permapp/static/console.js`
- Modify: `permapp/static/console.html`

**Interfaces:**
- Consumes: Task 2 `ConsoleLogic`.
- Produces in `console.js`: `api(path, {method, body, key}) -> Promise<{ok, status, data}>` (never throws on HTTP errors; network error → `{ok:false,status:0,data:{detail:"Không kết nối được máy chủ"}}`); `nextSeq() -> number` (one counter shared by polls and mutations); `beginMutation()` (sets `lastMutationStartSeq = nextSeq()`, increments `inFlight`) / `endMutation()` (decrements); `render()` per role; `notify(kind, text)` (kind `success`|`error`) shown in one `role="status"` live region, auto-hides after 5 s.

- [ ] **Step 1: Scaffold** — read `references/themes/cobalt.md` and `references/patterns.md` once; run `node $HM/theme.mjs scaffold cobalt --scope app --dir permapp/static`. Stamp field `theme: cobalt (by request)`.
- [ ] **Step 2: Build the shell** — `console.html` links Google Fonts (Familjen Grotesk 500/600, IBM Plex Sans 400/500/600, `&subset` not needed, CSS2 API serves Vietnamese), `/static/console.css`, then `console-logic.js` and `console.js` (deferred). `<noscript>` line pointing to `/status`. Top bar: wordmark "Quản lý quyền miniapp", plain-text refresh indicator ("Tự cập nhật mỗi 3 giây" / "Không cập nhật được, đang thử lại"), segmented switcher Admin / user1 / user2 (`role="tablist"`-free: use buttons with `aria-pressed`). Selected role persisted via `safeStore(localStorage)` key `permconsole.role`, default `user1`.
- [ ] **Step 3: User view** — `GET /me` + `GET /me/miniapps` with the user key. Heading `Xin chào, <display_name>`; grid of miniapp cards (name, description, state): `can_use` → button `Mở miniapp` → `POST /miniapps/{id}/use` → `notify("success", data.message)`, error → `notify("error", data.detail)`. Not member → `Chờ admin thêm bạn vào` (not a button). Empty → "Bạn chưa nhìn thấy miniapp nào. Admin cần cấp quyền hệ thống trước." Loading → skeleton cards; error → inline error with "Thử lại". Cards whose key appears in `diffSnapshots` of a poll are highlighted ~2 s (opacity/outline only). All text via `textContent`.
- [ ] **Step 4: Polling** — one `setInterval(3000)`: skip if `inFlight > 0`; take `seq = nextSeq()` when the poll starts; on response apply only if `shouldApplyPoll(seq, lastMutationStartSeq)`. After any mutation: refetch, replace baseline snapshot without highlight.
- [ ] **Step 5: Verify** — `.venv/Scripts/python -m uvicorn app:app --port 8000`, open `http://127.0.0.1:8000/`; as user1 after reset: empty state shows; grant via curl with admin key `admin-key-123` (local default) → card appears highlighted within ~3 s as "Chờ admin thêm bạn vào"; add member via curl → button appears; click → success notice. Stop the server. Run `node --test tests/` and pytest — all pass.
- [ ] **Step 6: Commit** `feat: console shell and user view (Cobalt theme)`

### Task 4: Admin view

**Files:**
- Modify: `permapp/static/console.js`, `permapp/static/console.css`, `permapp/static/console.html` (if markup templates live there)

**Interfaces:**
- Consumes: Task 2 `ConsoleLogic`, Task 3 `api`, `beginMutation`/`endMutation`, `notify`, polling.

- [ ] **Step 1: Admin key form** — when Admin is selected and no key in `permconsole.adminKey`: inline panel (not a modal) with password input "Admin key", button "Lưu và tiếp tục"; validate by `GET /admin/users`; 401/403 → inline error "Admin key không đúng", key not saved. Any later admin 401 → remove stored key, show the form, stop admin polling. `Đổi admin key` reopens the form.
- [ ] **Step 2: Table** — `GET /admin/users` + `GET /admin/miniapps`; rows `role === "user"` (username + display name), columns per miniapp (name). Each cell: label `STATE_LABEL[state]` styled by state, and two switches (`<button role="switch" aria-checked>`) `Quyền hệ thống` and `Thành viên`. Table heads in sentence case, body face.
- [ ] **Step 3: Switch actions** — system on → `POST /admin/system-access {username, miniapp_id}`; off → `DELETE /admin/system-access/{u}/{m}`; member on → `POST /admin/miniapps/{m}/members {username}`; off → `DELETE /admin/miniapps/{m}/members/{u}`. Switch disabled while its request runs. Error (e.g. 409) → `notify("error", data.detail)`. Always refetch after; the switch reflects the server.
- [ ] **Step 4: Reset** — `Reset dữ liệu` turns into `Xác nhận reset` + `Huỷ` for 5 s; confirm → `POST /admin/reset` → `notify("success", "Đã đưa dữ liệu về trạng thái ban đầu")` → refetch.
- [ ] **Step 5: States** — loading skeleton rows; error inline with "Thử lại"; poll diff highlights changed cells.
- [ ] **Step 6: Verify in browser** (local, admin key `admin-key-123`): wrong key rejected; member switch with no system access → 409 notice, switch back off; system on → "Chỉ nhìn thấy"; member on → "Dùng được"; system off → both off; grant via curl in another shell → cell highlighted within ~3 s; double-click a switch → one request; reset clears all. Switch to user1 and back — role remembered after reload.
- [ ] **Step 7: Commit** `feat: console admin view`

### Task 5: Hallmark sweep, README

**Files:**
- Modify: `permapp/static/console.css`/`.html`/`.js` (fixes only), `README.md`

- [ ] **Step 1: Lint** — `node $HM/sloplint.mjs permapp/static/console.html permapp/static/console.css --genre modern-minimal --scope app --render`. Fix every FAIL; fix or waive (in the stamp block) every REFLEX; re-run until clean.
- [ ] **Step 2: README** — replace "Trang `/` hiển thị trạng thái quyền hiện tại" with a short "Giao diện demo" section: `/` = console (Admin / user1 / user2, admin key nhập một lần), `/status` = bảng trạng thái chỉ đọc.
- [ ] **Step 3: Run** pytest and `node --test tests/` — all pass.
- [ ] **Step 4: Commit** `chore: Hallmark sweep and README for console`

### Task 6: Deploy and production check

- [ ] **Step 1:** Preview deploy first: `npx vercel --yes`; curl the preview URL for `/health`, `/`, `/static/console.js`, `/static/console.css` (preview URLs may need Deployment Protection bypass; if blocked, inspect `npx vercel build` output for `permapp/static`). Then, with the user's go-ahead, merge to `main`, push, `npx vercel --prod --yes`.
- [ ] **Step 2:** `curl -s -o /dev/null -w "%{http_code} %{content_type}\n"` on `/`, `/status`, `/static/console.js`, `/static/console.css` of `https://permission-test-api-jvd4.vercel.app` — Expected: `200` each with html/js/css types (proves the static files ship in the Vercel bundle).
- [ ] **Step 3:** The user opens the production URL, enters the real admin key, grants system access then membership for user1/leave, opens the miniapp as user1, then resets — and reports the result. Not done until they confirm.
