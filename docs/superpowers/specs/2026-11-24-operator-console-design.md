# Operator Console (Phân quyền miniapp + Đánh giá) — Design

## Intent
The two mock systems behind this API should look and behave like the real software a
technician uses when working a ticket **without** the agent: pick a person, pick what to change,
confirm, see the change logged. Today the admin view at `/` is a users × miniapps grid of switches,
and the appraisal mock (Đánh giá) only has a read-only HTML table at `/reviews`. The user said the
grid is "not how it works in real life" and asked for:

- miniapp permissions as a form: **type/pick a user → pick permissions from a dropdown (several at
  once) → Grant**, with a result per permission;
- an equally real operator screen for the appraisal mock, operated by hand;
- **a change log shown after every change**, whether the change was made by hand or by the agent.

Real systems are not told about SDP tickets: the technician reads the ticket in SDP and then works
in the system. So **no ticket number anywhere in either system**, including the review API, which
currently requires one.

## Goals
- Admin screen **Phân quyền miniapp**: user picker, multi-select permission dropdown, one Grant
  button, per-permission results, revoke from the user's current permissions, live change log.
- Admin screen **Đánh giá**: tab *Phiếu đánh giá* (pick an employee → their forms → actions) and
  tab *Kỳ đánh giá* (periods table → actions, create period, upload HQCV results), live change log.
- Every successful change (permissions and reviews, from the console or the agent) writes one log
  row with time, **who did it** (console = "Thao tác tay", otherwise "Agent"), what, and
  before → after. The log panel updates every 3 s and highlights new rows.
- The review API no longer requires, validates, or stores a ticket.

## Non-goals
- Real authentication, per-operator identity, or user/miniapp CRUD.
- Changing any eligibility or appraisal rule. The same service functions enforce them.
- Logging refused attempts (4xx). Refusals show in the result area of the screen only; the log is
  a record of **changes**. (Builder/our call; the mockup showed a "Bị chặn" row, the user's wording
  was "log after each change".)
- New operations for the Copilot Studio agent. The swagger loses the `ticket` fields and nothing else
  changes for the agent.

## Anti-goals
- The console writing to the database or applying rules itself. It calls API endpoints that go
  through `permapp/service.py` / `permapp/reviews.py`, so a refusal reads exactly as it would for
  the agent.
- Breaking the deployed agent: old tool definitions that still send `ticket` must keep working.
- A log that only records console actions. Agent changes must appear too; that is the point of
  watching the agent work.

## Constraints
- Same FastAPI app on Vercel, SQLite locally / Neon Postgres in production, no build step, vanilla
  JS, the existing Cobalt look (`tokens.css`, `base.css`, `console.css`) and Hallmark conventions.
- Production database already has `review_log.ticket NOT NULL`: schema changes are additive only
  (new tables / `LATE_COLUMNS`), no column drops.

## Approaches
1. **Rebuild `/` on the current stack, plus small server additions** — **chosen by the user.**
   Two admin sections in the existing console; a console-only multi-grant endpoint; a permission
   log table; an actor header; ticket removed from the review API. Reuses polling, highlighting,
   admin-key storage, and the deploy.
2. Same screens, but the browser calls the existing single-grant endpoints one by one. Rejected:
   "Sử dụng" would log as two rows, and a dropped connection leaves a half-applied grant set.
3. React/Vite frontend. Rejected: adds a build step on Vercel and rewrites screens that work.

## Decisions

### Who did it (actor)
- The console sends header `X-Client: console` on every request. Any write without it is logged
  as actor `agent` (curl and Swagger testers count as agent; acceptable for a mock).
- Stored values `console` / `agent`; the UI shows *Thao tác tay* / *Agent*.

### Permission log (new)
- New table `permission_log(id, at, actor, action, username, miniapp_id, before, after, detail)`.
  `before`/`after` are levels: `none`, `see`, `use`, or the LMS role (`learner`, `instructor`).
  `action` ∈ `Grant`, `ChangeRole`, `RevokeUse`, `RevokeAll`.
