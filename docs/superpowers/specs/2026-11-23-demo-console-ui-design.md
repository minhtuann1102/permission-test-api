# Demo Console UI — Design

## Intent
A web screen for demoing the two-tier permission flow **without the Copilot Studio agent**,
for both admin and users, on top of the existing Permission Test API. The audience watches a
demo (projector/screen share); the UI must look like a real, enterprise-grade product. When the
agent acts in parallel, the UI reflects its changes.

## Goals
- Admin can do every admin action by hand: grant/revoke system access (tier 1), add/remove
  miniapp members (tier 2), reset data.
- A user (user1, user2) sees the miniapps visible to them and can "open" (use) the ones they are
  members of.
- Fast role switching in one browser tab for the demo.
- Changes made by the agent show up without a manual reload.

## Non-goals
- Not for real production use: no login, sessions, user/miniapp CRUD, or per-person security.
- No API log / developer panel on screen (removed at the user's request).
- No changes to the API's rules or responses.

## Anti-goals
- A UI that bypasses the API rules (e.g. writing to the DB directly). It must call the same
  endpoints as the agent, so the 409 `SYSTEM_ACCESS_REQUIRED` rule shows up exactly as for the agent.
- The real admin key committed to the repo or embedded in the page.

## Constraints
- Same FastAPI app on Vercel; no build step, no frontend framework.
- The production admin key is secret; user keys (`user1-key-123`, `user2-key-123`) are public.

## Approaches
- **A. Static HTML page served by FastAPI, vanilla JS calling the existing API** — **chosen**:
  lightest, no build, the UI and the agent share one API.
- B. Server-rendered HTML forms — rejected: needs a cookie/session for the key plus duplicate routes.
- C. Separate React/Vite frontend — rejected: a build step and maybe a second deploy for a demo page.

Layout: **top-bar account switcher** (one role at a time, large and clear on a projector),
chosen over a split screen.
Visual direction: Hallmark theme **Cobalt** (cool near-white paper, blue-grey ink and hairlines,
Familjen Grotesk + IBM Plex Sans, one cobalt signal), chosen over Dusk, Ultraviolet,
Blueprint and Coral. As an app screen, only the palette, type, radius and surfaces come from the
theme; none of its decorative devices do.

## Decided
- **Route:** the new UI is at `/`; the old read-only status table moves to `/status`.
- **Top bar:** product name, a live-refresh indicator, a segmented switcher Admin / user1 / user2.
  The selected role is remembered per browser.
- **Keys:** user keys are pre-filled. The first time Admin is chosen, the page asks for the admin
  key once and keeps it in browser storage, with a "Đổi admin key" action. A wrong key shows a
  clear error and asks again.
- **Admin screen:** a users × miniapps table, rows = accounts with role `user` only (the admin
  account returned by `/admin/users` is not listed). Each cell has a status label (Không có quyền /
  Chỉ nhìn thấy / Dùng được) and two switches: "Quyền hệ thống" and "Thành viên".
  The member switch is not disabled without system access: turning it on calls the API, and the
  409 message is shown as a notice, which demonstrates the rule. Revoking system access also
  clears membership (existing API behaviour). Plus a "Reset dữ liệu" action with confirmation.
- **User screen:** a greeting with the display name, and cards for the visible miniapps. A member
  gets a "Mở miniapp" button (calls `POST /miniapps/{id}/use`, shows the success message).
  A non-member gets a "Chờ admin thêm bạn vào" state. Miniapps without system access are not shown.
- **Live refresh:** poll every ~3 s. A cell or card that changed since the last poll (e.g. by the
  agent) is briefly highlighted.
- **Clicks vs polling:** while a request from the UI is in flight, polls are skipped; right after
  each request (success or error) the UI refetches from the server instead of trusting its own
  optimistic state, so a 409 puts the switch back off and a revoked system access also shows
  membership off. Only changes the UI did not cause itself are highlighted.
- **Visual rules (Hallmark Floor, differs from the earlier mockup):** no emoji icons for miniapps,
  no uppercase letter-spaced table headers, no decorative "live" dot; the refresh indicator is
  plain text. Fonts Familjen Grotesk + IBM Plex Sans both ship the Vietnamese subset (checked).
  Theme stamped as a manual pick (`theme: cobalt (by request)`), not a dealt one.
- **States:** every data region has loading, empty, error and full states.
- **Language:** Vietnamese.

## Left to the builder
- Exact spacing, type scale and component styling within the Cobalt theme and the Hallmark Floor
  (app-screen scope, sloplint `--scope app` clean).
- How the HTML/CSS/JS file is stored and served, as long as it ships in the Vercel bundle
  (verify on production after deploy).
- Keep `/` and `/status` out of `swagger.json`; update tests and README for the route change.

## Done means
1. Tests pass; the page is exercised in a browser against local uvicorn (SQLite): switch roles,
   trigger the 409, use a miniapp, reset.
2. Deployed to production; the user enters the real admin key in the new UI and grants system
   access, then membership, uses the miniapp as user1, then resets — and reports it worked.
   (This also verifies the production admin write path, which is still untested.)
