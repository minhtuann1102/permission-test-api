# Operator Console Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the admin grid at `/` with two real-world operator screens (Phân quyền miniapp, Đánh giá) that show a live change log, and remove the SDP ticket from the review system.

**Architecture:** Backend: a `permission_log` table and an `actor` column on `review_log`, written inside the same transaction as each change in `permapp/service.py` / `permapp/reviews.py`; actor comes from header `X-Client: console`; a console-only multi-grant endpoint. Frontend: `console.js` stays the shell (roles, sections, polling, key, dialogs, log panel) and exposes helpers to two new screen modules; pure rules in `console-logic.js`.

**Tech Stack:** FastAPI, SQLAlchemy Core (SQLite / Neon Postgres), pytest; vanilla JS (no build), `node --test`; Cobalt CSS (`tokens.css`, `base.css`, `console.css`).

**Spec:** `docs/superpowers/specs/2026-11-24-operator-console-design.md`

## Global Constraints

- No ticket number anywhere: not in UI, request bodies, swagger, responses, or docs. Old agent calls sending `ticket` (body or `?ticket=`) must still get 200.
- Schema changes additive only: new table, `LATE_COLUMNS`. `review_log.ticket` stays in the schema and is written as `""`.
- Actor values stored: `console` | `agent`. Header `X-Client: console` → `console`; anything else / missing → `agent`. UI labels: *Thao tác tay* / *Agent*. NULL actor on old rows reads as `agent`.
- Log = successful changes only. No row for no-ops (`already_granted`, `revoked: false`, `NO_CHANGE`) or refusals.
- Levels: `none`, `see`, `use`, or an LMS role (`learner`, `instructor`). Never downgrade `use → see` through a grant. LMS role changes either way.
- Console-only endpoints (`/admin/permission-log`, `/admin/users/{username}/grants`) are not in swagger; `X-Client` never appears in swagger.
- UI copy in Vietnamese, short, matching existing copy. Polling stays 3 s.
- URL: keep `?as=<role>` (spec said `?role=`; corrected to the existing param) and add `&section=permissions|reviews`.
- Run all tests: `.venv/Scripts/python -m pytest -q` and `node --test "tests/*.test.cjs"`.

## Review Focus

1. **Poll while a dialog is open or picks are made**: the dialog, its inputs, the picked permissions and the selected user survive; the log updating must not re-mount the work area. (Task 5 manual check + Task 4 node test for `logChanged` separation.)
2. **Combined reopen + action**: no poll repaint between the two calls; if the second fails, the dialog shows the reason and the log shows the reopen row. (Task 7.)
3. **After Reset dữ liệu**: log ids restart from 1 on SQLite; the log panel must re-baseline, not stay silent. (Task 4 `newLogIds` test.)
4. **Picking Sử dụng then Xem for the same miniapp**: only one option per miniapp is ever sent. (Task 4 `togglePick` test.)
5. **Agent writes while the operator looks at the same user/form**: the work area updates and the new log row highlights, with "Agent" badge. (Task 1 actor test + Task 9 manual check.)

---

### Task 1: Permission log + actor

**Files:**
- Modify: `permapp/db.py` (new table, `reset_db` clears it)
- Modify: `permapp/service.py` (actor kwarg + log writes, `list_permission_log`)
- Modify: `app.py` (actor dependency, pass actor, `GET /admin/permission-log`)
- Modify: `tests/test_swagger.py` (`EXCLUDED` gains `/admin/permission-log`, `/admin/users/{username}/grants`)
- Test: `tests/test_permission_log.py` (new)