- Written inside the same transaction as the change, in `service.py`, so agent calls through the
  existing endpoints are logged too. No row when nothing changed (`already_granted`, `revoked: false`).
- `GET /admin/permission-log?username=` (admin key): latest 200 rows, newest first. Console-only,
  not added to swagger.
- `POST /admin/reset` clears it.

### Review log
- Add column `actor` to `review_log` via `LATE_COLUMNS` (existing rows → `agent`). The `ticket`
  column stays in the schema and is written as `""`. Responses no longer include `ticket`.
- `GET /admin/reviews/log` drops the `ticket` filter and gains an optional `target` filter
  (period, form or goal id). `ListReviewLog` in swagger changes to match.

### Removing the ticket from the review API
- `_ticket()` and `TICKET_REQUIRED` go away. Request bodies drop `ticket`. Pydantic ignores
  unknown fields, so an agent still sending `ticket` gets 200. `DELETE /admin/reviews/goals/{id}`
  ignores a `ticket` query parameter.
- Swagger: remove every `ticket` property, `required` entry and `TICKET_RULE` text.
- `docs/reviews.md`, `README.md`: remove the ticket rule and the ticket in examples; describe the
  actor column.
- `tests/test_reviews.py::test_every_write_needs_a_ticket` is replaced by a test that writes
  without a ticket succeed and that a stray `ticket` is ignored.

### Multi-grant endpoint (console-only, not in swagger)
`POST /admin/users/{username}/grants`, body `{"grants": [{"miniapp_id": "expense", "level": "use"},
{"miniapp_id": "lms", "level": "instructor"}]}`.
- `level`: `see` (system access) or `use` (system access then membership) for normal miniapps;
  a role name for miniapps with roles (LMS, always visible: no `see`).
- Each item runs in its **own transaction** in request order; one refusal does not undo the others.
- Response `{"username", "results": [{"miniapp_id", "level", "ok", "changed", "before", "after",
  "code", "detail"}]}`, always 200 for a known user (404 `USER_NOT_FOUND` otherwise). Refusal
  `code`/`detail` are the service's (`NOT_ELIGIBLE`, `INVALID_ROLE`, …).
- `use` on a miniapp the user only sees → one `Grant` row, `see → use`. Picking `see` when the user
  already has `use` is a no-op (`changed: false`): never downgrade *see/use*. LMS roles are not
  levels: picking the other role **changes the role in either direction** (instructor ⇄ learner,
  user-decided), one `ChangeRole` row, same as `AddMiniappMember` does for the agent. In the
  dropdown only the user's current LMS role is disabled "(đang có)".

### Screen: Phân quyền miniapp (admin)
- **Người dùng**: a select/combobox of non-admin users (username, display name, email). Shows
  department · title, resigned badge, and current permissions as chips.
- **Chip ✕ (revoke)** opens a small confirm: for a `use` chip, two choices *Thu hồi quyền dùng (vẫn
  xem được)* → `RemoveMiniappMember`, *Thu hồi hết* → `RevokeSystemAccess`; for a `see` chip,
  *Thu hồi hết*; for an LMS chip, *Gỡ khỏi LMS* → `RemoveMiniappMember`.
- **Quyền cần cấp**: a multi-select dropdown grouped by miniapp (Xem / Sử dụng; LMS: Học viên /
  Giảng viên). Options the user already has, or (for Xem) covered by Sử dụng, are shown disabled
  with "(đang có)". At most one LMS role can be picked at a time. Chosen items appear as removable chips in the field.
- **Cấp N quyền** button (disabled at 0). No separate confirm dialog: the button label states the
  count and the selection is visible. Results render below: ✓ with before → after, or ✕ with the
  service's Vietnamese reason. The selection clears on success items, keeps refused items.
- Section-level **Reset dữ liệu** stays (with its existing confirm).
- The old grid is removed from `/`. `/status` stays as the read-only overview.

