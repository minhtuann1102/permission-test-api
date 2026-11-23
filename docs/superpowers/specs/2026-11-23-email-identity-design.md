# Email Identity + Ticket Processing Agent — Design (short)

## Intent
Real process: a user files a ManageEngine ticket with a leader's approval attached; an admin
processes it. The user's existing flow already fetches tickets. This change lets the Copilot Studio
agent do the **processing**: take the ticket data (ticket id, requester email, miniapp, approval
status), map the email to an account in the Permission Test API, confirm with the admin, grant the
two tiers, verify, and return a result the flow can write back to the ticket. Identity is **mocked
by email** (no real Microsoft account yet).

## Goals
- The API knows each user's email and can find a user by email (case-insensitive, trimmed).
- The agent guide (`docs/copilot-studio-agent-setup.md`) becomes complete for this flow: input
  contract, tools, instructions, human confirmation, output contract, test scenarios.

## Non-goals
- Fetching tickets from ManageEngine (the user's own flow does it).
- Real Microsoft identity, verifying uploaded evidence (separate AI appraisal project).
- Changing the two-tier rules.

## Anti-goals
- The agent guessing who an email belongs to: the API decides; unknown email → stop.
- Granting without an explicit admin "yes", or when the ticket is not approved.

## Approaches
- **A. Email in the API + `FindUserByEmail` (chosen):** the system resolves identity; swapping to
  real Microsoft accounts later only changes where the email comes from.
- B. Email → username table in the agent's instructions: no code, but the AI can mis-map and the
  API cannot reject an unknown email. Rejected.

## Decided
- `users.email` column. Seed: `admin@demo.local`, `user1@demo.local`, `user2@demo.local`.
  Existing databases (Neon) get the column added at startup if missing, and seed users get their
  seed email filled when empty. `POST /admin/reset` restores seed emails.
- `GET /admin/users` items and `GET /me` include `email`.
- New `GET /admin/users/by-email?email=` (operationId `FindUserByEmail`, admin only) → the same
  shape as a `/admin/users` item; unknown email → `404 USER_NOT_FOUND`; missing/blank email → 422.
- Swagger documents the new operation and the `email` field; README endpoint list updated.
- Demo UI shows the email under each user's name (admin grid) and in the user view's subline.
- Agent guide rewritten around the ticket flow:
  - **Input contract** (what the flow/admin gives the agent): ticket id, requester email, miniapp
    (name or id), requested level (`dùng` = both tiers, `nhìn thấy` = tier 1 only), approval
    status and approver.
  - **Processing:** stop if not approved → `FindUserByEmail` (404 → stop) → resolve miniapp id →
    `CheckAccess` → summarise and ask the admin "Cấp …?" → only on yes: tier 1, then tier 2 if
    `dùng` → `CheckAccess` → output.
  - **Output contract:** a fixed text block (status ĐÃ CẤP / KHÔNG CẦN CẤP / TỪ CHỐI / CẦN BỔ SUNG,
    ticket, user, miniapp, final state, reason) for the flow to write back to the ticket.

## Left to the builder
- Column type/length, exact migration code (must work on SQLite and Postgres).
- Wording of the guide beyond the contracts above.