**Interfaces:**
- Produces:
  - Table `permission_log(id Integer PK autoincrement, at String(32), actor String(16), action String(16), username String(64), miniapp_id String(64), from_level String(32), to_level String(32), detail String(512))`.
  - `service.level_of(conn, username, app) -> str` (`none|see|use|<role>`; member of a roles app → role; member of a no-roles app → `use`; visible → `see`).
  - `grant_system_access(engine, username, miniapp_id, actor="agent")`, `grant_membership(engine, miniapp_id, username, role="", actor="agent")`, `revoke_system_access(engine, username, miniapp_id, actor="agent")`, `revoke_membership(engine, miniapp_id, username, actor="agent")`: same return shapes as today.
  - `service.list_permission_log(engine, username="") -> {"entries": [ {id, at, actor, action, username, miniapp_id, from_level, to_level, detail} ]}` newest first, max 200.
  - `app.actor(x_client: Optional[str] = Header(None, alias="X-Client")) -> str`.
  - Actions: `Grant` (none/see → higher), `ChangeRole`, `RevokeUse` (membership removed), `RevokeAll` (system access removed).
  - `detail`: one Vietnamese sentence, e.g. `Cấp quyền Sử dụng Kho cho user2`, `Đổi vai trò LMS của user1: Học viên → Giảng viên`, `Thu hồi hết quyền Nghỉ phép của user1`.

- [ ] **Step 1: Write failing tests** in `tests/test_permission_log.py`:
  - `test_grant_via_existing_endpoints_logs_agent`: POST system-access user2/inventory then POST member → 2 rows newest first: `[("Grant","see","use","agent"), ("Grant","none","see","agent")]` as `(action, from_level, to_level, actor)`.
  - `test_console_header_sets_actor`: same POST with headers `{**ADMIN, "X-Client": "console"}` → row actor `console`.
  - `test_no_row_on_noop`: grant system access twice → 1 row; revoke membership user2/leave when not member → 0 new rows.
  - `test_role_change_and_revokes`: user1 LMS add learner → `("Grant","see","learner")`; then instructor → `("ChangeRole","learner","instructor")`; DELETE member → `("RevokeUse","instructor","see")`; user1 leave granted to `use`, then DELETE system-access → `("RevokeAll","use","none")`.
  - `test_refusal_writes_no_row`: user2 lms instructor → 403, log empty.
  - `test_log_filter_and_admin_only`: `?username=user1` filters; user key → 403.
  - `test_reset_clears_permission_log`.
- [ ] **Step 2:** Run `.venv/Scripts/python -m pytest tests/test_permission_log.py -q` → FAIL (404 / import errors).
- [ ] **Step 3:** Implement. Compute `from_level` with `level_of` before the write and `to_level` after, in the same transaction; insert the row only if they differ. Add the dependency to the four write routes and pass `actor=`. Add route `GET /admin/permission-log?username=`. The new table is created by `metadata.create_all` in `_create_schema`; add `delete(permission_log)` in `reset_db`. Add the two console-only paths to `EXCLUDED` in `tests/test_swagger.py` (the grants path is created in Task 2; adding it now is harmless).
- [ ] **Step 4:** Run full pytest → all PASS.
- [ ] **Step 5:** Commit `feat: permission change log with actor`.

### Task 2: Multi-grant endpoint

**Files:**
- Modify: `permapp/service.py` (`grant_permissions`)
- Modify: `app.py` (`GrantItemIn`, `GrantsIn`, `POST /admin/users/{username}/grants`)
- Test: `tests/test_permission_log.py` (append)

**Interfaces:**
- Consumes: Task 1 `level_of`, log insert helper, `actor` dependency.
- Produces: `service.grant_permissions(engine, username, items, actor="agent") -> {"username", "results": [{"miniapp_id", "level", "ok", "changed", "from_level", "to_level", "code", "detail"}]}`; `items` = list of `{"miniapp_id", "level"}`. Unknown user → `ServiceError(404, "USER_NOT_FOUND")`. Bodies: `GrantsIn{grants: List[GrantItemIn{miniapp_id: str, level: str}]}`.
- Per-item errors (in result, not raised): service codes (`NOT_ELIGIBLE`, `MINIAPP_NOT_FOUND`, `INVALID_ROLE`) and new `INVALID_LEVEL` (422 semantics, detail `Mức quyền '<x>' không hợp lệ cho <app> (chọn: ...)`). Valid levels: apps without roles `see|use`; apps with roles → one of `app.roles`.