### Screen: Đánh giá (admin)
Tab **Phiếu đánh giá**
- **Nhân viên** select (user1, user2, user3; resigned badge). Lists that employee's forms
  (`FindReviewForms?username=`): id, kind, period, status pill, deadline (and max deadline),
  evaluators, goals with weights and a total-weight warning when ≠ 100%.
- Per-form actions, each opening a dialog with the inputs the API needs and a confirm button:
  *Mở lại phiếu* (optional personal deadline; required and pre-explained when the period is closed),
  *Gia hạn* (date, shows the cap), *Đổi người đánh giá* (old evaluator select when several, new
  email), per goal *Sửa* (title, weight, target) and *Xoá*.
- **Combined reopen (user-approved):** when the form is *Đã phê duyệt* and the action is goal
  edit/delete or evaluator change, the dialog says so and the confirm reads *Mở lại phiếu rồi …*.
  The console calls `ReopenReviewForm` then the action; two log rows. If the second call fails, the
  form stays reopened and the dialog shows the reason (the log shows what happened).
- Buttons for actions the current state forbids (locked period, resigned employee) are still shown
  but disabled, with the reason as a hint, so the operator sees why.

Tab **Kỳ đánh giá**
- Table of periods: id, name, status, deadline, original deadline, max extension date, counts.
- Actions per row: *Gia hạn* (open periods), *Mở lại* (closed), *Tải kết quả HQCV* (closed);
  locked periods show "Đã chốt, không thao tác được".
- *+ Tạo kỳ*: company, kind, year, month/quarter, start date, deadline.
- *Tải kết quả HQCV*: a textarea for pasted rows `email, điểm, xếp loại` (one per line, comma or
  tab), previewed as a table before confirm. The API's all-or-nothing errors show per line.

### Layout and navigation
- Top bar: wordmark, section switch **Phân quyền miniapp | Đánh giá** (admin only), sync status,
  account switcher (Admin, user1, user2, user3) unchanged. User views (user1–3) are unchanged.
- Admin sections: work area on the left, **Nhật ký thay đổi** panel on the right (stacked below on
  narrow screens). Each section's log shows its own system's log.
- Section in the URL (`?role=admin&section=permissions|reviews`), so reload and back/forward keep it.
- Every 3 s: reload the section data and the log. Log rows with an id above the last seen id get
  the existing `is-changed` highlight; the work area re-renders if the data changed (agent edits
  show up), keeping focus and any open dialog.
- Log row: time (local HH:MM:SS), actor badge, one Vietnamese sentence, before → after in muted text.

## Testing
- pytest: permission log rows for grant/role change/revoke via existing endpoints and via the
  multi-grant endpoint; actor from `X-Client`; no row on no-op; partial success; never downgrade;
  reset clears logs; reviews writes without ticket; stray `ticket` ignored; `actor` on review log;
  `target` filter; swagger has no `ticket`.
- node tests (`console-logic.js`): permission level from user data, which dropdown options are
  disabled, new-log-row detection, log sentence formatting, HQCV paste parsing.
- Manual pass in the browser on both sections, plus one agent-style curl write to see the "Agent"
  row appear and highlight.

## Calls made by the designer (not discussed with the user)
- Refused attempts are not logged (log = changes only).
- Actor via `X-Client: console` header; anything else counts as Agent.
- Multi-grant: no extra confirm dialog; one refusal doesn't undo other items.
- Grid removed from `/`; `/status` stays as the overview.
- Disabled-with-reason action buttons on the Đánh giá screen; HQCV upload by pasting rows.
- Review API ignores a stray `ticket` so the deployed agent keeps working.

## Left to the builder
- File split of the frontend (e.g. `console.js` + `permissions.js` + `reviews-ui.js`) and CSS
  organisation, within the Hallmark/Cobalt rules.
- Exact wording of log sentences and dialog copy (Vietnamese, short, matching existing UI copy).
- Whether `/reviews` (read-only page) keeps its log table; it must at least drop the ticket column.