- [ ] **Step 1: Write failing tests:**
  - `test_grants_use_is_one_row`: user2 `[{"miniapp_id":"expense","level":"use"}]` → result `ok, changed, from_level "none", to_level "use"`; log has exactly 1 new row `("Grant","none","use")`; `/admin/check` user2/expense `can_use` true.
  - `test_grants_partial_success`: user2 `[expense use, lms instructor, inventory see]` → oks `[True, False, True]`, item 2 `code == "NOT_ELIGIBLE"`; expense and inventory granted.
  - `test_grants_never_downgrade`: user1 leave use (grant first), then `leave see` → `ok True, changed False`, still `use`, no row.
  - `test_grants_lms_role_both_ways`: user1 lms instructor then learner → second result `from_level "instructor", to_level "learner"`, row `ChangeRole`.
  - `test_grants_invalid_level_and_unknown_user`: `{"miniapp_id":"leave","level":"learner"}` → `code "INVALID_LEVEL"`; unknown user → 404 `USER_NOT_FOUND`.
  - `test_grants_console_actor`: header `X-Client: console` → row actor `console`.
- [ ] **Step 2:** Run → FAIL.
- [ ] **Step 3:** Implement; each item in its own `engine.begin()`; `use` = system access (if needed) + membership in one transaction, eligibility checked once with role `""`; roles app level = `grant_membership` logic. Catch `ServiceError` per item into the result.
- [ ] **Step 4:** Full pytest PASS.
- [ ] **Step 5:** Commit `feat: console multi-grant endpoint`.

### Task 3: Remove the ticket from the review system, add actor

**Files:**
- Modify: `permapp/db.py` (`LATE_COLUMNS` += `("review_log", "actor", "VARCHAR(16)")`, column on table)
- Modify: `permapp/reviews.py` (drop `_ticket`, `TICKET_REQUIRED`; every write takes `actor="agent"`; `_log(conn, actor, action, target, detail)` writes `ticket=""`; `list_log(engine, target="")`; output rows without `ticket`, `actor` defaulting to `agent`)
- Modify: `app.py` (bodies drop `ticket`; routes pass `actor`; `DELETE goals` drops `ticket` query; `/admin/reviews/log?target=`; `/reviews` page drops ticket column, adds actor column)
- Modify: `permapp/swagger.py` (remove all `ticket` properties/required entries, `TICKET_RULE`, `TICKET_REQUIRED` mentions; `ReviewLogEntry` gets `actor`, loses `ticket`; `ListReviewLog` param `target`)
- Modify: `tests/test_reviews.py`, `tests/test_swagger.py`
- Modify: `docs/reviews.md` (rule list, scenario table, curl examples: no ticket; describe actor)

**Interfaces:**
- Produces: `reviews.create_period(engine, company, kind, year, number, start_date, deadline, actor="agent")`, `reopen_period(engine, period_id, deadline, actor=...)`, `extend_period(engine, period_id, deadline, actor=...)`, `import_results(engine, period_id, rows, actor=...)`, `reopen_form(engine, form_id, deadline, actor=...)`, `extend_form(engine, form_id, deadline, actor=...)`, `update_evaluator(engine, form_id, new_email, old_email, actor=...)`, `update_goal(engine, goal_id, title, weight, target, actor=...)`, `delete_goal(engine, goal_id, actor=...)`, `list_log(engine, target="") -> {"entries": [{id, at, actor, action, target, detail}]}`.

- [ ] **Step 1: Update tests:**
  - Replace `test_every_write_needs_a_ticket` with `test_writes_need_no_ticket`: DELETE `G-1001-3` with no params → 200 `DONE`; POST extend with body `{"deadline": "2026-12-05", "ticket": "abc"}` → 200 (stray ticket ignored).
  - Line ~222: log check becomes `client.get(f"{R}/log", params={"target": "G-1005-4"})` → 1 entry, `"ticket" not in entry`, `entry["actor"] == "agent"`.
  - New `test_review_actor_from_header`: extend with `X-Client: console` → newest log entry actor `console`.
  - `tests/test_swagger.py`: new `test_no_ticket_or_client_header_in_spec`: `"ticket"` not in `json.dumps(spec).lower()` and `"x-client"` not in it.
  - Existing tests that still send `"ticket"` stay as they are (proves backwards compatibility).
- [ ] **Step 2:** Run pytest → new tests FAIL.
- [ ] **Step 3:** Implement the module/app/swagger/docs changes above. `README.md` review paragraph: drop "Mọi thao tác ghi đều phải có số ticket SDP".
- [ ] **Step 4:** Full pytest PASS; `grep -rn -i ticket permapp/reviews.py permapp/swagger.py` shows only the `ticket=""` write and no API text.
- [ ] **Step 5:** Commit `feat: review system without ticket; log who made each change`.

### Task 4: Pure console logic

**Files:**
- Modify: `permapp/static/console-logic.js`
- Modify: `tests/console-logic.test.cjs` (delete `adminSnapshot` test and the function; keep `cellState`, `cellLabel`, `memberRole`, `userSnapshot`, `diffSnapshots` which the user view still uses)

**Interfaces (all on `window.ConsoleLogic`):**
- `pickSection(search) -> "permissions" | "reviews"` (`&section=` wins, default `permissions`).
- `levelOf(user, app) -> "none"|"see"|"use"|role` (same meaning as server `level_of`).
- `LEVEL_LABEL = {none: "Chưa có quyền", see: "Xem", use: "Sử dụng", learner: "Học viên", instructor: "Giảng viên"}`; `levelLabel(l)`.
- `grantOptions(user, miniapps) -> [{miniapp_id, name, options: [{level, label, disabled, note}]}]`: no-roles app: `see` disabled when current is `see` or `use` (note `đang có`), `use` disabled when `use`; roles app (LMS): one option per role, only the current role disabled; no `see` option for always-visible apps.
- `togglePick(picks, miniapp_id, level) -> picks` where `picks` is `{miniapp_id: level}`: picking a level for an app replaces any other level of that app; picking the same one again removes it.
- `pickList(picks, miniapps) -> [{miniapp_id, level}]` in miniapp order.
- `newLogIds(entries, lastSeenId) -> {ids: number[], lastSeenId: number}`: `lastSeenId === null` → no ids (first load), baseline = max id; if max id < lastSeenId (after reset) → no ids, re-baseline to max (0 when empty); else ids > lastSeenId.
- `permLogText(entry, appNames) -> string` (falls back to `entry.detail`); `actorLabel(a) -> "Thao tác tay" | "Agent"`.
- `parseResultRows(text) -> {rows: [{email, score, grade}], errors: string[]}`: one row per non-blank line, split on tab or comma, score integer, grade upper-cased; errors like `dòng 2: thiếu điểm`.

- [ ] **Step 1: Write failing node tests** with exact assertions, e.g.:
  - `grantOptions` for user2 (inventory `see`, leave `use`, lms member learner): inventory `see` disabled, `use` enabled; leave both disabled; lms `learner` disabled, `instructor` enabled; lms has no `see`.
  - `togglePick({}, "kho","see")` → `{kho:"see"}`; then `("kho","use")` → `{kho:"use"}`; then `("kho","use")` → `{}`.
  - `newLogIds([{id:5},{id:4}], null)` → `{ids:[], lastSeenId:5}`; `newLogIds([{id:7},{id:6},{id:5}], 5)` → `{ids:[7,6], lastSeenId:7}`; `newLogIds([{id:2},{id:1}], 9)` → `{ids:[], lastSeenId:2}`; `newLogIds([], 9)` → `{ids:[], lastSeenId:0}`.
  - `parseResultRows("a@x.vn, 90, a\n\nb@x.vn\t75\tB\nc@x.vn, x, C")` → 2 rows (`grade "A"`), errors `["dòng 4: điểm phải là số nguyên"]` (line numbers count raw lines).
  - `pickSection("?as=admin&section=reviews")` → `reviews`; `pickSection("?as=admin")` → `permissions`.
- [ ] **Step 2:** `node --test "tests/*.test.cjs"` → FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** node tests PASS.
- [ ] **Step 5:** Commit `feat: console logic for grants, log highlight, HQCV paste`.

### Task 5: Console shell (sections, log panel, dialogs), grid removed

**Files:**
- Modify: `permapp/static/console.html` (section nav in top bar; `<script defer>` for `perm-screen.js`, `review-screen.js` before `console.js`)
- Modify: `permapp/static/console.js`
- Modify: `permapp/static/console.css` (section nav, two-column admin layout, log panel, dialog, chips, multiselect, tabs, pills; responsive stack under 48rem; remove grid/switch styles no longer used)
- Create: `permapp/static/perm-screen.js` (stub that renders a heading, filled in Task 6)
- Create: `permapp/static/review-screen.js` (stub, filled in Tasks 7–8)

**Interfaces:**
- Shell exposes `window.ConsoleShell = { h, icon, api, notify, mutate, reload, openDialog, closeDialog, ui }`:
  - `api(path, opts)` always sends `X-Client: console` and the current key.
  - `mutate(fn) -> Promise`: `beginMutation()` before `fn()` (which returns a promise), `endMutation()` after it settles, then `reload()`. Multi-call actions (combined reopen) run inside one `mutate`.
  - `reload() -> Promise` reloads the current section now.
  - `openDialog({title, body: Node, confirmText, danger?, onConfirm: () => Promise<{ok, message}|void>})` mounts a native `<dialog>` appended to `document.body` (outside `#app`), traps focus, Esc/Huỷ closes; while `onConfirm` runs the confirm button is busy; a returned `{ok:false, message}` shows inside the dialog and keeps it open.
  - `ui`: a per-section object the screens use to keep UI state (selected user, picks, active tab) across re-renders.
- Screens register `window.PermScreen = { fetch(api) -> Promise<{ok, data, log}>, render(container, data, shell) }` and `window.ReviewScreen` the same. `data` excludes the log; `log` is `{entries}`.
- Admin layout: `#app` holds head (title, Đổi admin key, Reset dữ liệu) + `.workspace` with `.work` (screen render target) and `.logpanel` (shell-owned).
- Load/poll rules:
  - Work area re-renders only when `JSON.stringify(data)` changed; the log panel re-renders only when the log signature changed. Neither touches an open dialog.
  - Highlight: `L.newLogIds` with a baseline per section (`state.logSeen.permissions`, `state.logSeen.reviews`), reset to `null` on section switch and on role switch.
  - Section switch writes `?as=admin&section=…` (pushState) and loads that section; `popstate` restores it.
- Log panel row: time `HH:MM:SS` local, actor badge (`Thao tác tay` / `Agent`), sentence (`L.permLogText` or review `detail`), from → to muted; `is-changed` on new ids; heading *Nhật ký thay đổi*; empty state *Chưa có thay đổi nào.*
- Delete grid code: `renderAdmin`, `switchButton`, `roleSelect`, `setRole`, `toggle`, `mutateCell`, `fetchAdmin`, `state.cellError`, `L.adminSnapshot` usage. User views (user1–3) unchanged. Reset now also re-baselines logs (handled by `newLogIds`).

- [ ] **Step 1:** Implement the shell and stubs.
- [ ] **Step 2:** Run node + pytest → PASS (no behaviour change on server).
- [ ] **Step 3:** Manual check: `uvicorn app:app --port 8765`, open `/?as=admin`; switch sections (URL changes, back button works); curl a grant without `X-Client` → log row with *Agent* appears and highlights within 3 s; open a dialog from the stub (temporary button is fine) and wait 6 s while a curl write happens → dialog and its input value survive.
- [ ] **Step 4:** Commit `feat: console shell with sections, live log panel and dialogs`.

### Task 6: Phân quyền miniapp screen

**Files:**
- Modify: `permapp/static/perm-screen.js`, `permapp/static/console.css`

**Interfaces:**
- Consumes: `ConsoleShell`, `L.levelOf`, `L.grantOptions`, `L.togglePick`, `L.pickList`, `L.levelLabel`, `L.errorText`; endpoints `/admin/users`, `/admin/miniapps`, `/admin/permission-log`, `/admin/eligibility`, `POST /admin/users/{u}/grants`, `DELETE /admin/system-access/{u}/{m}`, `DELETE /admin/miniapps/{m}/members/{u}`.

Behaviour:
- **Người dùng** `<select>` of `role === "user"` accounts (`display_name · username · email`); `ui.user` persists. Below: org line, *Đã nghỉ việc* badge, current permissions as chips `"<App> · <level label>"` with ✕ (button, aria-label `Thu hồi …`).
- Chip ✕ → `openDialog`: `use` chip on no-roles app: two radio choices *Thu hồi quyền dùng (vẫn xem được)* (→ DELETE member) and *Thu hồi hết* (→ DELETE system-access), default the first; `see` chip: *Thu hồi hết*; LMS chip: *Gỡ khỏi LMS* (→ DELETE member).
- **Quyền cần cấp**: a disclosure button showing picked chips + `▾`, opening a listbox panel grouped by miniapp (checkbox-style options from `L.grantOptions`, disabled ones show `(đang có)`); keyboard: Tab into it, Space toggles, Esc closes. `ui.picks` persists; changing user clears picks.
- **Cấp N quyền** (primary, disabled at 0) → fetch `/admin/eligibility` per pick (parallel) → `openDialog` titled *Xác nhận cấp quyền*: user name + email, one line per pick `<App>: <from> → <to>` with ✓ first reason / ✕ first reason; confirm *Xác nhận cấp N quyền* → POST grants inside `mutate`.
- Results block under the form: one line per result, ✓ with from → to (or *đã có sẵn, không đổi* when `changed` false), ✕ with `detail`. Successful picks are removed from `ui.picks`; refused ones stay.
- Empty state when no users.

- [ ] **Step 1:** Implement.
- [ ] **Step 2:** Manual check at 1280 px and 375 px: grant user2 *Chi phí · Sử dụng* + *LMS · Giảng viên* → dialog shows ✓ and ✕; after confirm one success line + one refusal line, log gets 1 row; revoke via chip both ways; select user1 LMS Giảng viên when learner → *ChangeRole* row.
- [ ] **Step 3:** node + pytest PASS. Commit `feat: permissions screen (pick user, pick permissions, confirm, log)`.

### Task 7: Đánh giá screen — tab Phiếu đánh giá

**Files:**
- Modify: `permapp/static/review-screen.js`, `permapp/static/console.css`

**Interfaces:**
- Consumes: `ConsoleShell`; endpoints `/admin/users`, `/admin/reviews/forms`, `/admin/reviews/periods`, `/admin/reviews/log`, and the write endpoints. `fetch` loads users, all forms, all periods, log.

Behaviour:
- Tabs *Phiếu đánh giá* | *Kỳ đánh giá* (`role="tablist"`), `ui.tab` persists.
- **Nhân viên** `<select>` (user1–3, resigned badge); `ui.employee` persists. Form cards: id, kind label, period name, status pill, deadline + *gia hạn tối đa*, evaluators (relation label), goals table (id, title, weight, target) with total-weight warning when `!weight_ok`.
- Actions per form: *Mở lại phiếu*, *Gia hạn*, *Đổi người đánh giá*; per goal *Sửa*, *Xoá*. Disabled with a hint when: employee resigned, period locked, form locked (`Kỳ đã chốt`, `Nhân viên đã nghỉ việc`, `Phiếu đã chốt`); *Gia hạn* also disabled for APPROVED forms (hint: dùng Mở lại phiếu).
- Dialog inputs: Mở lại (date, required and explained when `period_status === "CLOSED"` and no personal deadline); Gia hạn (date, min = tomorrow of current, max = `max_deadline` shown as text); Đổi người đánh giá (select of current evaluators when > 1, new email input); Sửa mục tiêu (title, weight 1–100, target prefilled); Xoá (text only).
- **Combined reopen** when `status === "APPROVED"` and action is goal edit/delete or evaluator change: the dialog shows *Phiếu đã phê duyệt: hệ thống sẽ mở lại phiếu trước.* and confirm reads *Mở lại phiếu rồi xoá* / *… rồi sửa* / *… rồi đổi*; `onConfirm` runs both calls inside one `mutate`; if the second fails return `{ok:false, message: detail}` (dialog stays, says the form was reopened).
- After success: `notify("success", message from API)`.

- [ ] **Step 1:** Implement.
- [ ] **Step 2:** Manual check: scenarios 7, 8, 9, 10, 13, 14, 16 from `docs/reviews.md` section 5 by hand; scenario 8 gives 2 log rows; scenario 14 buttons disabled with hint.
- [ ] **Step 3:** node + pytest PASS. Commit `feat: review forms tab with actions, combined reopen and log`.

### Task 8: Đánh giá screen — tab Kỳ đánh giá

**Files:**
- Modify: `permapp/static/review-screen.js`, `permapp/static/console.css`

Behaviour:
- Table: id + name, status pill, start, deadline, original deadline, `max_deadline`, `extension_count`, `form_count`, `result_count`, actions. OPEN → *Gia hạn*; CLOSED → *Mở lại*, *Tải kết quả HQCV*; LOCKED → muted *Đã chốt, không thao tác được*.
- *+ Tạo kỳ* dialog: company (text), kind select (KPI tháng/quý/năm, Đánh giá 360), year (number, default current year), month/quarter select shown only for KPI_MONTH/KPI_QUARTER, start date, deadline.
- *Tải kết quả HQCV* dialog: textarea (placeholder `email, điểm, xếp loại` one per line), live preview table from `L.parseResultRows`, parse errors listed; confirm disabled while errors or 0 rows; server `INVALID_ROWS` detail shown in the dialog.

- [ ] **Step 1:** Implement.
- [ ] **Step 2:** Manual check: scenarios 1, 2, 3, 5, 6, 12, 15 by hand.
- [ ] **Step 3:** node + pytest PASS. Commit `feat: review periods tab (extend, reopen, create, HQCV upload)`.

### Task 9: Docs and final pass

**Files:**
- Modify: `README.md` (*Giao diện demo*: two admin screens, the flow, live log with actor; drop grid and switch wording; review section without ticket)
- Modify: `docs/copilot-studio-agent-setup.md` (expected-result column: replace grid wording such as "Ô user1 × Nghỉ phép tô sáng, thành **Dùng được**" / "Ô về **Không có quyền**" with the log row and `/status` state, e.g. "Nhật ký có dòng *Agent · Cấp quyền Sử dụng Nghỉ phép cho user1*")

- [ ] **Step 1:** Update docs.
- [ ] **Step 2:** Full verification: pytest, node tests, manual pass of both sections as admin plus one user view; a curl write without `X-Client` while the operator watches the same user → work area updates, *Agent* row highlights.
- [ ] **Step 3:** Commit `docs: operator console and change log`.
