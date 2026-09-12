# UX Scenarios

<!-- Managed with super-ux (scenario-format v1). Update in the same change as any user-facing behavior change. -->

Source of truth for all user-facing behavior of CheckMyData.ai. Built by an
Init (existing-code) inventory sweep on 2026-07-19 — every entry is reverse-
engineered from shipped code with `file:line` evidence, and every gap the sweep
found is recorded as a `draft` scenario with `Coverage: none yet`. Paths are
relative to `frontend/src/` unless noted. All entries start `draft`; only a
human review moves them to `validated`.

<!-- verification-status:begin -->
### Implemented is not verified

Counted 2026-09-12 — regenerate with `make ux-status`. **Every number below is
counted from the index table, never typed.**

Ages are measured against the stamp above, not against the clock. A block that aged on
its own would turn CI red on a day nobody changed anything, and a gate that fires
without a cause is one people learn to ignore. It goes stale when the *table* changes.

| | |
|---|---|
| Scenarios | **153** |
| Status | draft × 12, implemented × 141 |
| Last verdict | PARTIAL × 2, PASS × 139, no verdict × 12 |
| Verified when | 2026-07-19 × 95, 2026-08-16 × 5, 2026-08-19 × 9, 2026-08-20 × 1, 2026-08-21 × 2, 2026-08-25 × 5, 2026-08-31 × 10, 2026-09-03 × 1, 2026-09-07 × 4, 2026-09-08 × 8, 2026-09-09 × 1, undated × 12 |
| **Verified >30 days ago** | **95 of 153** (oldest 55 days) |
| Never verified (no date) | 12 |
| Referenced from code or tests | **37 of 153** |

*Implemented* says somebody built it. *Verified* says somebody checked it, on a date,
and that date has an age. A reader shown only the first will believe the second — which
is how "100% implemented, 98% PASS" came to be quoted while 110 of the verdicts were
five weeks old and 105 scenarios had no anchor a machine could check them by.

The stale count is a ratchet: it may fall, never rise. Re-auditing a scenario and dating
it is what moves it.
<!-- verification-status:end -->

## Index

| ID | Title | Feature | Persona | Status | Last audit |
|----|-------|---------|---------|--------|------------|
| SCN-001 | First-run onboarding wizard — happy path | onboarding | new-user | implemented | 2026-08-31 PASS |
| SCN-002 | Onboarding — connection test fails, retry/edit | onboarding | new-user | implemented | 2026-07-19 PASS |
| SCN-003 | Onboarding — skip setup / try demo | onboarding | new-user | implemented | 2026-08-20 PASS (seeded, read-only, deduped) |
| SCN-004 | Request project access (non-approved user) | onboarding | new-user | implemented | 2026-07-19 PASS |
| SCN-005 | Register with email + password | auth | new-user | implemented | 2026-08-31 PASS |
| SCN-006 | Log in with email + password | auth | analyst | implemented | 2026-08-31 PASS |
| SCN-007 | Sign in with Google | auth | analyst | implemented | 2026-07-19 PASS |
| SCN-008 | Log out | auth | analyst | implemented | 2026-08-25 PASS |
| SCN-009 | Change password | auth | analyst | implemented | 2026-07-19 PASS |
| SCN-010 | Delete account | auth | analyst | implemented | 2026-07-19 PASS |
| SCN-011 | Session expiry → forced re-login | auth | analyst | implemented | 2026-08-25 PASS |
| SCN-012 | Email verification after registration | auth | new-user | implemented | 2026-08-25 PASS |
| SCN-013 | Forgot / reset password | auth | analyst | implemented | 2026-08-25 PASS |
| SCN-014 | Accept a pending project invite | invites | analyst | implemented | 2026-07-19 PASS |
| SCN-015 | Decline / reject an invite | invites | analyst | implemented | 2026-08-25 PASS (line refs corrected) |
| SCN-016 | Create a project | projects | owner | implemented | 2026-07-19 PASS |
| SCN-017 | Switch between projects (multi-entity) | projects | analyst | implemented | 2026-07-19 PASS |
| SCN-018 | Edit a project | projects | owner | implemented | 2026-07-19 PASS |
| SCN-019 | Delete a project | projects | owner | implemented | 2026-07-19 PASS |
| SCN-020 | Project overview — no project / empty | projects | analyst | implemented | 2026-07-19 PASS |
| SCN-021 | Invite a member & set role | members | owner | implemented | 2026-07-19 PASS |
| SCN-022 | Change a member's role | members | owner | implemented | 2026-07-19 PASS |
| SCN-023 | Remove a member | members | owner | implemented | 2026-07-19 PASS |
| SCN-024 | Resend / revoke a pending invite | members | owner | implemented | 2026-07-19 PASS |
| SCN-025 | Add a DB connection | connections | owner | implemented | 2026-07-19 PASS |
| SCN-026 | Add connection via connection-string autofill | connections | owner | implemented | 2026-07-19 PASS |
| SCN-027 | Add an MCP connection | connections | owner | implemented | 2026-07-19 PASS |
| SCN-028 | Configure an SSH tunnel on a connection | connections | owner | implemented | 2026-07-19 PASS |
| SCN-029 | Toggle read-only mode | connections | owner | implemented | 2026-07-19 PASS |
| SCN-030 | Test a connection | connections | editor | implemented | 2026-07-19 PASS |
| SCN-031 | Edit a connection | connections | owner | implemented | 2026-07-19 PASS |
| SCN-032 | Delete a connection | connections | owner | implemented | 2026-07-19 PASS |
| SCN-033 | Index / re-index a database | connections | editor | implemented | 2026-07-19 PASS |
| SCN-034 | Run code↔DB sync | connections | editor | implemented | 2026-07-19 PASS |
| SCN-035 | Refresh schema cache | connections | editor | implemented | 2026-07-19 PASS |
| SCN-036 | Connection health & reconnect | connections | analyst | implemented | 2026-07-19 PASS |
| SCN-037 | Connections — empty state | connections | owner | implemented | 2026-08-31 PASS |
| SCN-038 | Add an SSH key | ssh-keys | owner | implemented | 2026-07-19 PASS |
| SCN-039 | Delete an SSH key | ssh-keys | owner | implemented | 2026-07-19 PASS |
| SCN-040 | SSH keys — empty state | ssh-keys | owner | implemented | 2026-07-19 PASS |
| SCN-041 | Ask a data question — streaming happy path | chat | analyst | implemented | 2026-08-31 PASS |
| SCN-042 | Quick-ask from project overview | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-043 | Stop / abort a running answer | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-044 | Empty chat + suggestion chips | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-045 | Readiness gate (first-run project) | chat | new-user | implemented | 2026-07-19 PASS |
| SCN-046 | Mid-stream error + retry | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-047 | Knowledge-only chat (no connection) | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-048 | Create / switch / delete chat sessions | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-049 | Resume in-progress session after leaving | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-050 | Pipeline checkpoint — continue/modify/retry | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-051 | Answer a clarification request | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-052 | Rate an answer & report wrong data | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-053 | Save an answer to notes | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-054 | View the agent reasoning panel | chat | analyst | implemented | 2026-08-31 PASS |
| SCN-055 | Step-limit reached → continue analysis | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-056 | Session-continuation (auto-summary) banner | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-057 | View & switch chart type | viz | analyst | implemented | 2026-07-19 PASS |
| SCN-058 | Export a result (CSV / JSON / XLSX) | viz | analyst | implemented | 2026-07-19 PASS |
| SCN-059 | Compound multi-query results | viz | analyst | implemented | 2026-07-19 PASS |
| SCN-060 | Chart render failure → table fallback | viz | analyst | implemented | 2026-07-19 PASS |
| SCN-061 | Browse indexed docs | knowledge | analyst | implemented | 2026-07-19 PASS |
| SCN-062 | Knowledge health & re-index actions | knowledge | editor | implemented | 2026-07-19 PASS |
| SCN-063 | Knowledge freshness warnings | knowledge | analyst | implemented | 2026-07-19 PASS |
| SCN-064 | Nightly sync history | knowledge | owner | implemented | 2026-07-19 PASS |
| SCN-065 | View & filter the insights feed | insights | analyst | implemented | 2026-07-19 PASS |
| SCN-066 | Confirm / dismiss / resolve an insight | insights | analyst | implemented | 2026-07-19 PASS |
| SCN-067 | Browse the metric catalog | insights | analyst | implemented | 2026-07-19 PASS |
| SCN-068 | Saved-queries panel (scopes & empty) | notes | analyst | implemented | 2026-07-19 PASS |
| SCN-069 | Run a saved query | notes | analyst | implemented | 2026-07-19 PASS |
| SCN-070 | Share / unshare a saved query | notes | analyst | implemented | 2026-07-19 PASS |
| SCN-071 | Edit a saved-query comment | notes | analyst | implemented | 2026-07-19 PASS |
| SCN-072 | Delete a saved query | notes | analyst | implemented | 2026-07-19 PASS |
| SCN-073 | View agent learnings | learnings | editor | implemented | 2026-08-31 PASS |
| SCN-074 | Confirm/contradict/edit/deactivate a learning | learnings | editor | implemented | 2026-07-19 PASS |
| SCN-075 | Recompile learnings | learnings | editor | implemented | 2026-07-19 PASS |
| SCN-076 | Clear all learnings | learnings | owner | implemented | 2026-07-19 PASS |
| SCN-077 | Create a custom rule | rules | editor | implemented | 2026-07-19 PASS |
| SCN-078 | Edit a custom rule | rules | editor | implemented | 2026-07-19 PASS |
| SCN-079 | Delete a custom rule (default vs normal) | rules | editor | implemented | 2026-07-19 PASS |
| SCN-080 | View a rule read-only | rules | viewer | implemented | 2026-07-19 PASS |
| SCN-081 | Dashboard list & empty state | dashboards | analyst | implemented | 2026-07-19 PASS |
| SCN-082 | Create a dashboard from saved queries | dashboards | editor | implemented | 2026-07-19 PASS |
| SCN-083 | Edit a dashboard / refresh all | dashboards | editor | implemented | 2026-07-19 PASS |
| SCN-084 | View a shared dashboard | dashboards | viewer | implemented | 2026-07-19 PASS |
| SCN-085 | Shared dashboard link invalid / expired | dashboards | viewer | implemented | 2026-07-19 PASS |
| SCN-086 | Delete a dashboard | dashboards | editor | implemented | 2026-07-19 PASS |
| SCN-087 | Run a batch of queries | batch | analyst | implemented | 2026-07-19 PASS |
| SCN-088 | Build a batch from saved notes | batch | analyst | implemented | 2026-07-19 PASS |
| SCN-089 | View batch results | batch | analyst | implemented | 2026-08-31 PASS |
| SCN-090 | Create a scheduled query + alerts | schedules | owner | implemented | 2026-08-31 PASS |
| SCN-091 | Edit / pause / run-now a schedule | schedules | owner | implemented | 2026-07-19 PASS |
| SCN-092 | Delete a schedule | schedules | owner | implemented | 2026-07-19 PASS |
| SCN-093 | View schedule run history | schedules | owner | implemented | 2026-07-19 PASS |
| SCN-094 | Feedback analytics panel | analytics | owner | implemented | 2026-07-19 PASS |
| SCN-095 | Open settings & navigate | settings | analyst | implemented | 2026-07-19 PASS |
| SCN-096 | Change theme (light / system / dark) | settings | analyst | implemented | 2026-07-19 PASS |
| SCN-097 | Reduced-motion honored | settings | analyst | implemented | 2026-07-19 PASS |
| SCN-098 | Upgrade via pricing → Stripe checkout | billing | owner | implemented | 2026-07-19 PASS |
| SCN-099 | Manage billing (Stripe portal) | billing | owner | implemented | 2026-07-19 PASS |
| SCN-100 | Hit token / quota limit (HTTP 402) | billing | analyst | implemented | 2026-07-19 PASS |
| SCN-101 | Billing disabled (self-hosted) degradation | billing | owner | implemented | 2026-07-19 PASS |
| SCN-101a | Billing on, no subscription (unpaid account) | billing | owner | implemented | 2026-09-07 PASS |
| SCN-102 | View usage stats | usage | owner | implemented | 2026-07-19 PASS |
| SCN-103 | Mint & copy an MCP token | mcp-tokens | api-consumer | implemented | 2026-07-19 PASS |
| SCN-104 | Revoke an MCP token | mcp-tokens | api-consumer | implemented | 2026-07-19 PASS |
| SCN-105 | Background tasks — view/cancel/retry/dismiss | tasks | analyst | implemented | 2026-07-19 PASS |
| SCN-106 | Request history & trace detail | logs | owner | implemented | 2026-08-31 PASS |
| SCN-107 | Runs & Errors log tabs | logs | owner | implemented | 2026-08-16 PASS |
| SCN-108 | Live activity log stream | logs | analyst | implemented | 2026-07-19 PASS |
| SCN-109 | Landing page → Get Started | marketing | visitor | implemented | 2026-07-19 PASS |
| SCN-110 | Pricing CTA (logged out) | marketing | visitor | implemented | 2026-07-19 PASS |
| SCN-111 | Support / Contact / Legal pages | marketing | visitor | implemented | 2026-07-19 PASS |
| SCN-112 | Logged-in visitor auto-redirect to /app | marketing | analyst | implemented | 2026-07-19 PASS |
| SCN-113 | Add a Google Analytics 4 connection | analytics-sources | owner | implemented | 2026-08-19 PASS |
| SCN-114 | Add / delete a vendor credential | analytics-sources | owner | implemented | 2026-08-19 PASS |
| SCN-115 | Analytics collection status — ok / partial / pending periods | analytics-sources | editor | implemented | 2026-08-19 PASS |
| SCN-116 | Vendor credential delete blocked while in use | analytics-sources | owner | implemented | 2026-08-19 PASS |
| SCN-117 | Ask about analytics data in chat — grounded answer or honest refusal | analytics-sources | analyst | implemented | 2026-08-19 PASS |
| SCN-118 | Analytics answer renders a chart | analytics-sources | analyst | implemented | 2026-08-19 PASS |
| SCN-119 | Unsupported analytics source refused at creation | analytics-sources | owner | implemented | 2026-08-19 PASS |
| SCN-128 | One question across analytics and the database in a single answer | analytics-sources | analyst | implemented | 2026-09-03 PASS |
| SCN-120 | Database does not answer — honest stop instead of a silent grind | chat | analyst | implemented | 2026-08-19 PASS |
| SCN-121 | Attaching an SSH key you do not own is refused | connections | owner | implemented | 2026-08-19 PASS |
| SCN-122 | Every answer says how it is known — the seal | chat | analyst | implemented | 2026-08-16 PARTIAL → fixed |
| SCN-123 | The interface reads as one design in light and in dark | settings | analyst | implemented | 2026-08-16 PASS |
| SCN-124 | A result reads as a ledger — aligned, labelled, and the same in both themes | chat | analyst | implemented | 2026-08-16 PASS |
| SCN-125 | The answer is the page, not a speech bubble | chat | analyst | implemented | 2026-08-16 PARTIAL → fixed |
| SCN-126 | Transfer project ownership | members | owner | implemented | 2026-08-21 PASS |
| SCN-127 | Leave a project | analyst | members | implemented | 2026-08-21 PASS |
| SCN-129 | Data workspace — every source managed on one screen | workspace | owner | implemented | 2026-09-08 PASS |
| SCN-130 | Add a source without leaving the workspace | workspace | owner | draft | — |
| SCN-131 | A new project's workspace says what to connect first | workspace | owner | implemented | 2026-09-08 PASS |
| SCN-132 | Each source card says what the agent can do with it | workspace | analyst | implemented | 2026-09-08 PASS |
| SCN-133 | The sidebar switches, the workspace manages | workspace | analyst | implemented | 2026-09-08 PASS |
| SCN-134 | Say what a connection is for, in the agent's terms | connections | editor | implemented | 2026-09-08 PASS |
| SCN-135 | The answer shows which source context it was given | connections | analyst | draft | — |
| SCN-136 | Source context that did not fit says so | connections | analyst | draft | — |
| SCN-137 | Connect a repository to a project | repos | owner | draft | — |
| SCN-138 | Connect a second repository | repos | owner | draft | — |
| SCN-139 | Say what a repository is for, and what to ignore | repos | editor | draft | — |
| SCN-140 | Index one repository without disturbing the other | repos | editor | draft | — |
| SCN-141 | The answer names the repository it came from | repos | analyst | draft | — |
| SCN-142 | Disconnect a repository | repos | owner | draft | — |
| SCN-143 | Repository access is refused — recovery without losing the form | repos | owner | draft | — |
| SCN-144 | Refresh the documentation and see what changed | knowledge | editor | draft | — |
| SCN-145 | A document says where it came from and how old it is | knowledge | analyst | draft | — |
| SCN-146 | Set up a project without a subscription — the work proceeds, the schedule does not | billing | owner | implemented | 2026-09-07 PASS |
| SCN-147 | The schedule says why it is off and what turns it on | billing | owner | implemented | 2026-09-08 PASS |
| SCN-148 | A granted account behaves exactly as its plan | billing | owner | implemented | 2026-09-07 PASS |
| SCN-149 | The sidebar answers "where was I, and what needs me" | workspace | analyst | implemented | 2026-09-08 PASS |
| SCN-150 | The sidebar surfaces what needs attention and routes to the fix | workspace | analyst | implemented | 2026-09-08 PASS |
| SCN-151 | A panel link opens the panel it names | workspace | analyst | implemented | 2026-09-07 PASS |
| SCN-152 | The rail says when a project's index outgrew its plan | billing | owner | implemented | 2026-09-09 PASS |

## Personas

### new-user
Just registered, no projects yet. Wants to connect a database and get a first
answer with minimal reading. Meets the onboarding wizard and the readiness gate.

### analyst
Returning primary user. Asks natural-language data questions, reads results,
rates them, saves queries, builds dashboards. Trusts the agent but verifies —
cares about data honesty, freshness, and being able to stop/redo.

### owner
Project owner/admin. Creates projects and connections, manages members and
roles, billing, schedules, and destructive lifecycle actions. Sees owner-only
surfaces (Team & Invites, Billing, Usage, Schedules create).

### editor
Project member with edit rights. Can index/sync, edit rules and notes, build
dashboards — but cannot manage members, billing, or delete the project.

### viewer
Read-only member. Sees data, dashboards, and rules; can run saved queries; sees
static badges instead of mutate buttons.

### api-consumer
Developer wiring CheckMyData into an external agent/tool via MCP. Mints and
revokes per-user MCP tokens in-app; most of their work happens outside the UI.

### visitor
Anonymous marketing-site visitor evaluating the product before signing up.

## onboarding

### SCN-001: First-run onboarding wizard — happy path
- **Persona:** new-user
- **Feature:** onboarding
- **Entry point:** `/app` first load when `user && !is_onboarded && projects.length===0` opens the 5-step modal (`app/app/page.tsx:121-122,174`)
- **Preconditions:** authenticated, approved to create projects, no projects yet
- **Steps:**
  1. Step 0 — pick DB type, fill host/port/database/username/password, submit
  2. Step 1 — connection auto-tests and, on success, auto-advances
  3. Step 2 — start indexing and wait for "Indexing complete"
  4. Step 3 — optionally add a Git repo URL, or Skip (marked Optional)
  5. Step 4 — type a first question and Finish setup
- **Expected result:** connection created, DB indexed, onboarding dismissed; user lands in chat with the first question queued
- **UI elements:** step progress dots, DB-type toggles, host/port/db/user/password inputs, "SSH Tunnel (Advanced)" toggle, Test spinner, "Start indexing" button, repo URL input, first-question textarea, Back / Continue / "Finish setup" / "Skip setup entirely" buttons
- **States covered:** loading, success, error
- **Errors & recovery:** create fails → toast "Failed to create connection"; index timeout → inline "Indexing had issues, but you can still use the app" + toast + Continue; complete fails → toast "Failed to complete onboarding" (`OnboardingWizard.tsx:160` create, `:584-591` the indexing warning and its Continue, `:237` complete)
- **Status:** implemented
- **Coverage:** components/onboarding/OnboardingWizard.tsx:13,173,286-292,498-660; app/app/page.tsx:121-122,174

### SCN-002: Onboarding — connection test fails, retry/edit
- **Persona:** new-user
- **Feature:** onboarding
- **Entry point:** onboarding step 1 after submitting bad DB credentials
- **Preconditions:** in onboarding, step 0 submitted
- **Steps:**
  1. Connection test runs and fails
  2. User reads "Connection failed" + error detail
  3. User clicks "Edit connection" to fix fields, or "Retry"
- **Expected result:** user can correct credentials and re-test without leaving the wizard
- **UI elements:** test spinner "Testing connection...", failure block, error message, "Edit connection" button, "Retry" button
- **States covered:** loading, error
- **Errors & recovery:** this scenario IS the error path; retry re-runs the test, edit returns to step 0 (`OnboardingWizard.tsx:515-544,178-181`)
- **Status:** implemented
- **Coverage:** components/onboarding/OnboardingWizard.tsx:498-547

### SCN-003: Onboarding — skip setup / try demo
- **Persona:** new-user
- **Feature:** onboarding
- **Entry point:** onboarding modal footer / step-0 alternative
- **Preconditions:** in onboarding
- **Steps:**
  1. User clicks "Try demo instead" (step 0) to load demo data, OR
  2. User clicks "Skip setup entirely" / presses Escape
- **Expected result:** onboarding is dismissed; wizard does not reappear (`is_onboarded` set). The demo path creates a **read-only** SQLite connection over a **seeded** sample database — `customers` (5 rows) and `orders` (8 rows), enough to join, group and check the agent's answer by eye. Clicking it a **second time reuses the same demo project and connection** rather than creating another.
- **UI elements:** "Try demo instead" button, "Skip setup entirely" button, Escape-to-skip, step-3 "Skip"
- **States covered:** success, error, plan-limit
- **Errors & recovery:** demo setup fails → toast "Failed to set up demo"; **plan limit reached → 402 with a linkified upgrade message** (`_client.ts:140-158`), because the demo consumes a project and a connection like any other; skip fails → toast "Failed to skip onboarding" (`OnboardingWizard.tsx:284,251`)
- **Status:** implemented
- **Coverage:** components/onboarding/OnboardingWizard.tsx:761-766,798-804,88-90; backend/app/api/routes/demo.py; backend/app/services/demo_data.py; backend/app/connectors/sqlite.py; backend/tests/integration/test_demo_routes.py; backend/tests/unit/test_demo_data.py; backend/tests/unit/test_sqlite_connector.py
- **Note (2026-08-20):** the demo runs on the SQLite connector added the same day — `db_type="sqlite"` had no entry in the adapter registry, so before that the demo's connection could not be opened at all and the first question asked of it failed on dispatch. This scenario was marked PASS on 2026-07-19 against its *affordances* — the button rendered and the toasts fired — while its **expected result went undelivered**: the route seeded nothing and pointed at `:memory:`, so a first-run user saw an empty database. A scenario can pass on what the screen offers and fail on what it promised; the audit that closes it must read the expected result, not the buttons.

### SCN-004: Request project access (non-approved user)
- **Persona:** new-user
- **Feature:** onboarding
- **Entry point:** onboarding step 0 when `!user.can_create_projects`, or the "New project" action for a non-approved user (`OnboardingWizard.tsx:310-315`, `ProjectSelector.tsx:277-288`)
- **Preconditions:** authenticated, not permitted to create projects
- **Steps:**
  1. User sees the approval notice and clicks "Request project access"
  2. User fills email (prefilled), project description, and message
  3. User clicks "Send request"
- **Expected result:** confirmation panel "Request sent" + toast; user can dismiss with "Got it"
- **UI elements:** "Request project access" button, email/description/message inputs, "Send request" button, success panel, "Got it" button, FormModal close
- **States covered:** loading, success, error
- **Errors & recovery:** submit fails → toast "Failed to send request" (`RequestAccessModal.tsx:40`)
- **Reached far less often since 2026-09-02:** `can_create_projects` defaulted to False and **no code path anywhere granted it** — this very screen's "Send request" emails a human and returns ok, setting nothing. So every signup landed here about forty seconds in, and the queue was drained by hand. The right is now granted the moment the address is proven owned: at email verification, and at creation for a Google login. This scenario survives for the two cases that remain — an account whose right was revoked, and a self-hosted install with no mail configured — and the wall a user hits before verifying now says *verify your email*, with the resend link, instead of *request access*.
- **Status:** implemented
- **Coverage:** components/projects/RequestAccessModal.tsx:26,38-73,90-132; backend/app/api/routes/projects.py:152-169; backend/app/services/auth_service.py (verify_email, find_or_create_google_user); tests backend/tests/unit/test_project_access_grant.py, backend/tests/integration/test_projects.py

## auth

### SCN-005: Register with email + password
- **Persona:** new-user
- **Feature:** auth
- **Entry point:** `/login` in register mode (toggled from Sign In)
- **Preconditions:** not authenticated
- **Steps:**
  1. User switches to "Create Account"
  2. User fills display name, email, password (≥8 chars)
  3. User clicks "Create Account"
- **Expected result:** account created, session established, redirect to `/app`
- **UI elements:** mode-switch button, display name input, email input, password input, "Create Account" button, inline validation messages
- **States covered:** loading, error, success
- **Errors & recovery:** invalid email → inline "Please enter a valid email address"; password <8 → inline "Password must be at least 8 characters"; register fails → inline error block + toast "Registration failed" (`login/page.tsx:162` sets the email message and `:240` renders it, `:262-266` the password rule; `auth-store.ts:115-123`)
- **Status:** implemented
- **Coverage:** app/login/page.tsx:159-190 (submit), :208-272 (register fields), :284-291 (error block); stores/auth-store.ts:115-123

### SCN-006: Log in with email + password
- **Persona:** analyst
- **Feature:** auth
- **Entry point:** `/login` (default Sign In mode)
- **Preconditions:** existing account, not authenticated
- **Steps:**
  1. User enters email and password
  2. User clicks "Sign In"
- **Expected result:** session cookie set, redirect to `/app`
- **UI elements:** email input, password input, "Sign In" button (shows "Signing in..."), inline error block
- **States covered:** loading, error, success
- **Errors & recovery:** invalid email → inline message; login fails → inline error + toast "Login failed" (`auth-store.ts:102-110`, rendered `login/page.tsx:284-291`)
- **Status:** implemented
- **Coverage:** app/login/page.tsx:159-190 (submit), :294-300 ("Signing in…"), :284-291 (error block); stores/auth-store.ts:102-110

### SCN-007: Sign in with Google
- **Persona:** analyst
- **Feature:** auth
- **Entry point:** `/login`, Google Identity Services button (only when `GOOGLE_CLIENT_ID` set)
- **Preconditions:** not authenticated; Google configured
- **Steps:**
  1. User clicks the rendered Google button
  2. User completes Google auth; credential + CSRF token exchanged
- **Expected result:** pre-verified session, redirect to `/app`
- **UI elements:** GIS button, "Signing in with Google..." disabled state
- **States covered:** loading, error, success
- **Errors & recovery:** exchange fails → toast "Google sign-in failed" + store error (`auth-store.ts:131-135`); button absent entirely if Google not configured
- **Status:** implemented
- **Coverage:** app/login/page.tsx:61-96,256-273; stores/auth-store.ts:125-136

### SCN-008: Log out
- **Persona:** analyst
- **Feature:** auth
- **Entry point:** "Sign Out" in Account menu (`AccountMenu.tsx:80-86`) or Settings panel (`SettingsPanel.tsx:104-111`)
- **Preconditions:** authenticated
- **Steps:**
  1. User clicks "Sign Out"
- **Expected result:** stores/storage cleared, `user=null`, a "Signed out" success toast shown, AuthGate redirects to `/login`
- **UI elements:** "Sign Out" button, success toast
- **States covered:** success
- **Errors & recovery:** the local teardown is unconditional — a failing call must never trap someone in a session they asked to leave — but a non-401 failure now says the server session may still be active (`auth-store.ts:148-165`), because "Signed out" alone is a claim the client cannot make on its own (AUD-0819-12). A 401 stays quiet: the session is already gone, which is the outcome asked for, and a warning beside it is the noise that teaches people to ignore warnings. No confirm dialog (immediate, non-destructive) — intentional. Session-expiry (SCN-011) and account-deletion paths keep their own distinct toasts (no double-toast)
- **Status:** implemented
- **Coverage:** components/auth/AccountMenu.tsx:80-89; components/settings/SettingsPanel.tsx:104-113; stores/auth-store.ts:138-172

### SCN-009: Change password
- **Persona:** analyst
- **Feature:** auth
- **Entry point:** Account menu / Settings → "Change Password" (hidden for Google-only accounts)
- **Preconditions:** authenticated with a password-based account
- **Steps:**
  1. User opens Change Password
  2. User enters current password and a new password (≥8)
  3. User clicks Save
- **Expected result:** toast "Password changed successfully"; form closes
- **UI elements:** current-password input, new-password input, Cancel, Save ("Saving...")
- **States covered:** loading, error, success
- **Errors & recovery:** new password <8 → toast; API fails → toast (server msg or "Failed to change password") (`AccountMenu.tsx:114-124`)
- **Status:** implemented
- **Coverage:** components/auth/AccountMenu.tsx:107-175; components/settings/SettingsPanel.tsx:224-258

### SCN-010: Delete account
- **Persona:** analyst
- **Feature:** auth
- **Entry point:** Account menu / Settings → "Delete Account"
- **Preconditions:** authenticated
- **Steps:**
  1. User opens Delete Account
  2. User types `DELETE` into the confirm field
  3. User clicks Delete
- **Expected result:** account deleted, toast "Account deleted", user logged out
- **UI elements:** type-to-confirm input, "This action cannot be undone" warning, Cancel, Delete (disabled until `DELETE`, "Deleting...")
- **States covered:** loading, error, success
- **Errors & recovery:** API fails → toast "Failed to delete account" (`AccountMenu.tsx:189`). Destructive-confirm: inline typed-`DELETE` gate (bespoke, not the global ConfirmModal)
- **Status:** implemented
- **Coverage:** components/auth/AccountMenu.tsx:177-227; components/settings/SettingsPanel.tsx:263-310

### SCN-011: Session expiry → forced re-login
- **Persona:** analyst
- **Feature:** auth
- **Entry point:** any authenticated screen when the refresh timer expires, or any API call that returns 401
- **Preconditions:** authenticated session reaches expiry
- **Steps:**
  1. Refresh timer fires, or a 401 is intercepted from any non-auth API call
- **Expected result:** toast "Your session has expired. Please log in again." then auto-logout → `/login`; on the 401 path the same message is stashed to sessionStorage before the hard redirect and shown once on `/login` as an inline banner (role="alert"), then cleared. **The persisted profile (`auth_user`, `auth_token`) is cleared synchronously before the redirect** — anything deferred past `window.location.href` may never run, and the profile is the one piece of auth state that outlives a navigation.
- **UI elements:** toast, AuthGate "Redirecting...", login-page session-expired banner
- **States covered:** error
- **Errors & recovery:** this IS the recovery path — user re-authenticates via SCN-006/007. One shared message constant `SESSION_EXPIRED_MESSAGE` (`lib/session-flash.ts`) across the 401 interceptor, SSE path, and timer path; the one-shot 401 guard (`sessionExpiredHandled`) is re-armed by `resetSessionExpiredFlag()` on every successful (re-)authentication, so repeat 401s are handled even without a full page reload. **Correction 2026-08-21:** until this date the teardown ran through `void import("@/stores/auth-store").then(logout)` with the redirect on the next synchronous line, so whether the profile was actually cleared depended on a race with the document unloading — a session could expire, land the user on `/login`, and leave the app holding their profile against a cookie the server had already rejected
- **Status:** implemented
- **Coverage:** frontend/src/lib/session-flash.ts; frontend/src/lib/api/_client.ts:15-52,152-153; stores/auth-store.ts:36,77,90; app/login/page.tsx:62-68,198-205; components/auth/AuthGate.tsx:16-36; tests frontend/src/__tests__/session-flash.test.ts, frontend/src/__tests__/session-expiry-clears-auth.test.ts (the profile is gone before the redirect), frontend/src/__tests__/components/LoginPage.test.tsx (flash banner), frontend/src/__tests__/auth-store.test.ts (re-arm)

### SCN-012: Email verification after registration
- **Persona:** new-user
- **Feature:** auth
- **Entry point:** post-registration prompt in the app shell + the emailed `/verify-email?token=…` link (backend `POST /api/auth/verify-email`, F-PROJ-01)
- **Preconditions:** email/password registration with `email_verified=False`
- **Steps:**
  1. After registering, the app shell shows an unobtrusive "Verify your email" banner (hidden for verified and Google accounts)
  2. User opens the link in the verification email → lands on `/verify-email?token=…`, which auto-confirms the address (and auto-accepts any pending email invites)
  3. If the link is invalid/expired — or from the banner — the user can resend a fresh link
- **Expected result:** the address is verified, the banner disappears, and pending email invites are auto-accepted; a lost/expired link can be re-requested
- **UI elements:** `EmailVerifyBanner` (app shell) with a "Resend email" button; `/verify-email` page with loading / "Email verified" (→ "Continue to app") / "Verification failed" (+ resend when logged in) states
- **States covered:** loading (verifying), success (verified + continue link), error (invalid/expired token, missing token), resend (success/failure toast, "Email sent")
- **Errors & recovery:** invalid / expired / missing token → error state; logged-in users resend from the page or the banner ("Verification email sent" / failure toast); `email_verified` is surfaced in register/login/refresh/`/me` responses so the banner shows only for unverified non-Google accounts; resend is an idempotent no-op for already-verified / Google accounts (`already_verified: true`) and rate-limited (3/min)
- **Status:** implemented
- **Coverage:** backend `backend/app/api/routes/auth.py` (`_auth_response`/`UserResponse` expose `email_verified`; `POST /api/auth/resend-verification`; `POST /api/auth/verify-email`) → `AuthService.issue_email_verification`/`verify_email`, `EmailService.send_verification_email`; frontend `frontend/src/app/verify-email/page.tsx`, `frontend/src/components/auth/EmailVerifyBanner.tsx` (wired into `frontend/src/app/app/page.tsx`), `frontend/src/lib/api/auth.ts` (`verifyEmail`/`resendVerification`), `AuthUser.email_verified` in `frontend/src/lib/api/types.ts`; tests `backend/tests/integration/test_auth_email_verification.py`, `frontend/src/__tests__/components/VerifyEmailPage.test.tsx`, `frontend/src/__tests__/components/EmailVerifyBanner.test.tsx`

### SCN-013: Forgot / reset password
- **Persona:** analyst
- **Feature:** auth
- **Entry point:** `/login` → "Forgot password?" link (sign-in mode only) → `/forgot-password`; reset link in the email lands on `/reset-password?token=…`
- **Preconditions:** password-based account, user cannot log in
- **Steps:**
  1. From the login screen the user clicks "Forgot password?" and enters their email on `/forgot-password`
  2. The backend mints a single-use token (SHA-256 hash + 1-hour expiry persisted, raw token emailed) and emails a `/reset-password?token=…` link; the page always shows a generic confirmation so account existence is never revealed
  3. The user opens the link, enters a new password (+ confirm) on `/reset-password`, and submits
  4. On success the password is updated, the token is cleared (single-use), all prior sessions are revoked (`token_version` bump), and the user is redirected to `/login` to sign in with the new password
- **Expected result:** user regains access without contacting support; every previously issued session/token is invalidated
- **UI elements:** login "Forgot password?" link; `/forgot-password` page (email input + inline validation, "Send reset link" button, generic "Check your email" confirmation); `/reset-password` page (new-password + confirm inputs with inline validation, "Reset password" button, invalid/expired-link error with a "Request a new reset link" recovery link, missing-token "Invalid reset link" state)
- **States covered:** forgot: idle (form), loading ("Sending…"), success (generic confirmation), error (rate-limit/network message), inline invalid-email; reset: loading ("Resetting…"), success (toast + redirect to `/login`), error (invalid/expired token + recovery link), inline password-too-short (<8) / password-mismatch, missing-token
- **Errors & recovery:** unknown / passwordless (Google-only) email → still a generic `{"ok": true}` with no email sent (no account-enumeration leak); invalid / expired / already-used token → 400 surfaced as an error with a link to request a fresh reset; `new_password` < 8 → 422 (also blocked client-side inline); both endpoints are public + rate-limited (5/min)
- **Status:** implemented
- **Coverage:** backend model `backend/app/models/user.py:42-45` (`password_reset_token`/`password_reset_expires_at`), migration `backend/alembic/versions/e7f8a9b0c1d2_add_password_reset_to_users.py` (revision `e7f8a9b0c1d2`, down_revision `d5e6f7a8b9c0`), config `backend/app/config.py:122` (`password_reset_expiry_hours=1`); service `backend/app/services/auth_service.py:162` (`issue_password_reset`), `:188` (`reset_password`); email `backend/app/services/email_service.py:205` (`send_password_reset_email` → `{app_url}/reset-password?token=…`); routes `backend/app/api/routes/auth.py:183-201` (`POST /api/auth/forgot-password`), `:204-224` (`POST /api/auth/reset-password`); frontend `frontend/src/app/forgot-password/page.tsx`, `frontend/src/app/reset-password/page.tsx`, login link `frontend/src/app/login/page.tsx:261`, api `frontend/src/lib/api/auth.ts:75` (`forgotPassword`), `:80` (`resetPassword`); tests `backend/tests/unit/test_password_reset.py`, `backend/tests/integration/test_password_reset.py`, `frontend/src/__tests__/components/ForgotPasswordPage.test.tsx`, `frontend/src/__tests__/components/ResetPasswordPage.test.tsx`, `frontend/src/__tests__/components/LoginPage.test.tsx` (forgot-password link)

## invites

### SCN-014: Accept a pending project invite
- **Persona:** analyst
- **Feature:** invites
- **Entry point:** Pending Invitations banner at the top of the sidebar (auto-loaded)
- **Preconditions:** authenticated, ≥1 pending invite
- **Steps:**
  1. User clicks "Accept" on an invite row
- **Expected result:** row removed, projects reloaded, toast "Invite accepted"
- **UI elements:** invite row, "Accept" button (shows "..."), Spinner while list loads
- **States covered:** loading, empty (banner hidden when none), error, success
- **Errors & recovery:** load fails (non-401) → toast; accept fails → toast "Failed to accept invite" (`PendingInvites.tsx:20-23,42`)
- **Status:** implemented
- **Coverage:** components/invites/PendingInvites.tsx:29-73

### SCN-015: Decline / reject an invite
- **Persona:** analyst
- **Feature:** invites
- **Entry point:** Pending Invitations banner → per-invite "Decline" button
- **Preconditions:** ≥1 pending invite addressed to the signed-in user's email
- **Steps:**
  1. User clicks "Decline" on an unwanted invite
- **Expected result:** the invite row is removed from the pending list, the invite is deleted server-side (the user never joins the project), and an "Invite declined" success toast is shown
- **UI elements:** per-row secondary/text "Decline" button (`aria-label="Decline invitation to {project}"`) beside "Accept"; both buttons disabled while either action is in flight (label shows "…")
- **States covered:** loading (button "…"), success (row removed + toast), error (toast, row retained)
- **Errors & recovery:** decline fails → toast "Failed to decline invite" (or the API error message) and the row is kept; a non-invitee is rejected 403 and a non-pending/unknown invite 400/404 server-side, surfaced as an error toast
- **Status:** implemented
- **Coverage:** backend route `POST /api/invites/decline/{invite_id}` (`backend/app/api/routes/invites.py:253-270`) → `InviteService.decline_invite` (`backend/app/services/invite_service.py:159-196`; deletes the row for constraint-safe re-invite — email-owner + pending checks mirror accept with 404/400/403); frontend `frontend/src/components/invites/PendingInvites.tsx:50-61,85-93` + `frontend/src/lib/api/workspace.ts:106-107`; tests `backend/tests/unit/test_invite_service.py::TestDeclineInvite`, `backend/tests/integration/test_invites.py::TestInviteRoutes::test_invitee_can_decline_invite`, `frontend/src/__tests__/components/PendingInvites.test.tsx`

## projects

### SCN-016: Create a project
- **Persona:** owner
- **Feature:** projects
- **Entry point:** sidebar "New project" action → "New Project" FormModal
- **Preconditions:** authenticated with `can_create_projects` — held by every user whose email address is verified (2026-09-02); before that the flag had no grant path at all and this scenario was unreachable for a self-signup
- **Steps:**
  1. User opens New Project
  2. User enters a name, optionally a Git repo URL (+ SSH key/branch), optionally LLM models
  3. User clicks "Create"
- **Expected result:** project created, prepended, set active; toast "Project created"
- **UI elements:** name input, repo URL input, SSH key select, branch select/input, LLM "details", "Use Agent model" checkbox, Create button
- **States covered:** loading (repo access check), error, success
- **Errors & recovery:** empty name → inline "Name is required"; repo access denied → inline red text; SSH URL without key → inline "add an SSH key first"; create fails → toast (`ProjectSelector.tsx:296-299,322-327,512-538`)
- **Status:** implemented
- **Coverage:** components/projects/ProjectSelector.tsx:461-655; components/Sidebar.tsx:494

### SCN-017: Switch between projects (multi-entity)
- **Persona:** analyst
- **Feature:** projects
- **Entry point:** clicking a project row in the sidebar
- **Preconditions:** ≥2 projects
- **Steps:**
  1. User clicks a different project row
- **Expected result:** active project + role swap; connections and chat sessions reload; first connection auto-selected; a welcome session ensured when none exist
- **UI elements:** project row (role="button"), active indicator, role badge, per-row Spinner
- **States covered:** loading, error, success
- **Errors & recovery:** parallel load fails → toast "Failed to load project data", connections/sessions reset, and an inline error + Retry rendered in the connections list instead of a deceptive "No connections yet" (audit M5; `connectionsError` in app-store); stale responses ignored via sequence guard (`ProjectSelector.tsx:379-431`)
- **Status:** implemented
- **Coverage:** components/projects/ProjectSelector.tsx:379-431,679-729; components/connections/ConnectionSelector.tsx:118-136,1097-1103

### SCN-018: Edit a project
- **Persona:** owner
- **Feature:** projects
- **Entry point:** hover a project row → pencil "Edit project" (owner only), or the active-project edit trigger
- **Preconditions:** owner of the project
- **Steps:**
  1. User opens Edit Project
  2. User changes name / repo / LLM models
  3. User clicks "Save Changes"
- **Expected result:** toast "Project updated"; row reflects changes
- **UI elements:** same FormModal as create titled "Edit Project", Save Changes, Cancel
- **States covered:** error, success
- **Errors & recovery:** empty name → inline; update fails → toast "Failed to update project" (`ProjectSelector.tsx:341-344,371-376`)
- **Status:** implemented
- **Coverage:** components/projects/ProjectSelector.tsx:253-261,640-655

### SCN-019: Delete a project
- **Persona:** owner
- **Feature:** projects
- **Entry point:** hover a project row → trash "Delete project" (owner only)
- **Preconditions:** owner of the project
- **Steps:**
  1. User clicks the trash icon
  2. Global confirm (critical) appears warning it removes all connections/chat/rules/knowledge
  3. User types the project name to enable Confirm, then confirms
- **Expected result:** project removed; if active, active project/connections/sessions cleared
- **UI elements:** trash ActionButton, ConfirmModal (severity critical, detail, type-to-confirm the project name)
- **States covered:** error, success
- **Errors & recovery:** delete fails → toast "Failed to delete project" (`ProjectSelector.tsx:451-455`)
- **Status:** implemented
- **Coverage:** components/projects/ProjectSelector.tsx:429-455; components/ui/ConfirmModal.tsx:64,126-127

### SCN-020: Project overview — no project / empty
- **Persona:** analyst
- **Feature:** projects
- **Entry point:** main panel when no project is active or no connections exist
- **Preconditions:** no active project, or active project with no connections
- **Steps:**
  1. User views the overview panel
- **Expected result:** clear guidance — "Select a project to see its overview", "No connections configured yet", "No recent pipeline errors"
- **UI elements:** folder icon empty states, embedded HomeAsk / ConnectionHealth / KnowledgeHealth / Usage panels
- **States covered:** empty
- **Errors & recovery:** read-only surface; last 5 failed pipeline log entries shown
- **Status:** implemented
- **Coverage:** components/projects/ProjectOverview.tsx:36-90

## members

### SCN-021: Invite a member & set role
- **Persona:** owner
- **Feature:** members
- **Entry point:** hover a project row → "Manage access" (owner) → AccessModal → InviteManager
- **Preconditions:** owner of the project
- **Steps:**
  1. User types an email, picks a role (Editor/Viewer)
  2. User clicks "Invite" (or presses Enter)
- **Expected result:** toast "Invite sent"; invite appears under Pending
- **UI elements:** email input, role select, Invite button, close (X)
- **States covered:** loading, error, success
- **Errors & recovery:** invite fails → inline error text; load fails → toast "Failed to load access data" (`InviteManager.tsx:86,66`)
- **Status:** implemented
- **Coverage:** components/projects/InviteManager.tsx:186-210; components/projects/ProjectSelector.tsx:733-773

### SCN-022: Change a member's role
- **Persona:** owner
- **Feature:** members
- **Entry point:** AccessModal member row role select
- **Preconditions:** owner; ≥1 non-owner member
- **Steps:**
  1. User changes a member's role in the select
- **Expected result:** toast "Role updated" (applied optimistically)
- **UI elements:** per-member role select
- **States covered:** loading, error, success
- **Errors & recovery:** update fails → optimistic revert + toast (`InviteManager.tsx:158-161`). Note: role change has no confirm dialog
- **`owner` is not one of the choices, by design (F-PROJ-10):** the select offers `editor`/`viewer` and the route's schema accepts only those. Ownership moves through SCN-126, which enforces the receiving owner's plan quota and keeps `Project.owner_id` and the member row in step; allowing "owner" here would be a second, unguarded path to the same state.
- **The member list is bounded (F-PROJ-13):** the API returns at most 500 members (hard maximum 1000) and marks a partial page with `X-Result-Capped: true`, carrying the real total in `X-Total-Count`. A team that large is not a case this product has met, but a page returned with no marker would read as the whole team — which is the same shape as a truncated query result reported as a total.
- **Status:** implemented
- **Coverage:** components/projects/InviteManager.tsx:237-254,149-165

### SCN-126: Transfer project ownership
- **Persona:** owner
- **Feature:** members
- **Entry point:** AccessModal member row → "Make owner"
- **Preconditions:** the viewer is the owner; the target is already a member
- **Steps:**
  1. Owner clicks "Make owner" on a member's row
  2. Owner confirms in the dialog
- **Expected result:** the target becomes owner, the previous owner becomes an **editor**, the members list re-reads from the server, toast "<name> is now the owner"
- **UI elements:** "Make owner" button per non-owner row (owner only), confirm dialog, per-row disabled state while in flight
- **States covered:** loading, success, error, declined
- **Why it exists (F-PROJ-10):** before this the owner was permanent. `update_member_role` refuses to touch an owner and the role route's schema accepts only `editor`/`viewer`, so no request could appoint a successor or resign. An owner leaving took the workspace with them, and there was no in-product fix.
- **What the confirm must say:** the actor is **demoted to editor and cannot take ownership back** — only the new owner can pass it on — and the new owner's plan must have room for another project. A confirm that omits the demotion asks someone to agree to something they were not told.
- **The old owner is demoted, not removed.** Taking away someone's access is a different decision from taking away their ownership, and only the second one was asked for.
- **Both records move together.** Ownership is readable from `Project.owner_id` *and* from a member row; changing one leaves two owners — the new one by the column, the old one by the row — which is worse than none. The list is therefore re-read rather than patched locally, because two rows change at once.
- **Plan limits apply to the receiving owner.** Project quotas count by `owner_id`, so the transfer is refused with the usual 402/quota message if the new owner is full — checked before anything is written, so a refusal changes nothing.
- **The target must already be a member.** Transfer is not an access grant: invite first, then transfer. Naming a non-member returns 400 saying so.
- **Errors & recovery:** declined confirm → nothing happens; 403 (not the owner) / 400 (not a member, or already the owner) / quota → toast with the server's reason, list unchanged
- **The stranded case is an admin action, not a UI one.** `Project.owner_id` is `ondelete="SET NULL"`, so a deleted account leaves a project with **no** owner and no member who may appoint one — the button does not appear for anyone. An admin (`ADMIN_EMAILS`) can transfer it via `POST /api/invites/{project_id}/transfer-ownership`; a non-admin member claiming it is refused with 403, since self-appointment is exactly the escalation that guard is for.
- **Status:** implemented
- **Coverage:** components/projects/InviteManager.tsx (row action + confirm), lib/api/workspace.ts `transferOwnership`, `backend/app/services/membership_service.py::transfer_ownership`, `backend/app/api/routes/invites.py::transfer_ownership`; tests `frontend/src/__tests__/components/InviteManager.test.tsx` (6), `backend/tests/unit/test_membership_service.py` (9), `backend/tests/unit/test_ownership_transfer_route.py` (5)

### SCN-127: Leave a project
- **Persona:** analyst (any member who is not the owner)
- **Feature:** members
- **Entry point:** AccessModal → "Leave project" on your own row
- **Preconditions:** the viewer is a member and is **not** the owner
- **Steps:**
  1. Member clicks "Leave project"
  2. Member confirms
- **Expected result:** the membership is removed, the project disappears from their list, and they are returned to the project picker
- **UI elements:** "Leave project" action on the caller's own row only; confirm dialog
- **States covered:** success, refused (owner), error
- **Why it exists (F-PROJ-12):** there was no way out. Only an owner could remove a member, so a person who no longer needed a project stayed in it — and the project stayed in their list — until someone else acted.
- **The owner cannot leave, and the refusal is the point.** An owner walking out would leave the workspace with nobody able to manage it, which is exactly the stranded state SCN-126 exists to prevent. So the answer is 400 with a message naming the way out: transfer ownership first, then leave. This scenario is only coherent *because* SCN-126 shipped — before it, "you must transfer first" would have been advice with no route behind it.
- **Ownership is read from both places.** A role comes from the member row *or* `Project.owner_id`; an owner whose row disagrees with the column is still refused, because checking one of the two is how such a person slips out.
- **The request cannot name anyone else.** The endpoint is `/members/me`, not `/members/{id}` — there is no guard to forget, because there is no way to express the thing a guard would refuse.
- **Errors & recovery:** owner → 400 with the transfer hint; not a member → 404 (not a 204 that removed nothing); network failure → toast, membership unchanged
- **Status:** implemented
- **Coverage:** `backend/app/services/membership_service.py::leave_project`, `backend/app/api/routes/invites.py::leave_project`; tests `backend/tests/unit/test_membership_lists_and_leave.py` (17)

### SCN-023: Remove a member
- **Persona:** owner
- **Feature:** members
- **Entry point:** AccessModal member row "Remove"
- **Preconditions:** owner; target is a non-owner member
- **Steps:**
  1. User clicks "Remove"
  2. Global confirm (warning) "…lose access immediately" appears
  3. User confirms
- **Expected result:** toast "Member removed"; member row gone
- **UI elements:** "Remove" button, ConfirmModal (warning, no type-to-confirm)
- **States covered:** error, success
- **Errors & recovery:** remove fails → toast (`InviteManager.tsx:145`)
- **Status:** implemented
- **Coverage:** components/projects/InviteManager.tsx:256-264,131-146

### SCN-024: Resend / revoke a pending invite
- **Persona:** owner
- **Feature:** members
- **Entry point:** AccessModal Pending list
- **Preconditions:** owner; ≥1 pending invite
- **Steps:**
  1. User clicks "Resend" (60s cooldown → "Sent!"), or
  2. User clicks "Delete" → confirm (warning) → revoke
- **Expected result:** toast "Invite email resent" or "Invite deleted"
- **UI elements:** "Resend" button (cooldown), "Delete" button, ConfirmModal (warning)
- **States covered:** empty (Pending block hidden when none), error, success
- **Errors & recovery:** resend fails → toast; revoke fails → toast (`InviteManager.tsx:125,105`)
- **Status:** implemented
- **Coverage:** components/projects/InviteManager.tsx:271-313,92-125

## connections

### SCN-025: Add a DB connection
- **Persona:** owner
- **Feature:** connections
- **Entry point:** sidebar "New connection" (owner) → "New Connection" FormModal
- **Preconditions:** owner; a project is active
- **Steps:**
  1. User names the connection and picks a DB type (postgres/mysql/clickhouse/mongodb) — default port auto-fills
  2. User fills host/port/database/username/password
  3. User submits "Create Connection"
- **Expected result:** toast "Connection created"; connection appears in the list
- **UI elements:** name input, DB-type select, host/port/db/user/password inputs, read-only toggle, "Create Connection" button (Saving…)
- **States covered:** loading, error, success
- **Errors & recovery:** empty name → silent return; SSH host without user/key → toast; create fails → toast "Failed to create connection" (`ConnectionSelector.tsx:313-317,379-383`)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:623-835,1028-1035

### SCN-026: Add connection via connection-string autofill
- **Persona:** owner
- **Feature:** connections
- **Entry point:** New/Edit Connection form → "Use connection string" or paste-to-autofill
- **Preconditions:** owner; adding a non-MCP connection
- **Steps:**
  1. User checks "Use connection string" and pastes a DSN, or pastes into the autofill field
  2. Fields populate; user submits
- **Expected result:** connection created from the parsed string
- **UI elements:** "Use connection string" checkbox, connection-string input, autofill field with detection message
- **States covered:** loading, error, success
- **Errors & recovery:** as SCN-025; note SSH tunnel is not used with connection strings (inline note)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:732-772,836-840

### SCN-027: Add an MCP connection
- **Persona:** owner
- **Feature:** connections
- **Entry point:** New Connection form → DB type "mcp"
- **Preconditions:** owner
- **Steps:**
  1. User selects MCP and a transport (stdio/sse)
  2. User fills command+args (stdio) or URL (sse), optional env JSON
  3. User submits
- **Expected result:** MCP connection created (shows "MCP" badge; no read-only/SSH fields)
- **UI elements:** transport select, command/args inputs, sse URL input, env JSON textarea
- **States covered:** loading, error, success
- **Errors & recovery:** stdio without command → toast; sse without URL → toast; invalid env JSON → toast (`ConnectionSelector.tsx:319-337`)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:670-728

### SCN-028: Configure an SSH tunnel on a connection
- **Persona:** owner
- **Feature:** connections
- **Entry point:** New/Edit Connection form (non-MCP, individual-fields mode) → fill SSH Host
- **Preconditions:** owner; ≥1 SSH key exists for tunnel auth
- **Steps:**
  1. User enters SSH host/port/user and selects an SSH key
  2. Optionally enables SSH Exec Mode + command template/pre-commands
  3. User submits
- **Expected result:** connection saved with tunnel/exec config
- **UI elements:** SSH host/port/user inputs, SSH key select, "SSH Exec Mode" checkbox, exec preset select, command-template + pre-commands textareas, inline warnings
- **States covered:** error, success
- **Errors & recovery:** SSH host set but missing user/key → inline warning + toast at submit; MongoDB disables exec mode (`ConnectionSelector.tsx:886-890,314-317`)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:842-1006

### SCN-029: Toggle read-only mode
- **Persona:** owner
- **Feature:** connections
- **Entry point:** New/Edit Connection form (non-MCP) → "Read-only mode" checkbox (default on)
- **Preconditions:** owner; non-MCP connection
- **Steps:**
  1. User toggles the read-only checkbox
  2. User saves
- **Expected result:** connection shows/hides the "RO" badge; read-only enforcement applied at query time (vision §7 #1)
- **UI elements:** "Read-only mode" checkbox (shield icon), "RO" row badge
- **States covered:** success
- **Errors & recovery:** none specific to the toggle
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:1010-1025,1134-1138

### SCN-030: Test a connection
- **Persona:** editor
- **Feature:** connections
- **Entry point:** connection row hover → refresh-cw "Test"
- **Preconditions:** a connection exists
- **Steps:**
  1. User clicks Test
- **Expected result:** status dot updates; toast "Connected" on success
- **UI elements:** Test button, StatusDot ("Checking...")
- **States covered:** loading, error, success
- **Errors & recovery:** failure → toast "Not connected: …" and error status stored (`ConnectionSelector.tsx:503-512`)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:1283-1289,1051-1063

### SCN-031: Edit a connection
- **Persona:** owner
- **Feature:** connections
- **Entry point:** connection row hover → pencil (canManageProject) → "Edit Connection"
- **Preconditions:** owner/manager
- **Steps:**
  1. User edits fields (password blank keeps existing)
  2. User clicks "Save Changes"
- **Expected result:** toast "Connection updated"
- **UI elements:** same form as create titled "Edit Connection", Save Changes, Cancel
- **States covered:** loading, error, success
- **Errors & recovery:** name required → toast; SSH/MCP validation as create; update fails → toast (`ConnectionSelector.tsx:398-415,487-491`)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:389-491,1290-1297

### SCN-032: Delete a connection
- **Persona:** owner
- **Feature:** connections
- **Entry point:** connection row hover → trash (canDelete)
- **Preconditions:** owner
- **Steps:**
  1. User clicks trash
  2. Global confirm (critical) lists what will be removed and requires typing `DELETE`
  3. User confirms
- **Expected result:** connection removed; if active, active connection cleared
- **UI elements:** trash ActionButton, ConfirmModal (critical, type-`DELETE`)
- **States covered:** error, success
- **Errors & recovery:** delete fails → toast "Failed to delete connection" (`ConnectionSelector.tsx:606-609`)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:585-599,1307-1315

### SCN-033: Index / re-index a database
- **Persona:** editor
- **Feature:** connections
- **Entry point:** connection row "IDX" / "IDX*" badge (canIndex)
- **Preconditions:** editor/owner; active connection
- **Steps:**
  1. User clicks IDX to (re)index
- **Expected result:** pulsing "IDX..." while running; toast "DB indexed: n/m active tables"
- **UI elements:** IDX badge button, polling status
- **States covered:** loading, success, error
- **Errors & recovery:** timeout → toast; partial evidence → warning toast; failed/poll-lost → toast (`ConnectionSelector.tsx:124-165`). Viewers see a static badge
- **A hard crash resolves to `failed`, never to a permanent spinner (F-SCHED-03, 2026-08-21):** a worker that dies mid-run stops writing `heartbeat_at`, and `StaleRunReaper` flips the row after `stale_running_heartbeat_timeout_seconds` (300 s, ten heartbeat intervals) so the badge shows a failure the user can retry instead of pulsing forever. Three properties this rests on, each held by a test: a **just-started** run is not reaped (its start time is inside the grace window, and `heartbeat()` writes a beat before the first interval); a **long but living** run is not reaped, because the beacon is an independent task and the heavy stages hand their work to a thread; and a run whose age **cannot be established at all** — no heartbeat and no start time — is reaped rather than assumed healthy, since a row nobody can tell is stuck is the one nothing will ever reconcile. A live run flipped by mistake is recoverable: the reap is marked, and `RunCoordinator` reconciles it when the still-running pipeline emits its terminal event.
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:1144-1184,116-165; `backend/app/services/stale_run_reaper.py`; tests `backend/tests/unit/test_stale_run_reaper.py` (12)

### SCN-034: Run code↔DB sync
- **Persona:** editor
- **Feature:** connections
- **Entry point:** connection row "SYNC" badge (canIndex)
- **Preconditions:** editor/owner; DB already indexed
- **Steps:**
  1. User clicks SYNC
- **Expected result:** pulsing "SYNC..."; toast "Code-DB synced: n/m tables matched"
- **UI elements:** SYNC badge button, SyncStatusIndicator line
- **States covered:** loading, success, error
- **Errors & recovery:** timeout → toast; failed → toast "…ensure DB is indexed first" (`ConnectionSelector.tsx:176-215`)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:1190-1247; components/connections/SyncStatusIndicator.tsx:91-132

### SCN-035: Refresh schema cache
- **Persona:** editor
- **Feature:** connections
- **Entry point:** connection row hover → database icon (active, non-MCP, canIndex)
- **Preconditions:** editor/owner; active non-MCP connection
- **Steps:**
  1. User clicks the refresh-schema icon
- **Expected result:** toast "Schema refreshed"
- **UI elements:** refresh-schema icon button
- **States covered:** loading, success, error
- **Errors & recovery:** fails → toast "Schema refresh failed" (`ConnectionSelector.tsx:522-527`)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:1298-1306,515-527

### SCN-036: Connection health & reconnect
- **Persona:** analyst
- **Feature:** connections
- **Entry point:** inline health dot on a connection row / overview; SSE-driven
- **Preconditions:** a connection exists
- **Steps:**
  1. User sees a degraded/down health dot
  2. User clicks "RECONNECT" (appears when down)
- **Expected result:** health re-checks and updates; row banner clears
- **UI elements:** health dot + tooltip, "RECONNECT" button, "Connection is unreachable" row banner
- **States covered:** loading, error, success
- **Errors & recovery:** reconnect fails → toast "Reconnect failed"; fetch failure silent (`ConnectionHealth.tsx:104-106`)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionHealth.tsx:111-151; components/connections/ConnectionSelector.tsx:1318-1323

### SCN-037: Connections — empty state
- **Persona:** owner
- **Feature:** connections
- **Entry point:** Connections panel with no connections, or no project
- **Preconditions:** project active but no connections (or no project)
- **Steps:**
  1. User opens Connections
- **Expected result:** "No connections yet" (or "Select a project first")
- **UI elements:** empty-state text, "New connection" action (owner)
- **States covered:** empty, error
- **Errors & recovery:** connections load failure (project switch) → inline error + Retry in place of the empty state (shared `ListError`, audit M5; `ConnectionSelector.tsx:1511-1516`). Known gap: the connections list has no list-level loading spinner (populated via project switch)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:1511-1523 (error vs empty states), :197 (`handleRetryLoad`); frontend/src/components/workspace/DataWorkspace.tsx ("Select a project first" — the state moved here when `ConnectionsPanel` was deleted); components/ui/ListError.tsx

### SCN-134: Say what a connection is for, in the agent's terms
- **Persona:** editor
- **Feature:** connections
- **Traces:** FLW-02
- **Entry point:** workspace source card → "Describe" (or the card's Edit form → "What is this for?")
- **Preconditions:** editor/owner; the project has at least one connection
- **Steps:**
  1. User opens "Describe" on a source card -> system shows a multi-line field, a character counter against the cap, and one line stating that this text is sent to the agent with every question on this connection
  2. User writes what the source is and how to read it — e.g. "Production billing DB. Money is in minor units. Only rows with `status='settled'` count as revenue." -> system enables Save and shows the remaining characters
  3. User clicks Save -> system persists it on the connection and the card's subtitle changes from "No purpose set" to the first line of the text
  4. User asks a revenue question in chat -> the answer honours the stated rule instead of guessing
- **Expected result:** the description is stored per connection, visible on its card, and demonstrably reaches the agent
- **Alt paths:** user clears the field and saves -> the card reverts to "No purpose set" and the agent stops receiving it; viewer opens the card -> the text renders read-only with no Save
- **UI elements:** "Describe" action, multi-line field, character counter, cap notice, Save / Cancel, card subtitle, "No purpose set" placeholder
- **States covered:** empty, loading, error, success
- **Errors & recovery:** over the cap -> counter turns warning, Save refused with "N characters over the limit", text preserved; save fails -> toast "Could not save the description" and the field keeps the text so nothing is retyped; the field is user-authored text that reaches a prompt, so it is injected as data under its own heading and never as instructions the agent must obey
- **Status:** implemented
> **Delivered end to end 2026-09-08.** The column, the API contract (create AND update, capped identically), the migration and the prompt injection all exist and are tested: a described connection now reaches the SQL agent as `## What the user says these sources are for` — **data under its own heading, attributed, never framed as an instruction**, because a free-text field presented as a rule is an injection channel with a text input attached. The budget drops whole descriptions and names the omitted ones. The place to type it is the Describe affordance on the source card of `SCR-01`, which landed the same day: a failed save keeps the text, and one line states that the agent receives this with every question — a field whose effect is invisible does not get filled in.
- **Coverage:** frontend/src/components/workspace/SourceDescribe.tsx; frontend/src/components/workspace/DataWorkspace.tsx; frontend/src/__tests__/components/DataWorkspace.test.tsx; backend/app/models/connection.py; backend/app/agents/source_purpose.py; backend/app/agents/sql_agent.py (`_load_source_purposes`); backend/app/agents/prompts/sql_prompt.py; backend/app/api/routes/connections.py; backend/alembic/versions/f6a7b8c9d0e1_add_connection_purpose.py; backend/tests/unit/test_source_purpose.py

### SCN-135: The answer shows which source context it was given
- **Persona:** analyst
- **Feature:** connections
- **Traces:** FLW-05
- **Entry point:** chat answer → the seal (SCN-122)
- **Preconditions:** a question was answered against a connection or repository that carries a description
- **Steps:**
  1. User reads an answer and opens its seal -> system lists what the agent was told beyond the schema: the connection description, the repository context, the rules and learnings applied
  2. User clicks one entry -> system shows the exact text that was injected, verbatim
  3. User sees a wrong instruction there and clicks through to its source -> system opens that source card's Describe field with the text loaded for editing
- **Expected result:** no instruction reaches the agent invisibly; every one is inspectable from the answer it shaped, and correctable in one step
- **Alt paths:** nothing beyond the schema was injected -> the seal says so explicitly rather than omitting the section
- **UI elements:** seal, context list, per-entry expander, verbatim text block, "Edit this" link
- **States covered:** empty, success
- **Errors & recovery:** the injected text can no longer be resolved (source deleted since the answer) -> the entry renders with a "source removed" label and the verbatim text is still shown, because what the agent was told is a fact about that answer and does not change when the source does
- **Status:** draft
- **Coverage:** none yet; planned: frontend/src/components/ui/Seal.tsx, planned: backend/app/agents/orchestrator.py (what is recorded per request)

### SCN-136: Source context that did not fit says so
- **Persona:** analyst
- **Feature:** connections
- **Traces:** FLW-05
- **Entry point:** chat answer, when descriptions across sources exceed the prompt budget
- **Preconditions:** the combined source descriptions are over the context cap
- **Steps:**
  1. User asks a question spanning several described sources -> system drops whole descriptions, never part of one, until the set fits
  2. User reads the answer -> the seal states how many descriptions were omitted and names them
- **Expected result:** the answer admits it may not reflect every description, and says which ones it did not see
- **Alt paths:** everything fits -> no notice is shown
- **UI elements:** seal, omitted-context notice with count and names
- **States covered:** success
- **Errors & recovery:** nothing can fail here — the cap is enforced before the call. The rule is inherited deliberately from `rules_to_context`: a half-included description is worse than an excluded one, because the agent cannot tell it was truncated
- **Status:** draft
- **Coverage:** none yet; planned: backend/app/knowledge/custom_rules.py, planned: frontend/src/components/ui/Seal.tsx

## ssh-keys

### SCN-038: Add an SSH key
- **Persona:** owner
- **Feature:** ssh-keys
- **Entry point:** sidebar "SSH Keys" section → "Add"
- **Preconditions:** authenticated
- **Steps:**
  1. User opens Add SSH Key
  2. User enters a name and pastes a private key (+ optional passphrase); optional help guide with copyable commands
  3. User clicks "Add Key"
- **Expected result:** toast "SSH key added"; key row appears with type badge + fingerprint
- **UI elements:** "Add" button, name input, help toggle, private-key textarea, passphrase input, "Add Key" button (Adding…), inline error
- **States covered:** loading, error, success
- **Errors & recovery:** create fails → inline error; button disabled until name+key present (`SshKeyManager.tsx:177,280-288`)
- **Status:** implemented
- **Coverage:** components/ssh/SshKeyManager.tsx:218-290

### SCN-039: Delete an SSH key
- **Persona:** owner
- **Feature:** ssh-keys
- **Entry point:** SSH key row hover → trash "Delete key"
- **Preconditions:** ≥1 SSH key
- **Steps:**
  1. User clicks trash
  2. Global confirm (warning) "Connections using this key will lose SSH tunnel access." appears
  3. User confirms
- **Expected result:** toast "SSH key deleted"; row removed
- **UI elements:** trash ActionButton, ConfirmModal (warning, no type-to-confirm)
- **States covered:** error, success
- **Errors & recovery:** delete fails → toast (`SshKeyManager.tsx:200-203`)
- **Status:** implemented
- **Coverage:** components/ssh/SshKeyManager.tsx:316-324,187-192

### SCN-040: SSH keys — empty state
- **Persona:** owner
- **Feature:** ssh-keys
- **Entry point:** SSH Keys section with no keys
- **Preconditions:** no SSH keys added
- **Steps:**
  1. User opens SSH Keys
- **Expected result:** "No SSH keys added yet"
- **UI elements:** empty-state text, "Add" button, Spinner while loading
- **States covered:** loading, empty, error
- **Errors & recovery:** list load fails → toast "Failed to load SSH keys" (`SshKeyManager.tsx:151-155`)
- **Status:** implemented
- **Coverage:** components/ssh/SshKeyManager.tsx:292,327-331

## chat

### SCN-041: Ask a data question — streaming happy path
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** chat input at the bottom of the chat panel
- **Preconditions:** active project + connection (or knowledge-only), a session
- **Steps:**
  1. User types a question and presses Enter (or clicks send)
  2. Agent streams tokens; plan summary, thinking log, and tool activity appear live
  3. Final answer renders (text/table/chart)
- **Expected result:** an assistant answer with reasoning trace, verification badge, and any visualization
- **UI elements:** auto-growing textarea (grows with content up to 160px, then scrolls; Enter submits / Shift+Enter newline), send button, char-remaining counter, PlanSummaryCard, ThinkingLog, ToolCallIndicator, StageProgress, "■ Stop generating"
- **States covered:** loading, success, error
- **Errors & recovery:** session auto-create fails → toast + abort (`ChatPanel.tsx:423-426`); stream error → in-transcript red "Error: …" bubble with optional Retry (`ChatPanel.tsx:622-644` sets `responseType: "error"` + `isRetryable`; rendered `ChatMessage.tsx:596-597`)
- **Status:** implemented
- **Coverage:** components/chat/ChatPanel.tsx:394-672, :940 and :962 ("■ Stop generating", two placements); components/chat/ChatInput.tsx:12-84 (auto-grow :27-37 capped by `MAX_TEXTAREA_HEIGHT_PX` :13; Enter/Shift+Enter :52; counter :77-78); tests frontend/src/__tests__/components/ChatInput.test.tsx

### SCN-042: Quick-ask from project overview
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** HomeAsk "Ask your data" input on the overview panel
- **Preconditions:** active project + (connection or knowledge mode)
- **Steps:**
  1. User types a question and clicks "Ask"
- **Expected result:** panel switches to chat and the question is submitted
- **UI elements:** text input (maxLength 2000), "Ask" button
- **States covered:** empty/disabled, success
- **Errors & recovery:** disabled with "Add a connection to start asking" when not askable; no inline error surface here (`HomeAsk.tsx:16,43-46`)
- **Status:** implemented
- **Coverage:** components/home/HomeAsk.tsx:16-55; components/chat/ChatPanel.tsx:706-714

### SCN-043: Stop / abort a running answer
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** "■ Stop generating" during streaming
- **Preconditions:** an answer is streaming
- **Steps:**
  1. User clicks Stop
- **Expected result:** stream aborts; any partial text is committed as an assistant message suffixed "*(Generation stopped by user)*"
- **UI elements:** "■ Stop generating" button (in streaming-text and thinking bubbles)
- **States covered:** success
- **Errors & recovery:** none (local abort, no data loss, no confirm). Switching sessions mid-stream also aborts and commits partial text to the previous session
- **Status:** implemented
- **Coverage:** components/chat/ChatPanel.tsx:674-696,925-951

### SCN-044: Empty chat + suggestion chips
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** chat panel with a session but no messages
- **Preconditions:** active session, `messages.length===0`, readiness satisfied
- **Steps:**
  1. User views the empty hero
  2. User clicks a suggestion chip
- **Expected result:** the chip's question is sent
- **UI elements:** animated hero ("Ready to query" / "Knowledge Base Mode"), SuggestionChips (skeleton while loading)
- **States covered:** empty, loading, error, success
- **Errors & recovery:** suggestions fetch fails → toast "Could not load suggestions"; chips hidden (`ChatPanel.tsx:334`)
- **Accessibility:** a chip longer than 60 chars is cut **in the DOM**, not merely clipped by CSS, so it carries `aria-label` with the full question (`SuggestionChips.tsx:55-64`). `title` cannot serve as the accessible name here — the button has text content, and content wins (AUD-0819-08)
- **Status:** implemented
- **Coverage:** components/chat/ChatPanel.tsx:824-851,982-988; components/chat/SuggestionChips.tsx:11-63

### SCN-045: Readiness gate (first-run project)
- **Persona:** new-user
- **Feature:** chat
- **Entry point:** chat panel before the first message when the project isn't ready
- **Preconditions:** `messages.length===0`, not bypassed, not cached-ready
- **Steps:**
  1. User sees a readiness checklist (connect repo/db, index, sync)
  2. User runs a step, or clicks "Chat anyway"
- **Expected result:** steps complete (with success toasts) or user bypasses to chat; auto-bypass when ready & fresh
- **UI elements:** per-step "Run" buttons, navigable connect steps, "Re-index" on stale, "Chat anyway", "Start chatting", Retry on fetch error
- **States covered:** loading, error, success
- **Errors & recovery:** action fails → toast; poll timeout → toast; readiness-check fails → "Failed to check project readiness" + Retry / Chat anyway (`ReadinessGate.tsx:159-199`)
- **Status:** implemented
- **Coverage:** components/chat/ReadinessGate.tsx:74-336; components/chat/ChatPanel.tsx:740-787

### SCN-046: Mid-stream error + retry
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** during/after a streamed answer that errors
- **Preconditions:** a question was sent
- **Steps:**
  1. Stream errors; a red error bubble appears in the transcript
  2. If retryable, user clicks Retry
- **Expected result:** error shown honestly in-transcript; retry re-runs the request
- **UI elements:** red "Error: …" message, Retry button (only when `is_retryable`)
- **States covered:** error
- **Errors & recovery:** this IS the error path; non-retryable errors omit the Retry button (`ChatPanel.tsx:611-621`, `ChatMessage.tsx:605-616`)
- **Status:** implemented
- **Coverage:** components/chat/ChatPanel.tsx:611-633; components/chat/ChatMessage.tsx:605-616

### SCN-047: Knowledge-only chat (no connection)
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** chat panel when no DB connection is configured
- **Preconditions:** active project, no connection
- **Steps:**
  1. User sees "No database connection configured."
  2. User clicks "Chat with Knowledge Base"
- **Expected result:** chat switches to knowledge-only mode; codebase/doc Q&A works
- **"Codebase Q&A" was answered from a summary of the code, not the code (row 2.2, 2026-09-05):** the lexical half of hybrid retrieval was built from `KnowledgeDoc` rows, and their content is the LLM's **generated documentation** of each file. So asking about a function reached the keyword leg only if the model happened to name it in a summary, while the dense leg held the real bodies — two legs, two corpora. Symbol documents (name, signature, decorators, docstring, path, from `code_graph_symbols`) are now in the lexical corpus under the **same ids** the vector store uses, so the legs reinforce one symbol instead of ranking two documents for it. Bodies stay out deliberately: the snapshot must be rebuildable on the web dyno from Postgres alone, with no clone. Paired with row 2.10, without which changing those ids would have orphaned every stored symbol chunk permanently.
- **UI elements:** no-connection message, "Chat with Knowledge Base" button
- **States covered:** empty, success
- **Errors & recovery:** as SCN-041/046 for the stream itself
- **Status:** implemented
- **Coverage:** components/chat/ChatPanel.tsx:756-769

### SCN-048: Create / switch / delete chat sessions
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** sidebar "Chat History" section
- **Preconditions:** active project
- **Steps:**
  1. User clicks "New chat" to start a session, or clicks a session row to switch
  2. User deletes a session via the trash icon → confirm "Delete this chat session?"
- **Expected result:** new/selected session active; deleted session (and cached messages) removed
- **UI elements:** "New chat" action, session rows, per-row trash, "Show all N" expander, ConfirmModal
- **States covered:** loading, empty, error, success
- **Errors & recovery:** load fails → toast; delete fails → toast; create fails → toast (`ChatSessionList.tsx:169-227`). GAP: no rename UI (titles auto-generated) and no bulk clear-history
- **Status:** implemented
- **Coverage:** components/chat/ChatSessionList.tsx:70-276

### SCN-049: Resume in-progress session after leaving
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** returning to a session whose backend is still processing
- **Preconditions:** a prior question is processing in the background
- **Steps:**
  1. User navigates away then back (or reopens the session)
- **Expected result:** "Processing in background…" bubble shows; polling fills in the answer automatically
- **UI elements:** processing bubble, session-row processing spinner
- **States covered:** loading, success
- **Errors & recovery:** network errors during polling are silently retried until the answer arrives or the cap is hit (`useSessionPolling.ts`)
- **Status:** implemented
- **Coverage:** hooks/useSessionPolling.ts; components/chat/ChatPanel.tsx:86-87,956-979

### SCN-050: Pipeline checkpoint — continue/modify/retry
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** a multi-stage pipeline answer that pauses at a checkpoint or fails a stage
- **Preconditions:** complex query routed to the pipeline path
- **Steps:**
  1. User sees the stage list with a checkpoint or failed stage
  2. User clicks "Continue pipeline", "Modify plan" (+ text), or "Retry stage"
- **Expected result:** pipeline resumes per the chosen action
- **UI elements:** StageProgress, StageRow, CheckpointCard (Continue / Modify + input / Retry), "Show all N stages"
- **States covered:** loading, success, error
- **Errors & recovery:** failed stage shows inline red error text; Retry/Modify appear when any stage failed (`StageRow.tsx:114-118`, `StageProgress.tsx:160-176`)
- **Status:** implemented
- **Coverage:** components/chat/StageProgress.tsx:73-176; components/chat/CheckpointCard.tsx:91-148; components/chat/ChatPanel.tsx:883-911

### SCN-051: Answer a clarification request
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** an assistant message of type `clarification_request`
- **Preconditions:** the agent needs disambiguation
- **Steps:**
  1. User answers via yes/no, multiple-choice, free-text, or numeric-range control
- **Expected result:** the answer is sent as a follow-up; "You answered: …" recorded
- **UI elements:** ClarificationCard inputs
- **States covered:** success
- **Errors & recovery:** none surfaced (submit just sends a message)
- **Status:** implemented
- **Coverage:** components/chat/ClarificationCard.tsx:42-121; components/chat/ChatMessage.tsx:411-417

### SCN-052: Rate an answer & report wrong data
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** thumbs up / down on an assistant message
- **Preconditions:** an assistant answer exists
- **Steps:**
  1. User clicks thumbs up or thumbs down
  2. On thumbs-down for a SQL result, an investigation prompt is auto-sent
- **Expected result:** the rating is recorded; a thumbs-down on a SQL answer **auto-sends a canned investigation prompt as the user's next message** ("I flagged the previous query result as incorrect…"), and the agent answers it like any other question. Two further effects carry the invariant and are the reason this scenario is not merely a rating: the backend **rolls back the learnings that answer exposed** (`exposed_learning_ids`), so a wrong answer does not keep teaching, and the client writes a **parallel `validate-data` verdict** for the connection
- **UI elements:** thumbs up/down buttons (disabled while submitting)
- **States covered:** loading, error, success
- **Errors & recovery:** submit fails → toast "Failed to submit feedback" (`ChatMessage.tsx:243`). The `validate-data` write is deliberately fire-and-forget (`.catch(() => {})`): it is a second opinion on the same click, and failing it must not lose the rating
- **Not built:** the richer `WrongDataModal` investigation flow. The Expected result above describes what ships — this line says what does not, which is the distinction the previous wording collapsed: its Expected result promised the modal flow while its own note said a canned prompt, so a reader taking the Expected result as the contract got the opposite of what ships (BIZ-14)
- **Status:** implemented
- **Coverage:** components/chat/ChatMessage.tsx:216-245 (handler), :223-235 (the parallel validate-data write), :243 (the failure toast), :637-668 (the two buttons); backend/app/api/routes/chat_feedback.py:77-94 (the learning rollback)

### SCN-053: Save an answer to notes
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** bookmark button on an assistant SQL message
- **Preconditions:** an SQL-result answer exists
- **Steps:**
  1. User clicks the bookmark
- **Expected result:** toast "Query saved to notes"; note prepended and Saved Queries panel opens; button flips to "Saved to notes"
- **UI elements:** bookmark button (pulses while saving, disabled once saved)
- **States covered:** loading, success, error
- **Errors & recovery:** save fails → toast "Failed to save note" (`ChatMessage.tsx:322-323`)
- **Status:** implemented
- **Coverage:** components/chat/ChatMessage.tsx:297-327,682-694

### SCN-054: View the agent reasoning panel
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** the reasoning icon on an assistant message (shown only when a trace exists)
- **Preconditions:** the message has a captured reasoning trace
- **Steps:**
  1. User opens the reasoning panel
- **Expected result:** Plan (tables/strategy/rules/learnings/warnings), Thinking log, and per-step timeline with elapsed time (per-step `elapsed_ms` rendered next to each step, overall elapsed in the header)
- **UI elements:** reasoning toggle button, ReasoningPanel (close X, mobile bottom-sheet)
- **States covered:** empty ("No reasoning data available"), success
- **Errors & recovery:** none (trace is in-store; no async fetch). Button hidden when no trace
- **Status:** implemented
- **Coverage:** components/chat/ReasoningPanel.tsx:42-95 (per-step elapsed :42-44,88-92),:96-224; components/chat/ChatMessage.tsx:104-130; tests frontend/src/__tests__/components/ReasoningPanel.test.tsx

### SCN-055: Step-limit reached → continue analysis
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** an answer returned with `response_type: step_limit_reached`
- **Preconditions:** the agent hit its live step budget
- **Steps:**
  1. User clicks "Continue analysis"
- **Expected result:** the agent resumes from where it stopped
- **The wall clock is one budget for the whole request (F-SQL-03, 2026-08-21):** on the multi-stage path a failing stage is replanned up to `max_pipeline_replans` times, and every replan spends from the *same* deadline the first attempt started. When it is spent the request returns the failed stage's result rather than starting another plan — so a hard question ends in a bounded time with an honest partial answer plus "Continue analysis", instead of running three full budgets back to back. Before this each replan started a fresh budget, so a request whose documented limit is `agent_wall_clock_timeout_seconds` could occupy roughly three times that with the user watching a spinner.
- **The answer says what it did not reach (2026-09-02):** the synthesis prompt used for this path carried, verbatim, "Do NOT mention step limits, partial results, or that anything was cut short — present this as a complete answer." That function is reached only when the step budget is spent, so the instruction applied to every answer on this scenario: the badge said partial and the text said finished. The prompt now tells the model the run stopped at its budget and asks it to name, in one short closing sentence, which part of the question it did not reach. Honest in both directions — when the collected data does fully answer the question it is told to add **no** caveat, because a caveat invented for a complete answer teaches the reader to discount every caveat after it.
- **The badge is now reached at all (row 1.7, 2026-09-05):** this scenario's entry point is `response_type: step_limit_reached`, and the orchestrator handed it out only when the partial answer already looked bad. With rows on the table and the partial-answer validator approving, the exhausted-budget branch returned the **ordinary** type, so a cut-off run was typed `sql_result` and `sealStateFor` (`components/ui/Seal.tsx:73-91`) sealed it **Verified** — contradicting SCN-122 below, which states that a budget-exhausted run seals Unverified *even when a query is attached*. The branch now types every cut-off run `step_limit_reached`. The validator is still called, for the errors-screen signal it raises, not for the type: it is asked whether the answer addresses the question and can only see the answer and the question, never the data the run did not reach — a partial answer judged against itself cannot say the cut-off did not matter. **Nothing had ever executed this branch**: no test in the suite exhausted the step budget (`tests/unit/test_cutoff_is_visible_to_the_reader.py`, 4 cases, 1 red before).
- **A crashed quality gate now reaches this scenario too (row 2.9, 2026-09-05):** the flat loop answers a validator exception by consulting `answer_validator_fail_closed` (default on) and downgrading, so an unverifiable answer arrives here labelled. The multi-stage path answered the same exception with a bare `return None`, which `build_pipeline_response` reads as **accept** — so one question got two safety postures depending on which path a router the user cannot see had chosen, and only the crashing case differed, which is why no test compared them. The old behaviour was documented as "fail-open to avoid blocking a successful pipeline", and the fear does not match the mechanism: a non-accept directive maps to `step_limit_reached`, which **preserves the answer text** and adds this scenario's CTA. Nothing was ever blocked, so the fail-open bought nothing and paid an unverified answer for it. `warn`, not `block`: parity here is about labelling honestly, not withholding. `tests/unit/test_pipeline_gate_fails_the_same_way.py` (5 cases, 1 red before).
- **UI elements:** "Continue analysis" button
- **States covered:** success, partial (the answer names what it did not reach)
- **Errors & recovery:** as the normal stream (SCN-046)
- **Status:** implemented
- **Coverage:** components/chat/ChatMessage.tsx:619-642; components/chat/ChatPanel.tsx:215-315; backend/app/agents/response_builder.py:335-356; tests backend/tests/unit/test_synthesis_prompt_honesty.py

### SCN-056: Session-continuation (auto-summary) banner
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** a message of type `session_continuation` after auto-summary near the context limit
- **Preconditions:** session rotation triggered
- **Steps:**
  1. User expands "Conversation continued (N messages summarized)"
- **Expected result:** a summary preview + topic chips explain what was carried over
- **UI elements:** SessionContinuationBanner (collapsible)
- **States covered:** success
- **Errors & recovery:** none
- **Status:** implemented
- **Coverage:** components/chat/SessionContinuationBanner.tsx:18-60; components/chat/ChatMessage.tsx:252-262

## viz

### SCN-057: View & switch chart type
- **Persona:** analyst
- **Feature:** viz
- **Entry point:** a chat SQL result that produced a visualization
- **Preconditions:** an answer with a visualization
- **Steps:**
  1. User toggles Visual/Text view
  2. User switches chart type (Table/Bar/Line/Pie/Scatter) in the toolbar
- **Expected result:** the chart re-renders as the chosen type
- **A money total reached this scenario as prose (row 2.7, 2026-09-05):** the single-cell fast path in `viz_agent.py` chose `viz_type="number"` on `isinstance(val, (int, float))`, which is **False for `Decimal`** — the type asyncpg returns for a Postgres `NUMERIC` and the one `connectors/mongodb.py:134` converts `Decimal128` into deliberately. So `SELECT count(*)` produced a number card and `SELECT sum(revenue)` fell through to `viz_type="text"`: the product rendered counts as numbers and money as prose, on a question ("what is total revenue?") that is among the most common a user asks. A boolean single cell now renders as text rather than the number card, deliberately — `SELECT is_active` is not a metric, and `bool` reached the card only because it subclasses `int`. `tests/unit/test_money_is_not_invisible.py`.
- **UI elements:** Visual/Text toggle, VizToolbar type buttons (spinner while re-rendering), mobile "Tap to view chart"
- **States covered:** loading, empty, error, success
- **Errors & recovery:** re-render fails → toast "Failed to re-render visualization" and type reverts (`SQLResultSection.tsx:85-88`)
- **Status:** implemented
- **Coverage:** components/viz/VizToolbar.tsx:61-80; components/viz/VizRenderer.tsx:8-25; components/chat/SQLResultSection.tsx:70-181

### SCN-058: Export a result (CSV / JSON / XLSX)
- **Persona:** analyst
- **Feature:** viz
- **Entry point:** DataTable export buttons on a result
- **Preconditions:** a tabular result
- **Steps:**
  1. User clicks CSV, JSON, or XLSX
- **Expected result:** file downloads in the chosen format
- **UI elements:** CSV/JSON/XLSX buttons, "show all rows" (cap 500)
- **States covered:** success, error
- **Errors & recovery:** export fails → toast "Export failed" (`DataTable.tsx:34-36`)
- **Status:** implemented
- **Coverage:** components/viz/DataTable.tsx:49-112

### SCN-059: Compound multi-query results
- **Persona:** analyst
- **Feature:** viz
- **Entry point:** an answer that returned ≥2 SQL results
- **Preconditions:** compound query
- **Steps:**
  1. User views each "Query i of N" block with its own viz/text toggle and SQL
- **Expected result:** each result block renders independently with its own chart and insights
- **UI elements:** SQLResultSection per-block header, per-block toolbar/SQLExplainer/InsightCards
- **States covered:** loading, success, error
- **Errors & recovery:** per-block viz re-render error → toast (`SQLResultSection.tsx:85-87`)
- **Status:** implemented
- **Coverage:** components/chat/ChatMessage.tsx:419-432; components/chat/SQLResultSection.tsx:97-208

### SCN-060: Chart render failure → table fallback
- **Persona:** analyst
- **Feature:** viz
- **Entry point:** a chart that throws while rendering
- **Preconditions:** viz data that the chart cannot render
- **Steps:**
  1. Chart render throws
- **Expected result:** inline "Chart could not be rendered / Try Table view" (no crash, no toast)
- **UI elements:** chart error-boundary card, "No chart data available" / "Unsupported chart type" fallbacks
- **States covered:** error, empty
- **Errors & recovery:** this IS the fallback; user switches to Table view (`ChartRenderer.tsx:64-91,220-226`)
- **Status:** implemented
- **Coverage:** components/viz/ChartRenderer.tsx:64-116,205-229

## knowledge

### SCN-061: Browse indexed docs
- **Persona:** analyst
- **Feature:** knowledge
- **Entry point:** sidebar "Knowledge" → Docs tab
- **Preconditions:** a repo has been indexed
- **Steps:**
  1. User clicks a doc row to open it in the inline viewer
  2. User closes the viewer or expands "Show all N"
- **Expected result:** the doc's content renders inline
- **UI elements:** Docs/Insights/Metrics tabs, doc rows, "Show all N", close-viewer (X), Spinner
- **States covered:** loading, empty, error, success
- **Errors & recovery:** list load fails → toast; doc open fails → toast (`KnowledgeDocs.tsx:54,76-79`). Empty: "No indexed documents yet."
- **Status:** implemented
- **Coverage:** components/knowledge/KnowledgeDocs.tsx:92-173; components/knowledge/KnowledgeHub.tsx:74-106

### SCN-062: Knowledge health & re-index actions
- **Persona:** editor
- **Feature:** knowledge
- **Entry point:** Project Overview → Knowledge Health panel
- **Preconditions:** editor/owner; a project with connections/repo
- **Steps:**
  1. User reviews artifact counts and freshness
  2. User triggers "Re-index" (repo), "Index DB", or "Sync"
  3. User can Cancel a running run or Retry a failed one, and expand History
- **Expected result:** the chosen pipeline starts (toast "… started"); RunCard shows live progress
- **UI elements:** refresh button, artifact-count chips, RunCard (trigger / Cancel / Retry / History), freshness action buttons
- **States covered:** loading, error, success
- **Errors & recovery:** health fetch fails → "Could not load knowledge health"; trigger fails → toast "Action failed"; run failed → inline red text; RunCard Cancel/Retry failures toast "Failed to cancel run" / "Failed to retry run" (`KnowledgeHealthPanel.tsx:129-164`, `RunCard.tsx:82,91`)
- **Status:** implemented
- **Coverage:** components/knowledge/KnowledgeHealthPanel.tsx:138-253; components/knowledge/RunCard.tsx:58-139

### SCN-063: Knowledge freshness warnings
- **Persona:** analyst
- **Feature:** knowledge
- **Entry point:** Knowledge Health panel freshness section (also injected into agent prompts)
- **Preconditions:** DB-index age / sync status / Git HEAD drift computed
- **Steps:**
  1. User reads freshness state
- **Expected result:** "Everything is fresh", a running-pipeline banner, or a severity-tagged warnings list (info/warning/critical) with per-warning actions
- **UI elements:** pipeline-running banner, fresh state, warnings list + action buttons
- **States covered:** loading, success, empty
- **Errors & recovery:** health fetch fails → inline "Could not load knowledge health"
- **Status:** implemented
- **Coverage:** components/knowledge/KnowledgeHealthPanel.tsx:158-251

### SCN-064: Nightly sync history
- **Persona:** owner
- **Feature:** knowledge
- **Entry point:** Project Overview → Sync History panel (above Knowledge Health)
- **Preconditions:** scheduled daily syncs have run (or not)
- **Steps:**
  1. User reviews the latest run summary and expands earlier runs
- **Expected result:** per-run outcomes with error messages when failed
- **UI elements:** refresh button, per-run expanders, "Show all N runs"
- **States covered:** loading, empty, error, success
- **Errors & recovery:** fetch fails → inline "Could not load sync history" (`SyncHistoryPanel.tsx:162-166`). Empty: "No scheduled syncs yet."
- **Status:** implemented
- **Coverage:** components/knowledge/SyncHistoryPanel.tsx:146-201

### SCN-144: Refresh the documentation and see what changed
- **Persona:** editor
- **Feature:** knowledge
- **Traces:** FLW-04
- **Entry point:** workspace → Documentation group → "Refresh docs"
- **Preconditions:** editor/owner; at least one repository is connected and indexed
- **Steps:**
  1. User clicks "Refresh docs" -> system states before starting what the job is: which repository, how many documents are due, that it calls an LLM, and a duration estimate from the last measured rate
  2. User confirms -> system starts the run and shows a live RunCard with the current document number out of the total
  3. User navigates away and returns -> system still shows the run in progress, because the work continues server-side
  4. Run completes -> system shows a change summary: documents added, updated, unchanged, failed
- **Expected result:** the documentation is regenerated and the user can see what actually changed, not merely that something ran
- **Alt paths:** user declines at the estimate -> nothing starts; a run is already active -> the button offers to open the running one instead of queueing a second
- **UI elements:** "Refresh docs" button, pre-run estimate panel (repository, document count, duration, "this calls an LLM"), Confirm / Cancel, RunCard with per-document progress, change-summary table
- **States covered:** loading, empty, error, success
- **Errors & recovery:** partial failure under `generate_docs_max_failure_ratio` -> run completes and the summary counts the failed documents by name rather than reporting success; over the ratio -> run fails with the reason; the run is reaped as stale -> the summary says so and offers a retry, never a silent gap
- **Status:** draft
- **Coverage:** none yet; planned: frontend/src/components/knowledge/KnowledgeDocs.tsx, planned: backend/app/knowledge/pipeline_runner.py (the `generate_docs` step it drives), planned: backend/app/api/routes/repos.py

### SCN-145: A document says where it came from and how old it is
- **Persona:** analyst
- **Feature:** knowledge
- **Traces:** FLW-04
- **Entry point:** workspace → Documentation group → a document row, or the Docs tab of SCN-061
- **Preconditions:** documents have been generated
- **Steps:**
  1. User opens a document -> system shows its source path, the commit it was generated from, and when
  2. User compares against the repository's current head -> system labels the document `current` when the commit matches, or `behind by N commits` when it does not
  3. User clicks a stale label -> system offers the refresh of SCN-144 scoped to that repository
- **Expected result:** every document carries its provenance, and a stale one is labelled rather than served as current
- **Alt paths:** the document predates repository tracking and has no commit -> the label reads "provenance unknown", which is a different claim from "current"
- **UI elements:** document viewer, source-path line, commit chip, generated-at timestamp, freshness label (`current` / `behind by N` / `provenance unknown`), "Refresh this repository" link
- **States covered:** loading, empty, error, success
- **Errors & recovery:** the head cannot be read (clone missing or unreachable) -> the label degrades to "cannot compare" and says why, instead of defaulting to `current`
- **Status:** draft
- **Coverage:** none yet; planned: frontend/src/components/knowledge/KnowledgeDocs.tsx, planned: backend/app/api/routes/repos.py (the docs list already returns `commit_sha` and `updated_at`)

## insights

### SCN-065: View & filter the insights feed
- **Persona:** analyst
- **Feature:** insights
- **Entry point:** sidebar "Knowledge" → Insights tab
- **Preconditions:** the system has generated insights
- **Steps:**
  1. User filters by severity (all/critical/warning/info/positive)
  2. User expands an insight card
- **Expected result:** filtered insight cards render
- **UI elements:** severity filter buttons, insight cards, Spinner
- **States covered:** loading, empty, error, success
- **Errors & recovery:** load fails → inline "Couldn't load insights" + Retry (`InsightFeedPanel.tsx:314-327`). Empty: "No insights yet."
- **Status:** implemented
- **Coverage:** components/insights/InsightFeedPanel.tsx:282-347

### SCN-066: Confirm / dismiss / resolve an insight
- **Persona:** analyst
- **Feature:** insights
- **Entry point:** insight card actions
- **Preconditions:** an insight card is visible
- **Steps:**
  1. User clicks Confirm, Dismiss, or Resolved
- **Expected result:** toast ("Insight confirmed" / "dismissed" / "marked as resolved"); card updates
- **UI elements:** Confirm / Dismiss / Resolved buttons
- **States covered:** error, success
- **Errors & recovery:** each action fails → its own toast (`InsightFeedPanel.tsx:230-260`). Note: Dismiss has no confirm dialog. "Investigate" drill-down is not wired at this entry point
- **Accessibility:** the card's expand toggle carries `aria-expanded` + `aria-controls` pointing at the detail region (`InsightFeedPanel.tsx:94-97,123`); the chevron that shows the state visually is `aria-hidden`, so without them an open card was indistinguishable from a closed one (AUD-0819-09)
- **Status:** implemented
- **Coverage:** components/insights/InsightFeedPanel.tsx:138-175,223-263

### SCN-067: Browse the metric catalog
- **Persona:** analyst
- **Feature:** insights
- **Entry point:** sidebar "Knowledge" → Metrics tab
- **Preconditions:** metrics exist
- **Steps:**
  1. User searches / filters by category
- **Expected result:** matching metrics list
- **UI elements:** search input, category filter buttons, metric rows
- **States covered:** loading, empty, error, success
- **Errors & recovery:** catalog fetch failure propagates a distinct error state + Retry, rendered separately from the "No metrics found" empty state (`KnowledgeHub.tsx:43-62`, `MetricCatalogPanel.tsx:118-145`)
- **Status:** implemented
- **Coverage:** components/insights/MetricCatalogPanel.tsx:75-169

## notes

### SCN-068: Saved-queries panel (scopes & empty)
- **Persona:** analyst
- **Feature:** notes
- **Entry point:** bookmark toggle in the app header (auto-opens after a note is saved)
- **Preconditions:** authenticated
- **Steps:**
  1. User switches scope (All / Mine / Shared)
  2. User reviews saved queries
- **Expected result:** notes list for the scope; scope-aware empty copy when none
- **UI elements:** scope tabs, "Batch" button (≥2 notes), close (X), skeletons
- **States covered:** loading, empty, error, success
- **Errors & recovery:** load fails → toast "Failed to load saved queries" then empty state (`notes-store.ts:78-82`)
- **Status:** implemented
- **Coverage:** components/notes/NotesPanel.tsx:82-126; stores/notes-store.ts:58-82

### SCN-069: Run a saved query
- **Persona:** analyst
- **Feature:** notes
- **Entry point:** NoteCard "Refresh" (run) button
- **Preconditions:** a saved query with a connection
- **Steps:**
  1. User clicks Refresh on a note
- **Expected result:** query re-executes; toast "Query executed successfully"; refreshed result injected into chat + inline result table (first 20 rows)
- **UI elements:** Refresh button (spins), inline result table
- **States covered:** loading, error, success
- **Errors & recovery:** result error → toast "Query error: …"; execution throws → toast "Execution failed" (`NoteCard.tsx:97-123`). Disabled when no connection
- **Status:** implemented
- **Coverage:** components/notes/NoteCard.tsx:93-127,210-238

### SCN-070: Share / unshare a saved query
- **Persona:** analyst
- **Feature:** notes
- **Entry point:** NoteCard share toggle (owner only)
- **Preconditions:** user owns the note
- **Steps:**
  1. User toggles Share/Unshare
- **Expected result:** note visibility changes; other project members can see shared notes
- **UI elements:** share/unshare toggle
- **States covered:** error, success
- **Errors & recovery:** toggle fails → toast "Failed to update sharing" (`NoteCard.tsx:136-137`)
- **Status:** implemented
- **Coverage:** components/notes/NoteCard.tsx:129-141,194-206

### SCN-071: Edit a saved-query comment
- **Persona:** analyst
- **Feature:** notes
- **Entry point:** NoteCard comment editor (owner)
- **Preconditions:** user owns the note
- **Steps:**
  1. User opens the comment editor, edits, Saves
- **Expected result:** comment saved on the note
- **UI elements:** comment textarea, Save, Cancel
- **States covered:** error, success
- **Errors & recovery:** save fails → toast "Failed to save comment" (`NoteCard.tsx:149-150`). Non-owners see a read-only comment
- **Status:** implemented
- **Coverage:** components/notes/NoteCard.tsx:143-152,247-281

### SCN-072: Delete a saved query
- **Persona:** analyst
- **Feature:** notes
- **Entry point:** NoteCard Delete (owner)
- **Preconditions:** user owns the note
- **Steps:**
  1. User clicks Delete
  2. Confirm "Delete this saved query?" (destructive) appears
  3. User confirms
- **Expected result:** toast "Note deleted"; note removed
- **UI elements:** Delete button, ConfirmModal (destructive)
- **States covered:** error, success
- **Errors & recovery:** delete fails → toast "Failed to delete" (`NoteCard.tsx:88-89`)
- **Status:** implemented
- **Coverage:** components/notes/NoteCard.tsx:81-91,219-226

## learnings

### SCN-073: View agent learnings
- **Persona:** editor
- **Feature:** learnings
- **Entry point:** connection row "LEARN {n}" pill → Learnings modal
- **Preconditions:** the connection has ≥1 learning
- **Steps:**
  1. User opens the modal, filters by category, sorts (confidence/newest/most confirmed/most applied)
- **Expected result:** learnings grouped by category with confidence bars and confirmed/applied counts
- **UI elements:** category filter pills, sort dropdown, learning rows, skeleton
- **States covered:** loading, empty, error, success
- **Errors & recovery:** load fails → inline error "Failed to load learnings" + Retry in place of the empty state (toast kept; shared `ListError`, audit M5) (`LearningsPanel.tsx:67-68` message + toast, `:307-311` inline error + Retry)
- **Status:** implemented
- **Coverage:** components/learnings/LearningsPanel.tsx:240-456; components/ui/ListError.tsx; tests frontend/src/__tests__/components/LearningsPanel.test.tsx

### SCN-074: Confirm/contradict/edit/deactivate a learning
- **Persona:** editor
- **Feature:** learnings
- **Entry point:** per-learning hover actions (canEdit)
- **Preconditions:** editor/owner
- **Steps:**
  1. User confirms (upvote), contradicts (downvote), edits text, or toggles active/inactive
- **Expected result:** the learning's confidence/active state updates
- **UI elements:** confirm/contradict/edit/activate/delete icons, edit textarea + Save/Cancel
- **States covered:** error, success
- **Errors & recovery:** each action fails → its own toast; single Delete → confirm "Delete this learning?" (`LearningsPanel.tsx:68-140`)
- **Status:** implemented
- **Coverage:** components/learnings/LearningsPanel.tsx:323-400

### SCN-075: Recompile learnings
- **Persona:** editor
- **Feature:** learnings
- **Entry point:** Learnings modal "Recompile" (canEdit)
- **Preconditions:** editor/owner
- **Steps:**
  1. User clicks Recompile
- **Expected result:** toast "Learnings prompt recompiled"
- **UI elements:** Recompile button
- **States covered:** error, success
- **Errors & recovery:** fails → toast "Failed to recompile" (`LearningsPanel.tsx:109`). No confirm (non-destructive)
- **Status:** implemented
- **Coverage:** components/learnings/LearningsPanel.tsx:103-110,216-224

### SCN-076: Clear all learnings
- **Persona:** owner
- **Feature:** learnings
- **Entry point:** Learnings modal "Clear all" (canDelete)
- **Preconditions:** owner
- **Steps:**
  1. User clicks "Clear all"
  2. Confirm (critical) requires typing `DELETE`
  3. User confirms
- **Expected result:** toast "Cleared N learnings"
- **UI elements:** "Clear all" button, ConfirmModal (critical, type-`DELETE`)
- **States covered:** error, success
- **Errors & recovery:** fails → toast "Failed to clear" (`LearningsPanel.tsx:156`)
- **Status:** implemented
- **Coverage:** components/learnings/LearningsPanel.tsx:142-158,227-233

## rules

### SCN-077: Create a custom rule
- **Persona:** editor
- **Feature:** rules
- **Entry point:** sidebar "Custom Rules" → "New rule" (canEdit)
- **Preconditions:** editor/owner
- **Steps:**
  1. User enters a name and rule content
  2. User clicks Create
- **Expected result:** toast "Rule created"; rule appears in the list
- **UI elements:** name input, content textarea, Create, Cancel
- **States covered:** loading, error, success
- **Errors & recovery:** create fails → toast "Failed to create rule" (`RulesManager.tsx:97-101`). Requires non-empty name+content. Cancel closes the modal and discards the draft (same `cancel()` as edit mode)
- **Status:** implemented
- **Coverage:** components/rules/RulesManager.tsx:62-70,168-176,201-234; tests frontend/src/__tests__/components/RulesManager.test.tsx

### SCN-078: Edit a custom rule
- **Persona:** editor
- **Feature:** rules
- **Entry point:** rule row click (canEdit)
- **Preconditions:** editor/owner
- **Steps:**
  1. User edits name/content
  2. User clicks Save (disabled unless dirty)
- **Expected result:** toast "Rule updated"
- **UI elements:** name input, content textarea, Save, Cancel; default-rule warning banner
- **States covered:** error, success
- **Errors & recovery:** update fails → toast "Failed to update rule" (`RulesManager.tsx:140-144`)
- **Status:** implemented
- **Coverage:** components/rules/RulesManager.tsx:117-123,195-225

### SCN-079: Delete a custom rule (default vs normal)
- **Persona:** editor
- **Feature:** rules
- **Entry point:** rule row Delete (canEdit)
- **Preconditions:** editor/owner
- **Steps:**
  1. User clicks Delete
  2. Confirm appears — for the default metrics rule the copy warns it won't be re-created
  3. User confirms
- **Expected result:** rule removed
- **UI elements:** Delete button, ConfirmModal (message differs for default rule)
- **States covered:** error, success
- **Errors & recovery:** delete fails → toast "Failed to delete rule" (`RulesManager.tsx:158-163`)
- **Status:** implemented
- **Coverage:** components/rules/RulesManager.tsx:150-163,282-290

### SCN-080: View a rule read-only
- **Persona:** viewer
- **Feature:** rules
- **Entry point:** rule row click as a viewer
- **Preconditions:** viewer role
- **Steps:**
  1. User opens a rule
- **Expected result:** read-only `<pre>` view; no edit/delete affordances
- **UI elements:** read-only modal, "default"/"global" badges
- **States covered:** empty ("No custom rules yet"), success
- **Errors & recovery:** list load fails → toast (no inline error)
- **Status:** implemented
- **Coverage:** components/rules/RulesManager.tsx:117-123,186-192,294-298

## dashboards

### SCN-081: Dashboard list & empty state
- **Persona:** analyst
- **Feature:** dashboards
- **Entry point:** sidebar "Dashboards" section
- **Preconditions:** authenticated
- **Steps:**
  1. User reviews the dashboard list
  2. User clicks a dashboard to open `/dashboard/{id}`
- **Expected result:** dashboards listed (shared ones flagged); navigates to the viewer
- **UI elements:** "New dashboard" action (canEdit), dashboard rows, shared icon, Spinner, "Retry"
- **States covered:** loading, empty, error, success
- **Errors & recovery:** list load fails → inline "Couldn't load dashboards" + Retry (`DashboardList.tsx:76-85`). Empty: "No dashboards yet"
- **Status:** implemented
- **Coverage:** components/dashboards/DashboardList.tsx:41-104

### SCN-082: Create a dashboard from saved queries
- **Persona:** editor
- **Feature:** dashboards
- **Entry point:** "New dashboard" → DashboardBuilder (FormModal)
- **Preconditions:** editor/owner; ≥1 saved query
- **Steps:**
  1. User names the dashboard, picks a column layout
  2. User adds cards from saved queries
  3. User clicks "Save Dashboard"
- **Expected result:** toast "Dashboard created"; dashboard saved
- **UI elements:** title input, layout toggle, "Add Card" + picker, per-card remove, "Refresh All", Save, Cancel
- **States covered:** loading, empty, error, success
- **Errors & recovery:** missing title → toast "Title is required"; save fails → toast; notes load fails → toast (`DashboardBuilder.tsx:74-77,101-102,53`)
- **Status:** implemented
- **Coverage:** components/dashboards/DashboardBuilder.tsx:131-230

### SCN-083: Edit a dashboard / refresh all
- **Persona:** editor
- **Feature:** dashboards
- **Entry point:** `/dashboard/{id}` "Edit" (owner/editor) or DashboardBuilder in edit mode
- **Preconditions:** owner/editor of the dashboard
- **Steps:**
  1. User edits title/cards
  2. User clicks "Refresh All" and "Save Dashboard"
- **Expected result:** toast "Dashboard saved"; refresh summary toast
- **UI elements:** DashboardBuilder controls, "Refresh All", deleted-note card "This query was deleted"
- **States covered:** loading, error, success
- **Errors & recovery:** refresh partial failures → toast "Refreshed: N succeeded, M failed"; duplicate add → toast "Note already on dashboard" (`DashboardBuilder.tsx:60-63,114-123`). Remove-card has no confirm
- **Status:** implemented
- **Coverage:** components/dashboards/DashboardBuilder.tsx:158-278; app/dashboard/[id]/page.tsx:224-234

### SCN-084: View a shared dashboard
- **Persona:** viewer
- **Feature:** dashboards
- **Entry point:** `/dashboard/{id}` (auth-gated)
- **Preconditions:** authenticated viewer with access to the dashboard
- **Steps:**
  1. User opens the dashboard link
- **Expected result:** header + card grid render; auto-refresh per card interval; viewers see no Edit/Add
- **UI elements:** "Back to app", "Refresh All", card grid, ResultTable (cap 50 rows), per-card data-age label, late marker, per-card refresh error
- **States covered:** loading, empty, error, success, **stale**
- **Data age, and what the label must be able to say (F-VIZ-01):** every card names *when its data was produced* — "Data from 3d ago", or "Never run" — because the page header already says "Updated …" about the dashboard itself and a second, bare relative age beside a title reads as the same measurement. Age alone cannot separate the two ways a card gets old, so the card distinguishes them:
  - A card with **no declared `refresh_interval`** is simply as old as the last person who ran it. That is not a fault and carries no marker.
  - A card that **declared an interval** has promised how old its figures may get. When its data exceeds twice that interval (one missed tick is normal — the interval only runs while a tab is open) the card says so: "This card is not refreshing on its schedule — the figures below are older than it promises." A broken promise is a different fact from an old number and must not render identically to it.
- **Refreshing on open:** opening a dashboard reads stored snapshots and executes nothing — **except** cards that declared an interval and are already past due, which run once, sequentially, as they paint. `setInterval` fires first only after a full period, so without this a card promising hourly data can show a days-old figure for an hour with that promise attached. Cards with no declared interval are never executed by opening the page.
- **Errors & recovery:** empty → "This dashboard has no cards yet."; per-card "No data" / "Note not found". A failed refresh — on open, on a tick, or from Refresh All — is shown on the card itself ("Last refresh failed: …") and cleared by the next success; a card whose query started failing must never look like a card nobody refreshed. Refresh-All tracks per-card success/failure and toasts the real counts — "Refreshed: N succeeded, M failed" (error toast when M>0, info when all pass)
- **Status:** implemented
- **Coverage:** app/dashboard/[id]/page.tsx:113-419; `frontend/src/__tests__/components/DashboardPage.test.tsx` (8)

### SCN-085: Shared dashboard link invalid / expired
- **Persona:** viewer
- **Feature:** dashboards
- **Entry point:** `/dashboard/{id}` with a bad/expired/forbidden id, or unauthenticated
- **Preconditions:** invalid id OR no access OR not logged in
- **Steps:**
  1. User opens the link
- **Expected result:** unauthenticated → redirect to `/login`; otherwise "Dashboard not found" + "Back to app" and a toast carrying the error
- **UI elements:** AuthGate redirect, "Dashboard not found" screen, "Back to app" button, toast
- **States covered:** error
- **Errors & recovery:** GAP — invalid/expired/forbidden all collapse to one "Dashboard not found" screen (no distinct "expired" or "no access" copy) (`app/dashboard/[id]/page.tsx:104-132,206-218`)
- **Status:** implemented
- **Coverage:** app/dashboard/[id]/page.tsx:87-132,206-218; components/auth/AuthGate.tsx:16-20

### SCN-086: Delete a dashboard
- **Persona:** editor
- **Feature:** dashboards
- **Entry point:** sidebar Dashboards list → per-row trash button (hover-revealed)
- **Preconditions:** owner/editor of the project (`canEdit`)
- **Steps:**
  1. User hovers a dashboard row and clicks the trash button (aria-label "Delete dashboard")
  2. Confirm "Delete this dashboard?" (destructive) appears
  3. User confirms
- **Expected result:** `api.dashboards.delete` called; row removed from the list; toast "Dashboard deleted"; the row's navigate-to-dashboard click is not triggered (stopPropagation)
- **UI elements:** per-row trash button (Tooltip "Delete dashboard", gated to `canEdit`), ConfirmModal (destructive)
- **States covered:** success (row removed + toast), cancelled (no-op), permission (button hidden for viewers)
- **Errors & recovery:** delete fails → toast "Failed to delete dashboard"; row stays; cancel on confirm → no-op
- **Status:** implemented
- **Coverage:** components/dashboards/DashboardList.tsx:66-76 (handleDelete), 122-135 (trash button, `canEdit`-gated); tests `__tests__/components/DashboardList.test.tsx`

## batch

### SCN-087: Run a batch of queries
- **Persona:** analyst
- **Feature:** batch
- **Entry point:** app header "Batch query runner" button → BatchRunner modal
- **Preconditions:** active project + connection
- **Steps:**
  1. User titles the batch, picks a connection
  2. User adds queries (title + SQL), reorders/removes them
  3. User clicks "Run All (N)"
- **Expected result:** progress bar + "Running queries… current/total"; toast on terminal status
- **UI elements:** title input, connection select, per-query inputs + move/remove, "Add Query", "Run All (N)", progress bar
- **States covered:** loading, error, success
- **Errors & recovery:** no connection → toast; no valid queries → toast; start fails → toast; partial/failed terminal → toast; poll lost (≥10) → toast "Lost connection to batch" (`BatchRunner.tsx:106-169`)
- **Status:** implemented
- **Coverage:** components/batch/BatchRunner.tsx:194-327

### SCN-088: Build a batch from saved notes
- **Persona:** analyst
- **Feature:** batch
- **Entry point:** Saved Queries panel "Batch" (≥2 notes) or BatchRunner "From Saved Notes"
- **Preconditions:** ≥2 saved notes
- **Steps:**
  1. User opens the note picker, checks queries, clicks "Add (N)"
  2. User runs the batch
- **Expected result:** selected saved queries pre-populate the batch
- **UI elements:** NotePicker (checkboxes, Cancel, "Add (N)"), "From Saved Notes" button
- **States covered:** empty ("No saved notes"), success
- **Errors & recovery:** as SCN-087
- **Status:** implemented
- **Coverage:** components/batch/BatchRunner.tsx:302-415; components/notes/NotesPanel.tsx:54-78

### SCN-089: View batch results
- **Persona:** analyst
- **Feature:** batch
- **Entry point:** BatchRunner auto-opens BatchResults when the batch reaches a terminal status (`BatchRunner.tsx:174-176`)
- **Steps:**
  1. On mount, `api.batch.get(batchId)` is fetched and `results_json` parsed
  2. Each per-query record renders as a titled block — success → result table (DataTable) with total_rows + duration; failed/blocked → the honest error text (+ SQL)
  3. User can Export the whole batch (xlsx blob download), go Back to the runner, or Close
- **Expected result:** per-query outputs/errors shown; export downloads `api.batch.export` blob; Back/Close wired to `onBack`/`onClose`
- **UI elements:** header (Back button, title, Export button, Close button), per-query success tables + error blocks, spinner, Retry button
- **States covered:** loading (spinner), loaded (per-query success/failed blocks), empty ("Batch is still running…" / "No results"), error (fetch failed → message + Retry)
- **Errors & recovery:** fetch fails → "Couldn't load batch results" + Retry; per-query failure/blocked → error text shown inline; export fails → toast
- **Status:** implemented
- **Coverage:** components/batch/BatchResults.tsx:49-236 (fetch/parse :59-71, loading :159-163, error + Retry :164-175, empty :176-182, per-query blocks :183-236, export :84-92); handoff components/batch/BatchRunner.tsx:174-176; tests `__tests__/components/BatchResults.test.tsx`

## schedules

### SCN-090: Create a scheduled query + alerts
- **Persona:** owner
- **Feature:** schedules
- **Entry point:** sidebar "Schedules" → "New schedule" (owner) → FormModal
- **Preconditions:** owner; ≥1 connection
- **Steps:**
  1. User enters title + SQL, picks a connection (if >1), sets a cron preset or custom expression
  2. User optionally adds alert conditions (column/operator/threshold)
  3. User clicks Create
- **Expected result:** toast "Schedule created"; schedule appears in the list
- **UI elements:** title/SQL inputs, connection select, cron preset/custom toggle, alert-condition rows, Create
- **States covered:** loading, error, success
- **Errors & recovery:** validation toasts (title/SQL/cron/connection); save fails → toast "Failed to save" (`ScheduleManager.tsx:251`; success toast `:246`); list load fails → inline error + Retry in place of the empty state (shared `ListError`, audit M5; `ScheduleManager.tsx:346-350`)
- **Status:** implemented
- **Coverage:** components/schedules/ScheduleManager.tsx:444-612; components/ui/ListError.tsx; tests frontend/src/__tests__/components/ScheduleManager.test.tsx

### SCN-091: Edit / pause / run-now a schedule
- **Persona:** owner
- **Feature:** schedules
- **Entry point:** schedule row actions
- **Preconditions:** ≥1 schedule
- **Steps:**
  1. User toggles pause/activate, clicks "Run now", or "Edit"
- **Expected result:** run-now executes (toast on status); pause/activate flips state; edit reopens the form prefilled
- **UI elements:** pause/activate toggle, "Run now", "History", "Edit"
- **States covered:** loading, error, success
- **Errors & recovery:** run failed → toast "Scheduled query failed"; alert_triggered → info toast; toggle fails → toast "Toggle failed" (`ScheduleManager.tsx:264-287`)
- **Status:** implemented
- **Coverage:** components/schedules/ScheduleManager.tsx:358-403

### SCN-092: Delete a schedule
- **Persona:** owner
- **Feature:** schedules
- **Entry point:** schedule row trash
- **Preconditions:** ≥1 schedule
- **Steps:**
  1. User clicks trash
  2. Confirm "Delete this schedule?" (destructive) appears
  3. User confirms
- **Expected result:** toast "Schedule deleted"; row removed
- **UI elements:** trash button, ConfirmModal (destructive)
- **States covered:** error, success
- **Errors & recovery:** delete fails → toast "Failed to delete" (`ScheduleManager.tsx:256-257`)
- **Status:** implemented
- **Coverage:** components/schedules/ScheduleManager.tsx:249-259

### SCN-093: View schedule run history
- **Persona:** owner
- **Feature:** schedules
- **Entry point:** schedule row "History" expander
- **Preconditions:** a schedule has run
- **Steps:**
  1. User expands History (last 10 runs)
- **Expected result:** per-run outcomes listed
- **UI elements:** History expander rows
- **States covered:** loading, empty, error
- **Errors & recovery:** history load fails → toast "Failed to load run history" and empties (`ScheduleManager.tsx:303-306`). Empty: "No runs yet"
- **Status:** implemented
- **Coverage:** components/schedules/ScheduleManager.tsx:407-440

## analytics

### SCN-094: Feedback analytics panel
- **Persona:** owner
- **Feature:** analytics
- **Entry point:** sidebar "Analytics" section
- **Preconditions:** owner
- **Steps:**
  1. User reviews confidence score, verdict breakdown, and top errors
- **Expected result:** metrics render; first-run shows guidance to rate results
- **UI elements:** ConfidenceScore bar, MiniStats, VerdictBar (hover tooltips), top-errors list, "Retry"
- **States covered:** loading, empty, error, success
- **Errors & recovery:** fetch fails → inline "Failed to load analytics" + Retry (`FeedbackAnalyticsPanel.tsx:62-69`). Empty: "No validation data yet…"
- **Status:** implemented
- **Coverage:** components/analytics/FeedbackAnalyticsPanel.tsx:43-224

## settings

### SCN-095: Open settings & navigate
- **Persona:** analyst
- **Feature:** settings
- **Entry point:** app header gear button → SettingsPanel
- **Preconditions:** authenticated
- **Steps:**
  1. User opens settings
  2. User navigates to Edit Project / Manage Connections / Team & Invites (owner) / MCP tokens, or opens account actions
- **Expected result:** the chosen surface opens; account and project sections reflect the user's permissions
- **UI elements:** close button, Change Password, Sign Out, Delete Account, Edit Project, Manage Connections, Team & Invites, McpTokenManager, Terms/Privacy links
- **States covered:** empty (sections hidden when no user/project), error, success
- **Errors & recovery:** password/delete errors → toasts (see SCN-009/010). Note: no loading state on panel open
- **Status:** implemented
- **Coverage:** components/settings/SettingsPanel.tsx:47-189

### SCN-096: Change theme (light / system / dark)
- **Persona:** analyst
- **Feature:** settings
- **Entry point:** Account menu → Appearance → ThemeToggle
- **Preconditions:** authenticated
- **Steps:**
  1. User picks Light, System, or Dark
- **Expected result:** theme applied immediately and persisted (`cmd_theme`); System tracks OS changes
- **UI elements:** 3 segmented buttons (aria-pressed)
- **States covered:** success
- **Errors & recovery:** none surfaced (storage failures swallowed). Default is Light on first run
- **Status:** implemented
- **Coverage:** components/theme/ThemeToggle.tsx:37-58; stores/theme-store.ts:27-58; components/theme/ThemeWatcher.tsx:9-17

### SCN-097: Reduced-motion honored
- **Persona:** analyst
- **Feature:** settings
- **Entry point:** OS "reduce motion" preference (no in-app toggle)
- **Preconditions:** OS prefers-reduced-motion enabled
- **Steps:**
  1. User has reduced motion enabled at the OS level
- **Expected result:** animations/transitions are neutralized app-wide (CSS + Framer MotionConfig + chart animations off)
- **UI elements:** (no control — OS-driven)
- **States covered:** success
- **Errors & recovery:** n/a. Note: there is intentionally no in-app reduced-motion toggle
- **Status:** implemented
- **Coverage:** app/globals.css:23-31; app/app/page.tsx:384; components/viz/ChartRenderer.tsx:142-145

## billing

### SCN-098: Upgrade via pricing → Stripe checkout
- **Persona:** owner
- **Feature:** billing
- **Entry point:** `/pricing` plan CTA, or BillingPanel "Upgrade"
- **Preconditions:** billing enabled; user logged in for a paid plan
- **Steps:**
  1. User picks a paid plan CTA
  2. App redirects to Stripe Checkout
- **Expected result:** browser navigates to Stripe to complete payment
- **UI elements:** per-plan CTA button ("Redirecting…"), FAQ
- **States covered:** loading, error, success (external)
- **Errors & recovery:** billing not live → toast "Billing is not enabled on this deployment"; checkout fails → toast "Checkout failed" (`PricingTable.tsx:101,109`). The logged-out paid CTA routes to `/login?next=/pricing` and `/login` now honors a safe same-origin `next` after auth (returning the visitor to `/pricing`; protocol-relative / absolute-URL values are rejected — open-redirect guard)
- **Status:** implemented
- **Coverage:** components/marketing/PricingTable.tsx:91-166

### SCN-099: Manage billing (Stripe portal)
- **Persona:** owner
- **Feature:** billing
- **Entry point:** sidebar "Usage" (owner) → BillingPanel "Manage billing"
- **Preconditions:** owner on a paid plan
- **Steps:**
  1. User clicks "Manage billing"
- **Expected result:** redirect to the Stripe Customer Portal (cancel/update happen there)
- **UI elements:** "Manage billing" button ("Opening…"), plan/status badges, usage bars, past-due / cancel-at-period-end notices
- **States covered:** loading, error, success (external)
- **Errors & recovery:** portal open fails → toast "Could not open billing portal" (`BillingPanel.tsx:98`). Note: no in-app cancel/confirm — delegated to Stripe
- **Status:** implemented
- **Coverage:** components/billing/BillingPanel.tsx:92-160

### SCN-100: Hit token / quota limit (HTTP 402)
- **Persona:** analyst
- **Feature:** billing
- **Entry point:** any API call that exceeds plan/token limits
- **Preconditions:** billing on; user over their limit
- **Steps:**
  1. User triggers a call that returns 402
- **Expected result:** the caller surfaces "Plan limit reached. Upgrade at /pricing to continue." (typically a toast / chat error bubble)
- **UI elements:** toast / chat error message
- **States covered:** error
- **Errors & recovery:** the client appends the paywall payload's own `upgrade_url` when the message does not already name it, and the toast surface renders any "/pricing" mention as a clickable upgrade link (`lib/api/_client.ts:140-159`, `components/ui/ToastContainer.tsx:18-30`). Before 2026-08-19 the link depended on the prose happening to contain the route, so the token-budget message (`usage_service.py:140`) was actionable while the connection/project quota messages ("Plan 'free' allows 1 connection(s); you have 1.") were not — AUD-0819-11
- **Status:** implemented
- **Coverage:** lib/api/_client.ts:140-159; `__tests__/api.test.ts` "plan paywall (402)"

### SCN-101: Billing disabled (self-hosted) degradation
- **Persona:** owner
- **Feature:** billing
- **Entry point:** any billing surface when the backend has billing off (routes 404)
- **Preconditions:** self-hosted with billing disabled
- **Steps:**
  1. User opens billing-related surfaces
- **Expected result:** BillingPanel renders nothing; PricingTable keeps the static catalog and paid CTA toasts "Billing is not enabled on this deployment"; usage still works via `/usage`
- **UI elements:** (BillingPanel hidden), PricingTable fallback catalog + toast
- **States covered:** empty, error
- **Errors & recovery:** subscription 404 caught → panel renders nothing (`BillingPanel.tsx:79-81,87`)
- **Status:** implemented
- **Coverage:** components/billing/BillingPanel.tsx:79-87; components/marketing/PricingTable.tsx:73-102

### SCN-101a: Billing on, no subscription (unpaid account)
- **Persona:** owner
- **Feature:** billing
- **Entry point:** any product surface while `billing_enabled=True` and the account has no subscription row, or one that is `canceled` / `unpaid` / `incomplete`
- **Preconditions:** billing enabled; no active or grace-period subscription
- **Steps:**
  1. User asks a question, indexes a repository, or adds a connection
- **Expected result:** the work proceeds and **scheduled work does not** (SCN-146). There is no free tier to fall to, so entitlements resolve to plan id `"none"` with every limit `0` (unlimited by this codebase's convention) and the plan catalogue is not consulted; the only ceiling that applies is the deployment-wide `USER_DAILY_TOKEN_LIMIT` / `USER_MONTHLY_TOKEN_LIMIT`. What changed on 2026-09-07 is not a limit but a capability: unattended work is withheld.
- **UI elements:** no paywall, no 402; `/pricing` shows only tiers that have a live Stripe price, otherwise the self-hosted fallback
- **States covered:** success, empty (no plan)
- **Errors & recovery:** none by design — this state degrades **open**. Before 2026-09-06 it resolved to the retired `free` plan and inherited its 100 000-token daily ceiling, which on production refused a code↔DB sync behind a 1 666 411-token index and pointed the operator at `/pricing`, a page that cannot take payment while no Stripe keys are set.
- **Decision taken 2026-09-07:** neither blocked nor fully open. Setting the product up and using it by hand stays open; **scheduled** work needs a subscription. Both binary options were on the table and the third answer is better than either: blocking an unpaid project makes the product unevaluable, and serving unattended nightly LLM work to accounts that pay nothing is the cost this tier exists to meter. `EntitlementService._no_plan()` is still the single place it lives.
> **Previously.** This scenario was `implemented` and audited PASS on 2026-09-06. The
> 2026-09-07 decision changed the behaviour it describes, so it is back to `draft`
> and owes a fresh audit. The old verdict is recorded here rather than in the Index's
> audit cell, because a date and a `PASS` in that cell are counted as a live
> verification — which would have made a draft read as verified.
- **Status:** implemented
- **Coverage:** backend/app/services/entitlement_service.py (`_no_plan`); backend/tests/unit/test_four_tiers_priced_by_data_volume.py

### SCN-146: Set up a project without a subscription — the work proceeds, the schedule does not
- **Persona:** owner
- **Feature:** billing
- **Traces:** FLW-01
- **Entry point:** any setup surface while `billing_enabled=True` and the account has no active subscription
- **Preconditions:** billing enabled; no active or grace-period subscription
- **Steps:**
  1. User creates a project, connects sources, connects a repository and describes them -> system allows all of it, with no paywall and no 402
  2. User presses Index on a source or a repository -> system runs it, because a manual action is the user asking for work they are watching
  3. User asks a question in chat -> system answers, subject only to the deployment-wide token caps
  4. Night falls -> system does **not** run the nightly knowledge sync, the analytics collection wave, or any scheduled query for this account
  5. User opens the workspace the next morning -> system shows the sources exactly as they were, and says the schedule did not run and why
- **Expected result:** an unpaid account can set the product up and use it by hand; only **unattended** work is withheld
- **Alt paths:** `billing_enabled=False` (self-hosted) -> automation runs normally, because the registry never installs the commercial provider and the permissive default answers instead; the account has a granted plan -> automation runs per SCN-148
- **UI elements:** no paywall on any setup surface; a schedule notice in the workspace and on the Schedules surface; the upgrade route from that notice only
- **States covered:** success, empty (no plan)
- **Errors & recovery:** nothing fails — this is a withheld capability, not an error. The withheld thing is named where it would have happened rather than in a billing page the user has no reason to open
- **Status:** implemented
- **Coverage:** backend/app/entitlements/base.py (`may_run_scheduled_work`, the fourth protocol method); backend/app/entitlements/__init__.py (the module helper that degrades to allowed); backend/app/entitlements/unlimited.py; backend/app/services/entitlement_service.py; backend/app/main.py (`_dispatch_daily_knowledge_sync_wave`, `_dispatch_analytics_collect_wave`, `_scheduler_loop`); backend/tests/unit/test_scheduled_work_needs_a_plan.py

### SCN-147: The schedule says why it is off and what turns it on
- **Persona:** owner
- **Feature:** billing
- **Traces:** FLW-01, FLW-04
- **Entry point:** workspace → the project's sync-hour control; Schedules surface
- **Preconditions:** the account may not run scheduled work
- **Steps:**
  1. User opens the sync-hour control -> system shows it disabled with one sentence: scheduled syncs need a subscription, and manual indexing does not
  2. User reads the Repositories group -> each card says `last indexed manually` rather than implying a nightly refresh that will not happen
  3. User follows the upgrade route -> system opens the plans surface; if no plan has a live Stripe price, it says so instead of offering a page that cannot take payment
- **Expected result:** the absence of automation is visible where the user would expect the automation, and it is never mistaken for a failure
- **Alt paths:** the account may run scheduled work -> the control is editable and this notice never appears
- **UI elements:** disabled sync-hour control with its reason, per-card `last indexed manually` label, upgrade route, the self-hosted fallback message when Stripe is unconfigured
- **States covered:** empty, success
- **Errors & recovery:** the entitlement cannot be read -> the control renders disabled with "could not check your plan" and a retry; it does not default to enabled, because promising a nightly run that will not happen is the failure this scenario exists to prevent
- **Status:** implemented
- **Coverage:** frontend/src/components/workspace/DataWorkspace.tsx (the sync-hour control and its reason); backend/app/api/routes/projects.py (`sync-schedule` reports `may_run`); backend/app/entitlements/__init__.py; backend/tests/integration/test_sync_schedule_may_run.py; frontend/src/__tests__/components/DataWorkspace.test.tsx

### SCN-148: A granted account behaves exactly as its plan
- **Persona:** owner
- **Feature:** billing
- **Traces:** FLW-01
- **Entry point:** none — the grant is operator configuration, and the account simply behaves as its plan
- **Preconditions:** the deployment grants a plan to a named account without Stripe
- **Steps:**
  1. Operator names the account and the plan in configuration -> system reconciles a subscription row for it at start-up, idempotently, without contacting Stripe
  2. User signs in -> system resolves the granted plan's entitlements: its quotas, its token ceilings, and its right to run scheduled work
  3. Night falls -> system runs the nightly sync for that account like any paid one
  4. Operator removes the grant -> system returns the account to no-plan at the next start-up, and the schedule stops
- **Expected result:** a comped account is indistinguishable from a paying one in behaviour, and the grant is a recorded configuration rather than a hand-edited row
- **Alt paths:** the granted plan id does not exist in the catalogue -> the grant is refused at start-up with a log line naming it, and the account stays on no-plan rather than resolving to something unintended
- **UI elements:** none of its own; the billing surface shows the granted plan's name and no Stripe portal link, because there is no Stripe subscription to manage
- **States covered:** success
- **Errors & recovery:** the reconcile cannot run -> it logs and never blocks boot, and the account degrades to no-plan, which is the safe direction for a grant. A granted row carries **no** `stripe_subscription_id`, which is what keeps `BillingService.reconcile` from cancelling it — that path already filters on the column being non-null and names manual grants as the reason
- **Status:** implemented
- **Coverage:** backend/app/ops/plan_grant_reconcile.py; backend/app/config.py (`plan_grants`); backend/app/main.py (reconciled in the lifespan, after the catalogue); backend/app/services/billing_service.py (`reconcile` skips rows with no Stripe id); backend/tests/unit/test_scheduled_work_needs_a_plan.py

## usage

### SCN-102: View usage stats
- **Persona:** owner
- **Feature:** usage
- **Entry point:** sidebar "Usage" (full) or Project Overview "Usage Summary" (compact)
- **Preconditions:** authenticated (owner for sidebar entry)
- **Steps:**
  1. User reviews token/usage stats over the last 30 days
- **Expected result:** stat cards + a daily bar chart (full) or compact rows
- **UI elements:** StatCards, MiniBarChart, "Retry" on error
- **States covered:** loading, empty, error, success
- **Errors & recovery:** fetch fails → inline "Failed to load usage stats" + Retry (`UsageStatsPanel.tsx:67-92`)
- **Status:** implemented
- **Coverage:** components/usage/UsageStatsPanel.tsx:65-176

## mcp-tokens

### SCN-103: Mint & copy an MCP token
- **Persona:** api-consumer
- **Feature:** mcp-tokens
- **Entry point:** Settings → McpTokenManager → "New"
- **Preconditions:** authenticated
- **Steps:**
  1. User opens the create modal, names the token, sets expiry days
  2. User clicks "Create token"
  3. User copies the issued token (shown once) and optional Claude Desktop config
- **Expected result:** token created; issued-token modal shows the value + copy buttons
- **UI elements:** "New", name input, expiry input, "Create token", issued-token box + copy, config `<details>`, "I've saved it"
- **States covered:** loading, empty, error, success
- **Errors & recovery:** empty name → toast; bad expiry → toast; create fails → toast; copy fails → toast (`McpTokenManager.tsx:87-104,49`). Empty: "No MCP tokens yet."
- **Status:** implemented
- **Coverage:** components/mcp/McpTokenManager.tsx:147-283

### SCN-104: Revoke an MCP token
- **Persona:** api-consumer
- **Feature:** mcp-tokens
- **Entry point:** McpTokenManager token row "Revoke" (live tokens only)
- **Preconditions:** ≥1 live token
- **Steps:**
  1. User clicks "Revoke"
  2. Global confirm (warning, type `Revoke`) appears
  3. User confirms
- **Expected result:** toast "Token revoked"; row reflects revoked status
- **UI elements:** "Revoke" button, ConfirmModal (warning, type-`Revoke`)
- **States covered:** error, success
- **Errors & recovery:** revoke fails → toast "Failed to revoke token" (`McpTokenManager.tsx:121`)
- **Status:** implemented
- **Coverage:** components/mcp/McpTokenManager.tsx:110-198

## tasks

### SCN-105: Background tasks — view/cancel/retry/dismiss
- **Persona:** analyst
- **Feature:** tasks
- **Entry point:** ActiveTasksWidget pill in the app header
- **Preconditions:** ≥1 background run for the active project
- **Steps:**
  1. User expands the widget
  2. User cancels a running task, retries a failed one, or dismisses a finished one
- **Expected result:** task list with live progress; the chosen action applies
- **UI elements:** toggle pill (count), per-task Cancel / Retry / Dismiss, progress bars, elapsed timer
- **States covered:** empty (renders null), loading, error, success
- **Errors & recovery:** Cancel/Retry failures toast "Failed to cancel task" / "Failed to retry task" (`ActiveTasksWidget.tsx:119-149`). Cancel has no confirm (the run is reversible by re-triggering)
- **Status:** implemented
- **Coverage:** components/tasks/ActiveTasksWidget.tsx:105-278

## logs

### SCN-106: Request history & trace detail
- **Persona:** owner
- **Feature:** logs
- **Entry point:** sidebar "Request History" → LogsScreen (Queries tab)
- **Preconditions:** active project
- **Steps:**
  1. User filters by date range and status, paginates the request list
  2. User clicks a request to open its trace detail (expandable spans)
- **Expected result:** requests listed; trace spans with input/output/token detail
- **UI elements:** date filter, tabs, request list + status filter + pagination, LogsTraceDetail span tree
- **States covered:** loading, empty, error, success
- **Errors & recovery:** queries load fails → banner "Failed to load logs" + Retry, visible on all three tabs (not only Queries — audit L6; `LogsScreen.tsx:76,147-154`); trace fails → inline "Failed to load trace" (set `LogsTraceDetail.tsx:45`, rendered `:63-66`)
- **Status:** implemented
- **Coverage:** components/logs/LogsScreen.tsx:104-216; components/logs/LogsTraceDetail.tsx:44-141; tests frontend/src/__tests__/components/LogsScreenTabs.test.tsx

### SCN-107: Runs & Errors log tabs
- **Persona:** owner
- **Feature:** logs
- **Entry point:** LogsScreen → Runs / Errors tabs
- **Preconditions:** active project
- **Steps:**
  1. User opens Runs (filter by kind) or Errors (filter source/status)
  2. In Errors, user cycles a row's status open → ack → resolved
- **Expected result:** runs / error rows listed on the same 32px ledger geometry the result table uses (SCN-124) — a 12px muted header over a hairline, hairline dividers, counts and timestamps in the data face with tabular figures; error status cycles. **A status shows a dot AND its word**: the dot carries the hue and the word stays in the primary ink, because every status colour in this design sits under AA on the light field
- **UI elements:** kind select + Refresh (Runs), source/status selects + Refresh + status-cycle chip (Errors)
- **States covered:** loading, empty, error, success
- **Errors & recovery:** Runs/Errors fetch failures render an inline error message + Retry (shared `ListError`, matching the Queries tab banner), distinct from the empty state; Errors status-cycle failure toasts the error (`RunsTab.tsx:17-29,63`, `ErrorsTab.tsx:25-41,97`)
- **Status:** implemented
- **Coverage:** components/logs/RunsTab.tsx; components/logs/ErrorsTab.tsx; components/shadcn/table.tsx; components/ui/StatusDot.tsx; components/ui/ListError.tsx

### SCN-108: Live activity log stream
- **Persona:** analyst
- **Feature:** logs
- **Entry point:** floating Live Activity toggle → LogPanel
- **Preconditions:** authenticated in `/app`
- **Steps:**
  1. User opens the live log; events stream in
  2. User clears or closes the panel
- **Expected result:** streamed log lines with an unread badge; Clear wipes the in-memory log
- **UI elements:** toggle (unread badge, connection dot), LogPanel, "Clear", "Close"
- **States covered:** empty ("Waiting for events..."), success
- **Errors & recovery:** disconnection reflected only by the status dot (no toast/inline error). Clear has no confirm (non-persistent data)
- **Status:** implemented
- **Coverage:** components/log/LogPanel.tsx:131-259

## marketing

### SCN-109: Landing page → Get Started
- **Persona:** visitor
- **Feature:** marketing
- **Entry point:** `/` (marketing home)
- **Preconditions:** anonymous visitor
- **Steps:**
  1. Visitor reads the landing page and clicks "Get Started Free"
- **Expected result:** navigates to `/login`
- **UI elements:** hero/final "Get Started Free" CTAs, "View on GitHub", star count (hidden on fetch failure), FAQ accordion
- **States covered:** success, empty(partial)
- **Errors & recovery:** GitHub stars fetch fails → star count silently hidden, no visible error (`page.tsx:227-229`)
- **Status:** implemented
- **Coverage:** app/(marketing)/page.tsx:429-434,976-981; components/marketing/FaqAccordion.tsx:34-60

### SCN-110: Pricing CTA (logged out)
- **Persona:** visitor
- **Feature:** marketing
- **Entry point:** `/pricing`
- **Preconditions:** anonymous visitor
- **Steps:**
  1. Visitor clicks a plan CTA (free or paid)
- **Expected result:** free → `/login`; paid → `/login?next=/pricing`
- **UI elements:** per-plan CTA, static FAQ
- **States covered:** loading, success
- **Errors & recovery:** the `next=/pricing` intent is now honored — after login/register `/login` redirects to a safe same-origin `next` (`/pricing`), with an open-redirect guard rejecting `//host` / absolute-URL values (`login/page.tsx` `resolveRedirect`; test `frontend/src/__tests__/components/LoginPage.test.tsx`)
- **Status:** implemented
- **Coverage:** components/marketing/PricingTable.tsx:91-99; redirect honored in frontend/src/app/login/page.tsx

### SCN-111: Support / Contact / Legal pages
- **Persona:** visitor
- **Feature:** marketing
- **Entry point:** header/footer links to `/support`, `/contact`, `/about`, `/terms`, `/privacy`
- **Preconditions:** anonymous or authenticated
- **Steps:**
  1. Visitor opens a static page and uses its links (email, GitHub, docs, FAQ)
- **Expected result:** static content renders; links work (mailto / external / cross-links)
- **UI elements:** FAQ `<details>` (support), mailto links (contact), legal sections, cross-links
- **States covered:** success (static)
- **Errors & recovery:** none. Note: contact page is mailto links only — there is no contact form
- **The data-handling claim is a measurement, not a slogan (2026-09-02):** four of these pages — privacy, terms, about and the support FAQ — stated that query results are transient and never stored on our servers. Measured against production: **55 of 131** chat messages carry a `raw_result` key, **39** contain a `rows` array, and **213 of 213** `db_index` rows carry sampled live column values. The product's whole ask is production database credentials, so this was the one promise a security review would test, and it was false. The pages now say what is kept (the result table behind an answer, capped at `chat_raw_result_row_cap` = 500 rows; a sample of distinct values per column, for query correctness), and what deletes it (the chat, the connection, the project, the account). `tests/unit/docs/test_privacy_claims_match_storage.py` fails if the old sentence returns or if the cap the pages quote stops matching the setting.
- **Status:** implemented
- **Coverage:** app/(marketing)/support/page.tsx:117-249; app/(marketing)/contact/page.tsx:90-156; tests backend/tests/unit/docs/test_privacy_claims_match_storage.py

### SCN-112: Logged-in visitor auto-redirect to /app
- **Persona:** analyst
- **Feature:** marketing
- **Entry point:** `/` while already authenticated
- **Preconditions:** authenticated session restored
- **Steps:**
  1. A logged-in user opens the marketing home
- **Expected result:** silent redirect to `/app` (no loading UI)
- **UI elements:** (none — AuthRedirect returns null)
- **States covered:** success
- **Errors & recovery:** none
- **Status:** implemented
- **Coverage:** components/auth/AuthRedirect.tsx:12-22

## analytics-sources

<!-- External report APIs (GA4 · App Store Connect · Google Play) cached per connection
     with provenance and TTL — see docs/adr/0001-external-report-cache.md and
     docs/superpowers/specs/2026-08-01-m0-ga4-spine-design.md. A `planned:` prefix on a
     Coverage entry marks a file that does not exist yet (allowed only while draft). -->

### SCN-113: Add a Google Analytics 4 connection
- **Persona:** owner
- **Feature:** analytics-sources
- **Entry point:** Connections → "New connection" → source type "Google Analytics 4"
- **Preconditions:** project owner; at least one `ga4` vendor credential already saved (SCN-114)
- **Steps:**
  1. User opens New Connection and picks "Google Analytics 4" as the source type
  2. The DB/SSH/read-only fields disappear; a credential picker, GA4 property ID, backfill-days, collection-hour and a "Collect automatically" toggle appear
  3. User selects a stored `ga4` credential, enters the property ID (e.g. `294380179`), and leaves backfill at 30 days and the hour at 03
  4. User submits
- **Expected result:** connection created with `source_type=ga4` and no host/port/database; it appears in the list with a GA4 badge and collects at the chosen hour (or immediately via "Collect now", SCN-115)
- **UI elements:** source-type select ("Google Analytics 4"), credential select + "＋ new credential" affordance, property-ID input, backfill-days input, collection-hour select, "Collect automatically" toggle, Save button
- **States covered:** loading, empty (no credentials saved yet), error, success
- **Errors & recovery:** submitting without a credential → toast and the credential select is marked invalid; a property not shared with the service account → 403 → `AnalyticsPermissionError` surfaced as "grant Viewer on this property"; a credential owned by another user → 404 (owner-strict); create fails → toast, form keeps its values
- **Status:** implemented
- **Audit note (2026-08-19):** verified against shipped code, AUD-0819-15. These nine shipped in `[1.16.0]` and stayed `draft` with `Last audit: —` for a month, which is the drift the scenario-first rule exists to prevent: the base is the source of truth only while it is kept current.
- **Coverage:** components/connections/ConnectionSelector.tsx

### SCN-114: Add / delete a vendor credential
- **Persona:** owner
- **Feature:** analytics-sources
- **Entry point:** Sidebar → Setup group → "Vendor credentials" section → "Add" (mirrors the SSH-keys section, SCN-038/039); also reachable inline from the GA4 connection form's "＋ New credential"
- **Preconditions:** authenticated
- **Steps:**
  1. User opens Vendor credentials and clicks Add
  2. User enters a name, picks the provider "Google Analytics 4", and pastes the service-account JSON into the write-only paste area
  3. User clicks "Add credential"
  4. Later, to remove one: user hovers the credential row, clicks the trash and confirms
- **Expected result:** the secret is stored Fernet-encrypted; the row shows name, provider badge, fingerprint and the service-account `client_email` — never the secret itself. Delete removes an unreferenced credential with a toast
- **UI elements:** "Add" button, name input, provider select, service-account JSON textarea (`aria-label`, write-only), "Add credential" button, credential rows with provider badge + fingerprint, trash ActionButton, ConfirmModal
- **States covered:** loading, empty, error, success
- **Errors & recovery:** malformed service-account JSON → 422 with a specific inline message and nothing stored; create fails → inline error; the secret is never echoed back — reopening a row shows only the fingerprint; another user's credential is never listed; delete refused while a connection still uses it → SCN-116
- **Status:** implemented
- **Audit note (2026-08-19):** verified against shipped code, AUD-0819-15. These nine shipped in `[1.16.0]` and stayed `draft` with `Last audit: —` for a month, which is the drift the scenario-first rule exists to prevent: the base is the source of truth only while it is kept current.
- **Coverage:** components/settings/VendorCredentialsPanel.tsx

### SCN-115: Analytics collection status — ok / partial / pending periods
- **Persona:** editor
- **Feature:** analytics-sources
- **Entry point:** the collection row in a GA4 connection's health area (`ConnectionHealth`)
- **Preconditions:** a GA4 connection exists (SCN-113)
- **Steps:**
  1. User opens Connections and looks at the GA4 connection's collection row
  2. User reads the outcome badge, the latest collected period per report, and the pending-period list
  3. User clicks "Collect now" to fill a gap without waiting for the scheduled hour
- **Expected result:** the badge reads `ok` / `partial` / `failed` distinctly; `partial` additionally names the periods still pending and the last error; "Collect now" enqueues exactly one job and the row switches to running
- **UI elements:** collection row, outcome badge (ok/partial/failed), last-run timestamp, per-report latest-ok period, pending-period list, next scheduled hour, "Collect now" button (`aria-label` + Tooltip)
- **States covered:** loading, empty (never collected), success, partial, error
- **Errors & recovery:** a period collected with zero rows reads as collected-zero, **not** as pending — the never-collected and the zero cases must render differently; a period that failed stays pending and is refilled on the next run; status fetch fails → inline error + Retry; "Collect now" fails → toast
- **Status:** implemented
- **Audit note (2026-08-19):** verified against shipped code, AUD-0819-15. These nine shipped in `[1.16.0]` and stayed `draft` with `Last audit: —` for a month, which is the drift the scenario-first rule exists to prevent: the base is the source of truth only while it is kept current.
- **Coverage:** components/connections/ConnectionHealth.tsx

### SCN-116: Vendor credential delete blocked while in use
- **Persona:** owner
- **Feature:** analytics-sources
- **Entry point:** Settings → Vendor credentials → trash on a credential that a connection still references
- **Preconditions:** at least one connection references the credential
- **Steps:**
  1. User clicks the trash on the credential
  2. User confirms in the ConfirmModal
- **Expected result:** the delete is refused (HTTP 409, FK RESTRICT); the credential row stays and the message says a connection still uses it — no connection is ever left orphaned
- **UI elements:** trash ActionButton, ConfirmModal, error toast naming the conflict, the unchanged credential row
- **States covered:** error
- **Errors & recovery:** this scenario IS the error path; recovery is to delete the referencing connection (SCN-032) or re-point it at another credential (SCN-113), then retry the credential delete
- **Status:** implemented
- **Audit note (2026-08-19):** verified against shipped code, AUD-0819-15. These nine shipped in `[1.16.0]` and stayed `draft` with `Last audit: —` for a month, which is the drift the scenario-first rule exists to prevent: the base is the source of truth only while it is kept current.
- **Coverage:** components/settings/VendorCredentialsPanel.tsx; components/connections/ConnectionSelector.tsx

### SCN-117: Ask about analytics data in chat — grounded answer or honest refusal
- **Persona:** analyst
- **Feature:** analytics-sources
- **Entry point:** Chat → question about traffic, users, events or revenue
- **Preconditions:** a GA4 connection exists and has collected at least one period (SCN-113, SCN-115)
- **Steps:**
  1. User asks e.g. "how many sessions did we get last week?"
  2. The agent reads the collected fact tables and answers with the figures
- **Expected result:** every number in the answer comes from collected rows; the answer states its coverage
- **UI elements:** chat answer, caveat lines, reasoning panel
- **States covered:** success, partial, refusal, error
- **Errors & recovery:** the model answering without reading data → it is re-prompted once and then refused, and no invented figure is shown; a window with periods that failed → `⚠️ PARTIAL DATA` naming them, and those periods are excluded from the totals; a window the vendor truncated → the numbers are shown as a real lower bound, explicitly not a complete measurement; a window whose collection record aged out of retention → the numbers are shown and counted, and only the record is reported missing; a period never collected → reported as unknown, never as zero
- **Status:** implemented
- **Audit note (2026-08-19):** verified against shipped code, AUD-0819-15. These nine shipped in `[1.16.0]` and stayed `draft` with `Last audit: —` for a month, which is the drift the scenario-first rule exists to prevent: the base is the source of truth only while it is kept current.
- **Coverage:** backend/app/agents/analytics_agent.py

### SCN-118: Analytics answer renders a chart
- **Persona:** analyst
- **Feature:** analytics-sources
- **Entry point:** Chat → analytics question whose answer is tabular
- **Preconditions:** a GA4 connection with collected rows (SCN-113)
- **Steps:**
  1. User asks a question that returns a table (e.g. sessions by country)
  2. The answer renders with a chart, as a database answer does
- **Expected result:** the tabular analytics result reaches the visualization pipeline and charts like any other result
- **UI elements:** chart, result block, chart-type controls
- **States covered:** success, partial, empty
- **Errors & recovery:** a truncated or partially-collected window marks the result truncated so the chart is not presented as complete; a result with no rows produces no chart rather than an empty one implying zero
- **Status:** implemented
- **Audit note (2026-08-19):** verified against shipped code, AUD-0819-15. These nine shipped in `[1.16.0]` and stayed `draft` with `Last audit: —` for a month, which is the drift the scenario-first rule exists to prevent: the base is the source of truth only while it is kept current.
- **Coverage:** backend/app/agents/orchestrator.py

### SCN-119: Unsupported analytics source refused at creation
- **Persona:** owner
- **Feature:** analytics-sources
- **Entry point:** New Connection form → source type
- **Preconditions:** project owner
- **Steps:**
  1. User attempts to create an App Store Connect or Google Play connection
- **Expected result:** creation is refused with a specific message; no connection row is created and nothing is scheduled
- **UI elements:** source-type select, error toast
- **States covered:** error
- **Errors & recovery:** 422 naming the source as not yet available, rather than creating a connection that would fail silently every day; the credential providers remain selectable so keys can be stored ahead of support landing
- **Status:** implemented
- **Audit note (2026-08-19):** verified against shipped code, AUD-0819-15. These nine shipped in `[1.16.0]` and stayed `draft` with `Last audit: —` for a month, which is the drift the scenario-first rule exists to prevent: the base is the source of truth only while it is kept current.
- **Coverage:** backend/app/services/connection_service.py

### SCN-128: One question across analytics and the database in a single answer
- **Persona:** analyst
- **Feature:** analytics-sources
- **Entry point:** a question in chat that needs both a connected analytics source and the project's own database
- **Preconditions:** a project with BOTH an analytics connection (collected periods on file) and a queryable database connection
- **Steps:**
  1. User asks something that spans both, e.g. "compare GA4 sessions per day in August with signups per day in our database"
  2. The router marks the question complex / multi-source, so the multi-stage pipeline is taken
  3. The planner names an analytics stage and a database stage, because the planner's user prompt lists what this project has connected
  4. The analytics stage reads the collected fact tables and returns rows; the database stage returns its own rows
  5. A following analyse/transform stage compares them and the synthesis answers from both
- **Expected result:** one answer grounded in both sources, carrying the analytics caveats it always carries — a period nobody collected is reported missing, never as zero
- **UI elements:** chat answer, Agent Reasoning Panel (both stages visible), chart where the comparison is chartable
- **States covered:** success, partial (a period is not collected), error (the analytics source is unreachable)
- **Errors & recovery:** an analytics source that cannot be resolved fails the stage as `configuration` — non-retryable, because no retry makes a connection appear — and the pipeline replans without it rather than grinding; a project with no analytics connection is never told analytics exists, so no stage is planned against a source that is not there
- **Status:** implemented
- **Audit note (2026-09-03):** added with A1. Before it, `StageExecutor` dispatched six tools and `query_analytics_source` was not among them, while the planner's vocabulary did not name it either. The orchestrator knew and worked around it: an analytics-**only** project was bounced to the flat loop (T13). What no workaround covered is this scenario — analytics *plus* a database — where the pipeline ran and analytics was silently absent. The bounce is removed: the pipeline executes analytics stages now. **The check behind this PASS is unit-level, not observed.** 47 tests, including a chain that drives analytics → `process_data` → `aggregate_data` with no LLM and two negative controls, prove the stage dispatches, resolves only within its own project, exposes rows a transform consumes, and classifies three outcomes. What they cannot prove is that a real planner builds a two-source plan on a real question — and that cannot be observed here at all: production holds **0 analytics connections and 0 vendor credentials** (measured 2026-09-03), so there is no project on which the mixed case exists. Re-audit when the first analytics source is connected.
- **Coverage:** backend/app/agents/stage_executor.py (`_run_analytics_stage`), backend/app/agents/prompts/planner_prompt.py, backend/app/services/connection_service.py (`resolve_analytics_connection`), backend/tests/unit/agents/test_analytics_pipeline_stage.py, backend/tests/unit/agents/test_planner_source_availability.py

### SCN-120: Database does not answer — honest stop instead of a silent grind
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** a data question in chat against a connection whose database is reachable but not executing
- **Preconditions:** a project with a database connection; the database accepts EXPLAIN but does not return rows within `query_timeout_seconds`
- **Steps:**
  1. User asks a data question
  2. The query times out; the agent retries **once** with a deliberately narrowed query
  3. The narrowed query also times out
- **Expected result:** the run stops within roughly two query timeouts and says the database did not answer — naming the environment, not the user's question, as the cause. Before this change the same situation produced ten LLM repair calls and a bare error after ~6 minutes (production trace `2026-08-06 11:39:24`, 84 spans)
- **UI elements:** in-transcript error bubble (the SCN-046 surface), Retry button — a timeout is retryable
- **States covered:** running, error, partial (narrowed query succeeded)
- **Errors & recovery:** two distinct outcomes, never conflated. (a) *Database did not answer* — "The database didn't answer within 30 s — twice in a row. That points at the database rather than at your question. Try again in a few minutes, or check the connection." (b) *Narrowed and succeeded* — the answer carries the existing partial-data caveat saying it covers a narrower range than asked. The SQL, the attempt count and the connection id are logged, never shown. A run killed by the outer request timeout is recorded with `failure_kind`, not as a stub row
- **Status:** implemented
- **Audit note (2026-08-19):** verified against shipped code, AUD-0819-15. These nine shipped in `[1.16.0]` and stayed `draft` with `Last audit: —` for a month, which is the drift the scenario-first rule exists to prevent: the base is the source of truth only while it is kept current.
- **Coverage:** backend/app/core/validation_loop.py; backend/app/core/error_classifier.py; backend/app/agents/sql_agent.py; frontend/src/components/chat/ChatMessage.tsx

### SCN-121: Attaching an SSH key you do not own is refused
- **Persona:** owner
- **Feature:** connections
- **Entry point:** connection create/update, or project update, carrying `ssh_key_id`
- **Preconditions:** the caller owns the project; the key id belongs to a different tenant
- **Steps:**
  1. The request names an `ssh_key_id` the caller does not own
- **Expected result:** refused with **404 "SSH key not found"**, and nothing is written. The same refusal covers the two-step variant — attach on one request, change other fields on the next — because the check runs on the merged row, not on the payload branch
- **UI elements:** error toast on the connection/project form
- **States covered:** error
- **Errors & recovery:** 404 rather than 403 is deliberate: the lookup is owner-strict, so "someone else's key" and "no such key" answer identically and neither confirms that an id exists. Before this change the reference was accepted unchecked, and `GitAgent` / the repo indexer later decrypted it with no owner filter — so the server would open a tunnel or clone a repository with another tenant's private key. The key itself was never exposed; its *use* was
- **Status:** implemented
- **Audit note (2026-08-19):** verified against shipped code, AUD-0819-15. These nine shipped in `[1.16.0]` and stayed `draft` with `Last audit: —` for a month, which is the drift the scenario-first rule exists to prevent: the base is the source of truth only while it is kept current.
- **Coverage:** backend/app/api/routes/connections.py; backend/app/api/routes/projects.py; backend/app/services/ssh_key_service.py; backend/tests/integration/test_ssh_key_ownership.py

### SCN-122: Every answer says how it is known — the seal
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** any assistant answer in the chat transcript
- **Preconditions:** a project with at least one connection; the user has asked a question
- **Steps:**
  1. User asks a question and the agent answers
  2. The answer carries a seal beside its response-type chip: **Verified**, **Inferred** or **Unverified**
  3. User clicks the seal
- **Expected result:** the seal states how *this* answer was obtained, and clicking it opens the proof — the SQL panel where a query was run, the source list where the answer came from retrieval. **Verified** means a query the reader can open produced the figure; **Inferred** means the system derived it by a step it can name (retrieval, or a query whose schema index the backend reported stale); **Unverified** means it cannot say — a run that failed, exhausted its step budget, or answered from neither a query nor a source.
- **UI elements:** the seal (10px monospace, uppercase, in the state's own colour, **always with its word** — the colour never carries the meaning alone), the SQL details panel, the sources list
- **States covered:** verified, inferred, unverified
- **Errors & recovery:** a failed or budget-exhausted run seals **Unverified** even when a query is attached to it, because a partial run's evidence proves nothing about the answer. **The backend did not honour this until 2026-09-05 (row 1.7):** the rule is implemented here, in `sealStateFor`, by keying on `step_limit_reached` — and the orchestrator withheld that type from exactly the runs where the seal mattered, typing a cut-off run `sql_result` whenever its partial answer looked plausible. The frontend was right and unreachable. A rule stated in one layer and decided in another is only as true as the value the other layer sends. The seal it replaced was fed `response_type === "sql_result" ? "unverified" : undefined` — two of its three words were unreachable, so it told the reader the same thing about every answer
- **Degraded retrieval (2026-08-19, AUD-0819-03; wording made cause-aware 2026-08-21, F-KNOW-07):** when a retrieval leg comes back empty **because something is wrong**, the answer carries a line naming it in the reader's words, on its own row above the seal, not folded into the freshness warning. **The cause picks the sentence, because the cause decides what the reader should do:** a missing, corrupt or stale-schema index reads "keyword search is unavailable for this project … re-indexing the repository restores it"; a timeout or error reads "did not respond in time"; only a leg that genuinely searched and found nothing reads "returned nothing for this question". The old single sentence was written when the backend labelled every empty leg `empty_result`, and said of a missing index it sent someone to rewrite a question that was never the problem while half the search was never consulted. **A working index that matched nothing now emits nothing at all** — it is not degradation, and a caveat on the normal path is the noise that teaches people to ignore caveats. The schema-retrieval leg is counted in metrics but deliberately carries **no** reader-facing line: it has a working relevance safety net behind it. The **seal state is unchanged**: sources *were* retrieved, so `inferred` is still the honest word, and fusing the two facts would also downgrade a SQL answer whose proof is its own query. This closes a signal that existed end-to-end and surfaced nowhere: `emit_retrieval_degraded` fed the metrics and the SSE stream, `PIPELINE_EVENTS` did not list the event, and the handler had no case for it — so an answer built on one leg of two rendered exactly like one built on both. In production that is the normal case, because the BM25 snapshot lives on the dyno's ephemeral disk (F-KNOW-07). The allowlist/handler seam is now held together by a test that reads both sides (`__tests__/sse.test.ts`) **One deploy will make the stale-schema branch fire on purpose (S2, 2026-09-05):** `tokenize_code` now emits whole identifiers, and the snapshot persists its tokenized corpus, so `_SCHEMA_VERSION` moved 2 → 3 to stop old tokens being matched against new queries. Every existing snapshot therefore reads as unusable until `bm25_local_reconcile` rebuilds it — and that runs through `spawn_tracked`, i.e. **beside** the first requests rather than before them. For that window the reader gets this scenario's line, whose advice ("re-indexing the repository restores it") is wrong here: nothing needs re-indexing, the rebuild is automatic and reads only Postgres. Accepted rather than given a fourth sentence — the window is one deploy wide, dense retrieval covers it, and a caveat minted for a transient boot state is the noise this scenario already warns about.
- **Status:** implemented
- **Audit note (2026-08-16):** PARTIAL on the first pass — the derivation was right and tested, but the row that renders the seal was guarded on `responseType !== "text"`, so a plain text answer carried **no seal at all** while deriving exactly the `unverified` state this scenario calls the honest one. Fixed in the same change (`ChatMessage.tsx`), and the check that was missing is now a render-level one, not another unit test of the derivation
- **Coverage:** frontend/src/components/ui/Seal.tsx; frontend/src/components/chat/ChatMessage.tsx; frontend/src/__tests__/components/Seal.test.tsx; frontend/src/__tests__/components/ChatMessage.test.tsx

### SCN-123: The interface reads as one design in light and in dark
- **Persona:** analyst
- **Feature:** settings
- **Entry point:** the theme control (SCN-096), or the OS preference under `system`
- **Preconditions:** none
- **Steps:**
  1. User switches between light, dark and system
- **Expected result:** the whole interface changes together. The product runs on the `ledger` style pack: a warm cream field under near-black ink in light, a warm coal field under cream ink in dark, elevation drawn as a 1px hairline at 12% ink with **no shadow on any card**, and one terracotta accent that **labels and marks but never fills a control** — the primary button is ink in light and cream in dark, and its text inverts with it. Nothing keeps a colour from the other theme
- **UI elements:** every surface; the theme toggle
- **States covered:** light, dark, system
- **Errors & recovery:** the theme is applied as **both** a `.dark` class and a `data-theme` attribute, because Tailwind's dark variant keys off the class while the pack's token layer switches on the attribute. Setting only one leaves half the app in the other theme, which reads as a rendering bug rather than a missing line — `theme-store.test.ts` fails if either stops being set
- **Status:** implemented
- **Coverage:** frontend/src/app/globals.css; frontend/src/stores/theme-store.ts; frontend/src/__tests__/theme-tokens.test.ts; frontend/src/__tests__/pack-bans.test.ts

### SCN-124: A result reads as a ledger — aligned, labelled, and the same in both themes
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** any answer that returns rows, and any chart drawn from them
- **Preconditions:** a project with a database connection; a question that produces a result set
- **Steps:**
  1. User asks a question that returns rows
  2. The result renders as a table, and — where the agent chose one — as a chart above it
- **Expected result:** rows are 32px on the data plane with hairline dividers and a monospace row number; **numeric columns are right-aligned in the data face with tabular figures, and which columns those are is decided from the values rather than from the column name** — a date column or a column with one `N/A` in it stays left-aligned as text. An absent value renders as `NULL` in the faint ink, never as an empty cell. Charts take their series colours from the pack's five-hue ramp and follow the theme; a sixth series repeats the ramp darkened rather than reusing a hue exactly. A category the agent named but has no number for shows as a gap, not as a zero
- **UI elements:** result table (row number column, export chips), chart card, legend with a coloured dot beside each series name
- **States covered:** result, empty result ("No data returned"), capped result (>500 rows, with the count and a control to show all), unsupported chart type
- **Errors & recovery:** an unsupported chart type is **named** and points at the table view rather than rendering nothing; a chart that throws falls back to the same suggestion. The per-row entrance cascade the table used to play was removed: a result table renders on every query, which is the frequency row where the motion doctrine cuts animation to the floor
- **Status:** implemented
- **Coverage:** frontend/src/components/viz/DataTable.tsx; frontend/src/components/viz/table-columns.ts; frontend/src/components/viz/ChartRenderer.tsx; frontend/src/components/viz/chart-series.ts; frontend/src/__tests__/components/table-columns.test.ts; frontend/src/__tests__/components/chart-series.test.ts

### SCN-125: The answer is the page, not a speech bubble
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** the chat transcript
- **Preconditions:** a project with a connection; at least one exchange
- **Steps:**
  1. User asks a question
  2. The agent works, then answers
- **Expected result:** the reader's own turn is a filled bubble in **ink**, capped at 80% of the column (95% on a phone). The **answer is not a bubble at all** — it is drawn straight on the panel at full width, because an answer the reader is meant to audit is the page's content rather than a remark, and a card around it adds a wall to look past. Above it sit the response-type chip and the seal (SCN-122), both 10px monospace uppercase. While the answer streams, a caret **blinks** — `steps(1, end)`, a caret rather than a breathing bar — and it stops the moment the stream does. While the agent is still working, three thinking dots pulse; they stop when the run does
- **UI elements:** user bubble, answer body, response-type chip, seal, streaming caret, thinking dots
- **States covered:** working, streaming, complete, refused, failed
- **Errors & recovery:** the three loops named here are the **only** ones this design permits, and every one of them is state: a caret while tokens arrive, dots while a run works, a heartbeat on a live indicator. All three stop under `prefers-reduced-motion: reduce`, which the global rule enforces by zeroing the duration tokens
- **Status:** implemented
- **Audit note (2026-08-16):** PARTIAL on the first pass, same root cause as SCN-122 — "above it sit the response-type chip and the seal" did not hold for a plain text answer. One guard, one fix, deliberately filed as one finding rather than two
- **Coverage:** frontend/src/components/chat/ChatMessage.tsx; frontend/src/components/chat/ChatPanel.tsx; frontend/src/app/globals.css; frontend/src/__tests__/components/ChatMessage.test.tsx

## workspace

### SCN-129: Data workspace — every source managed on one screen
- **Persona:** owner
- **Feature:** workspace
- **Traces:** FLW-01, FLW-02, FLW-03, FLW-04
- **Entry point:** top-bar "Data" button; replaces today's narrow `connections` centre panel
- **Preconditions:** a project is active
- **Steps:**
  1. User clicks "Data" -> system opens the workspace in the centre panel at the full width of the content column, with three groups: Databases & sources, Repositories, Documentation
  2. User reads a group -> system shows one card per item carrying its type, name, health dot, freshness line and counts
  3. User clicks a card -> system expands it in place into its management form — edit, test, index, describe, delete — without a modal and without the sidebar
- **Expected result:** every source of the project is visible and manageable on one screen; no management action requires the sidebar
- **Alt paths:** viewer opens the workspace -> cards render read-only with no edit/index/delete; no project active -> "Select a project first", as the panel does today
- **UI elements:** "Data" top-bar button, three group headings with counts, "Add" per group, source cards (type icon, name, health dot, freshness, counts), in-place expander, per-card Edit / Test / Index / Describe / Delete
- **States covered:** loading, empty, error, success
- **Errors & recovery:** a group's list fails to load -> that group shows an inline error with Retry while the other groups still render, rather than one failure blanking the screen; a card's health probe fails -> the card reads "health unknown" and stays manageable
> **Layout.**

```
  +----------------+-----------------------------------------------+
  |  sidebar       |  Data workspace                               |
  |  (switching)   |                                               |
  |                |  DATABASES & SOURCES (2)          [+ Add]     |
  |  Projects      |  +-----------------------------------------+  |
  |   > nicegram   |  | (o) nicegram        postgres  read-only |  |
  |     acme       |  |     718 tables - indexed 2h ago         |  |
  |                |  |     "billing ledger, money in cents"    |  |
  |  Chats         |  +-----------------------------------------+  |
  |   > today      |  | (o) nicegram_hub    postgres  read-only |  |
  |     earlier    |  |     41 tables - never indexed  [Index]  |  |
  |                |  |     No purpose set          [Describe]  |  |
  |                |  +-----------------------------------------+  |
  |                |                                               |
  |                |  REPOSITORIES (2)                 [+ Add]     |
  |                |  +-----------------------------------------+  |
  |                |  | (o) api        main   9,981 files       |  |
  |                |  |     indexed 3h ago - head matches       |  |
  |                |  +-----------------------------------------+  |
  |                |                                               |
  |                |  DOCUMENTATION (758)         [Refresh docs]   |
  +----------------+-----------------------------------------------+
```

> **Delivered 2026-09-08.** Four groups (sources, repository, scheduled queries, documentation), full content width, the empty state of SCN-131, capability and read-only chips, and per-card management in place: Describe, Edit, Test, Index, Delete — no modal and no sidebar. Test reports **on the card**, because a toast is gone by the time the user looks back at the source it was about. Test and Index are offered only for a source the SQL tools can reach: offering to index an analytics source offers an action whose adapter does not exist for that `db_type`. Edit sets an id the shared form in the same panel opens on, rather than reimplementing sixteen fields of it. Delete asks one confirmation naming what is destroyed, and that sentence now has **one home** shared with the connection list — two copies is two chances for one to under-report what the click removes.
- **Status:** implemented
- **Coverage:** frontend/src/components/workspace/DataWorkspace.tsx; frontend/src/__tests__/components/DataWorkspace.test.tsx; frontend/src/app/app/page.tsx (the `connections` panel at the `effectivePanel` switch)

### SCN-130: Add a source without leaving the workspace
- **Persona:** owner
- **Feature:** workspace
- **Traces:** FLW-02
- **Entry point:** workspace → Databases & sources → "Add"
- **Preconditions:** owner; a project is active
- **Steps:**
  1. User clicks "Add" -> system opens an inline panel in the centre column offering the source kinds: Database, MCP server, Analytics source
  2. User picks Database -> system reveals the database form in place, with the type select and its default port
  3. User fills the fields and clicks "Test connection" -> system reports the outcome inline beside the fields, naming the failure when there is one
  4. User clicks Create -> system adds the card to the group, collapses the form, and offers "Index now" on the new card
- **Expected result:** a source is created and appears as a card; the user never left the workspace and never opened a modal
- **Alt paths:** user picks Analytics source -> the GA4 flow of SCN-113 runs inside the same inline panel; user picks MCP server -> the MCP fields of SCN-027 do; user cancels -> the form collapses and nothing is created
- **UI elements:** "Add" button, source-kind chooser, inline form, "Test connection" button with inline result, Create (Saving…) / Cancel, "Index now" on the new card
- **States covered:** loading, error, success
- **Errors & recovery:** empty name -> inline "Name is required" with the field focused, rather than the silent return the sidebar form does today; SSH host without user or key -> inline message on the offending field; create fails -> inline error above the form with the input preserved; quota reached -> the 402 of SCN-100 rendered in place with the upgrade route
- **Status:** draft
- **Coverage:** none yet; planned: frontend/src/components/workspace/DataWorkspace.tsx, planned: frontend/src/components/connections/ConnectionSelector.tsx (the form logic it reuses)

### SCN-131: A new project's workspace says what to connect first
- **Persona:** owner
- **Feature:** workspace
- **Traces:** FLW-01
- **Entry point:** workspace of a project with nothing connected — reached right after SCN-016, including the second and later project
- **Preconditions:** owner; the project has no connections, no repository, no documents
- **Steps:**
  1. User opens the workspace of a fresh project -> system shows the three groups, each empty, each with one sentence naming what it unlocks and a single primary action
  2. User reads the order -> system states that a data source comes first, because a repository is only picked up by the nightly wave once the project has an active connection
  3. User clicks the one primary action -> the flow of SCN-130 starts
- **Expected result:** the user knows the next step and why it is that step; the ordering constraint is stated rather than discovered by a repository that silently never indexes
- **Alt paths:** the user connects a repository first anyway -> the Repositories group shows "indexed manually only — no data source connected yet" with the action to add one, so the consequence is visible where it applies
- **UI elements:** three empty-group cards, per-group one-line explanation, one primary action, the ordering note
- **States covered:** empty
- **Errors & recovery:** nothing can fail — the screen reads state that is already loaded
- **Status:** implemented
- **Coverage:** frontend/src/components/workspace/DataWorkspace.tsx; frontend/src/__tests__/components/DataWorkspace.test.tsx; backend/app/services/daily_knowledge_sync_service.py (the eligibility rule the note states)

### SCN-132: Each source card says what the agent can do with it
- **Persona:** analyst
- **Feature:** workspace
- **Traces:** FLW-02
- **Entry point:** workspace → any source card
- **Preconditions:** a project with at least one source
- **Steps:**
  1. User scans the cards -> each states its capability in the product's terms: queryable, read-only, indexed-not-queryable, or collected-on-a-schedule
  2. User reads a card with no description -> system shows "No purpose set — the agent will infer one" with a Describe action
  3. User reads a card whose index is stale -> system shows the age and the one action that fixes it
- **Expected result:** a user can tell, without opening anything, what each source contributes to an answer and what is missing
- **Alt paths:** an analytics source -> the card shows its coverage and pending periods per SCN-115 instead of a table count, because it is collected rather than queried
- **UI elements:** capability chip, read-only chip, freshness line, counts, "No purpose set" placeholder with Describe, single remedial action per stale card
- **States covered:** empty, success
- **Errors & recovery:** capability cannot be determined -> the chip reads "unknown" and links to Test, never defaulting to queryable; an analytics source must never advertise a query capability, per `is_queryable_database`
- **Status:** implemented
- **Coverage:** frontend/src/components/workspace/DataWorkspace.tsx; frontend/src/__tests__/components/DataWorkspace.test.tsx; backend/app/api/routes/connections.py (`capability_of` — answered server-side so the card does not reimplement `is_queryable_database` in a language that cannot import it); backend/tests/unit/test_workspace_contract.py

### SCN-133: The sidebar switches, the workspace manages
- **Persona:** analyst
- **Feature:** workspace
- **Traces:** FLW-01
- **Entry point:** the sidebar, after the workspace ships
- **Preconditions:** the workspace of SCN-129 exists
- **Steps:**
  1. User opens the sidebar -> system shows switching only: projects, sources and chats as selectable rows, with current selection marked
  2. User looks for a create or delete action there -> system offers none; each group header links to the workspace instead
  3. User clicks a source row -> system selects it for the chat and leaves the centre panel on chat, rather than opening a management form
- **Expected result:** exactly one place manages a source and exactly one place switches between them; the two are not the same place. What the rail becomes once management leaves is SCN-149, and the group that makes it worth looking at is SCN-150
- **Alt paths:** on the narrow layout the sidebar is a drawer -> the same rule holds, and management opens the workspace full-screen
- **UI elements:** sidebar project rows, source rows, chat rows, per-group "Manage" link, selection markers
- **States covered:** empty, success
- **Errors & recovery:** nothing can fail — no action is taken here beyond selection
> **Reconciliation.** This scenario changes the **Entry point** of SCN-025, SCN-026, SCN-027, SCN-028, SCN-029, SCN-030, SCN-031, SCN-032 and SCN-037, all of which read "sidebar …" today. They must be edited in the same change that removes the sidebar's management affordances, and they drop back to `draft` when they are. Until then both entry points exist and the sidebar remains authoritative.
- **Status:** implemented
- **Coverage:** frontend/src/components/Sidebar.tsx; frontend/src/components/connections/RailSourceList.tsx (selection only, with `Manage sources →` as the seam); frontend/src/components/workspace/DataWorkspace.tsx

### SCN-149: The sidebar answers "where was I, and what needs me"
- **Persona:** analyst
- **Feature:** workspace
- **Traces:** FLW-01
- **Entry point:** every authenticated screen — the left rail is always present
- **Preconditions:** signed in; a project is active
- **Steps:**
  1. User signs in and looks left -> system shows, in this order: the project switcher, anything that needs attention, five navigation entries, and the recent chats
  2. User reads the rail top to bottom -> it answers two questions and no others: *where am I* and *what needs me* (IS-01)
  3. User clicks a navigation entry -> system changes the centre panel and the rail does not change shape
  4. User clicks a recent chat -> system opens it with the rail's selection marked
  5. User looks for a create or delete control for a source -> the rail offers none; management is the workspace of SCN-129 (SCN-133)
- **Expected result:** the rail is a place to stand and a place to return to, not a control panel; nothing in it needs to be expanded before it is useful
- **Alt paths:** narrow layout -> the rail is a drawer with the same order and the same five entries; a viewer -> the same rail, with entries their role cannot use absent and explained rather than dead (IS-17)
- **UI elements:** project switcher (fixed, not collapsible); `Needs you` group (absent when empty); five navigation entries — Chat, Data, Knowledge, Dashboards, Activity; `Recent` chat list with `all chats →`; account entry at the foot
- **States covered:** loading, empty, error, success
- **Errors & recovery:** the recent list fails -> that block shows an inline retry and the navigation still works, because a rail that cannot navigate is worse than one with a stale list; the project list fails -> the switcher says so and keeps the last known active project rather than emptying the screen
> **What leaves the rail, and where it goes.** Thirteen collapsible sections is the defect, and it is a structural one: account configuration, project management, work and reports were stacked in one column at equal weight, so the rail had no answer to either question above. SSH Keys and Vendor Credentials → Settings → Credentials. Projects → the switcher, with its management in the workspace. Repository and Connections → the workspace (SCN-129). Custom Rules → the Knowledge panel, where the rest of the project's knowledge already lives. Schedules → the workspace, beside the sources they automate. Usage and Analytics → Settings. Request History → Activity. Chat History stays, shortened, as `Recent`.
- **Status:** implemented
> **Delivered 2026-09-08, over two changes.** Thirteen collapsible sections became two, and the rail lost 325 lines: SSH Keys and Vendor Credentials went to Settings → Credentials, Knowledge and Custom Rules to the Knowledge screen, Dashboards to its own, Usage and Analytics to Settings, and Repository and Schedules to the data workspace. The project switcher is fixed and never collapsible — a rail that can hide where you are answers neither of its questions. Five flat entries (Chat, Data, Knowledge, Dashboards, Activity), the `Needs you` group of SCN-150, and `Chat History` renamed `Recent`, which is what a returning user is looking for rather than a filing cabinet.
> **What went with them, and where.** The repository's status, its index trigger, its live progress and its update check were all in the rail. Live progress with cancel and retry is the Knowledge Health panel of the project overview (SCN-062); a failed or reaped run reaches `Needs you`; the repository is a group in the workspace. Nothing was dropped — the rail stopped running things.
> **One deviation from the spec above:** sources are still wrapped in a collapsible `Connections` section rather than being plain rows. Its contents are selection-only, so the rule this scenario exists for holds; only the chrome differs.
- **Coverage:** frontend/src/components/Sidebar.tsx; frontend/src/components/settings/SettingsPanel.tsx; frontend/src/components/connections/RailSourceList.tsx; frontend/src/components/attention/AttentionGroup.tsx; frontend/src/__tests__/components/Sidebar.test.tsx

### SCN-150: The sidebar surfaces what needs attention and routes to the fix
- **Persona:** analyst
- **Feature:** workspace
- **Traces:** FLW-01
- **Entry point:** the `Needs you` group of SCN-149
- **Preconditions:** something in the project is failed, stale, never-run or unread
- **Steps:**
  1. User signs in after a night -> system lists what changed against them: an index that failed or was reaped, a source never indexed, a schedule that did not run, a document behind its repository head, an unresolved insight
  2. User reads one entry -> it names the thing, what happened, and when, in one line (IS-02, IS-16)
  3. User clicks it -> system opens the exact surface that fixes it, with the item in view — not a list the user must search
  4. User fixes it -> the entry leaves the group; when the last one goes, the group disappears rather than becoming an empty box
- **Expected result:** the first thing a returning user sees is the shortest true list of what needs them, and every entry is one click from its remedy
- **Alt paths:** nothing needs attention -> the group is **absent**, not an empty state, because a permanent "all good" box trains people to stop reading the rail (IS-05, IS-06); more than five entries -> the five most severe are shown with `N more →` into Activity
- **UI elements:** `Needs you` group header with a count, one line per entry (subject, what happened, age), severity marker, `N more →`
- **States covered:** empty (absent), loading, error, success
- **Errors & recovery:** the attention query fails -> the group shows one line saying it could not check, which is different from "nothing needs you" and must never render as it; a routed-to item no longer exists -> the target surface says it was removed and the entry clears
> **Why this earns the space it takes.** Every input already exists and none of it is surfaced on return: failed and reaped runs are catalogued in `error_log` and `/api/logs`, freshness states are computed by `KnowledgeFreshnessService`, a schedule that did not run is in `sync-history`, and unresolved insights are the feed of SCN-065. Production ran 143 failed runs and `index_repo` completed 16 times in 94 runs; a user could learn none of that from the interface without going looking.
> **Delivered 2026-09-08 with three of the five sources**: a failed or reaped index, a source configured and never indexed, and a schedule withheld for want of a plan. Stale-but-indexed knowledge and unresolved insights are not yet in it — both are real signals, and both were left out because they are maintenance questions rather than "this needs you now", which is the line the group is drawn on.
- **Status:** implemented
- **Coverage:** backend/app/services/attention_service.py; backend/app/api/routes/projects.py (`GET /{project_id}/attention`); backend/tests/unit/test_attention_service.py; frontend/src/components/attention/AttentionGroup.tsx; frontend/src/components/Sidebar.tsx; frontend/src/__tests__/components/AttentionGroup.test.tsx

### SCN-151: A panel link opens the panel it names
- **Persona:** analyst
- **Feature:** workspace
- **Traces:** FLW-01
- **Entry point:** any `/app?panel=<name>` URL — a bookmark, a shared link, or a route the product hands out itself
- **Preconditions:** signed in; a project is active
- **Steps:**
  1. User opens `/app?panel=knowledge` -> system shows the Knowledge screen: the project's documents, insights and metrics, with its custom rules beneath them
  2. User opens `/app?panel=insights` -> system shows the same screen already on the insights tab, rather than on docs with the user hunting for it
  3. User opens `/app?panel=dashboards` -> system shows the project's dashboards
  4. User opens a name the product does not define -> system falls back to the default view, as it always did
- **Expected result:** a declared panel link arrives where its name says; nothing silently substitutes a different screen
- **Alt paths:** no project active -> each screen says "Select a project first" rather than rendering an empty shell
- **UI elements:** Knowledge screen (docs / insights / metrics tabs, custom rules section), Dashboards screen, the per-screen "Select a project first" state
- **States covered:** loading, empty, error, success
- **Errors & recovery:** a screen's own fetch fails -> it renders its inline error and the surrounding navigation still works; each panel is wrapped in a section error boundary, so one broken screen does not take the page down
> **What this fixed.** `knowledge` and `insights` were in `APP_PANELS` — validated as legal URLs — and both rendered the **chat**. Two gates dropped them: the panel resolver kept its own enumeration of five names while the list held eight, and the render switch had no case for them behind an unconditional chat fallback. A route that 404s teaches the user immediately; one that renders a plausible other screen teaches them nothing. The resolver now passes any declared panel through rather than re-deciding it by name, which is the shape that stops the two lists drifting apart again.
- **Status:** implemented
- **Coverage:** frontend/src/app/app/page.tsx; frontend/src/hooks/useAppPanel.ts; frontend/src/components/knowledge/KnowledgePanel.tsx; frontend/src/components/dashboards/DashboardsPanel.tsx; frontend/src/__tests__/app-panels-have-destinations.test.ts


### SCN-152: The rail says when a project's index outgrew its plan
- **Persona:** owner
- **Feature:** billing
- **Traces:** FLW-01
- **Entry point:** the "Needs You" group in the sidebar rail, on any screen
- **Preconditions:** signed in; a project is active; the account's plan sets a per-project index limit
- **Steps:**
  1. User's project holds more index than the plan sells -> system shows one rail line naming the project, its approximate index size and the plan's limit
  2. User selects the line -> system opens Settings, where the plan and its limits are
  3. User keeps working; the next index run starts and completes normally -> system indexes as it always did, and the line stays until the size or the plan changes
- **Expected result:** the user learns their project passed what they bought, from the place they already look, and nothing they were doing stops
- **Alt paths:** plan is unlimited (`enterprise`, or no limit set) -> no line, and the counting queries are never run; the size cannot be measured -> no line, because "could not check" must not be shown as "over quota"
- **UI elements:** the "Needs You" rail group, a warning-severity line, the Settings destination
- **States covered:** empty, success
- **Errors & recovery:** the billing lookup fails -> the account is treated as unlimited and the failure is logged, never surfaced as a breach the user cannot verify; the whole source fails -> the rail says "could not check index size", which is a different sentence from "nothing needs you"
> **The decision this records (D5, 2026-09-08).** Three options were on the table: warn, block a full rebuild, or block indexing entirely. Warn was chosen for the same reason the scheduled-work gate leaves manual indexing open — a product that refuses to index is a product nobody can evaluate, and the account most likely to be over its quota is the one getting the most out of the trial. `plans.max_index_bytes` had been sold since 2026-08-31 and `estimate_index_bytes` had existed beside it, called from a test and from nothing else: the promise, the column and the meter all existed, and nothing compared them.
- **Status:** implemented
- **Coverage:** backend/app/services/attention_service.py (`_index_over_quota`, `index_quota_exceeded`); backend/app/entitlements/__init__.py (`index_quota_bytes`); backend/app/services/plan_catalogue.py (`estimate_index_bytes`); backend/tests/unit/services/test_index_quota_warning.py

## repos

### SCN-137: Connect a repository to a project
- **Persona:** owner
- **Feature:** repos
- **Traces:** FLW-03
- **Entry point:** workspace → Repositories → "Add"; today the same fields live inside the project form of SCN-016/SCN-018
- **Preconditions:** owner; a project is active; an SSH key exists for a private repository
- **Steps:**
  1. User clicks "Add" under Repositories -> system shows the repository form: name, URL, branch, SSH key
  2. User pastes an SSH URL -> system detects that a key is required and probes access as the user stops typing
  3. User sees the probe result -> system reports reachable with the resolved head, or the exact reason it failed
  4. User clicks Create -> system adds the repository card and offers "Index now" with the first-run duration estimate
- **Expected result:** the repository is attached to the project as its own item, visible with its own status, and ready to index
- **Alt paths:** a public HTTPS URL -> no key is requested; user creates without indexing -> the card reads "never indexed" with the action still offered
- **UI elements:** "Add" button, name / URL / branch / SSH-key fields, live access-probe result, Create / Cancel, "Index now" with estimate
- **States covered:** loading, empty, error, success
- **Errors & recovery:** unreachable or unauthorised -> the probe names which of the two it was and the form keeps every field; branch does not exist -> inline error on the branch field naming the branches that do; branch fails validation -> refused before submit, since the value reaches `git checkout` as an argument
- **Status:** draft
- **Coverage:** none yet; planned: frontend/src/components/workspace/DataWorkspace.tsx, backend/app/api/routes/repos.py (`check-access` and the repositories CRUD it uses), backend/app/services/repository_service.py

### SCN-138: Connect a second repository
- **Persona:** owner
- **Feature:** repos
- **Traces:** FLW-03
- **Entry point:** workspace → Repositories → "Add", with one repository already attached
- **Preconditions:** owner; the project already has one connected repository
- **Steps:**
  1. User adds a second repository through SCN-137 -> system creates it beside the first, each with its own name, branch, key and status
  2. User starts its index -> system queues it behind any repository index already running for this project rather than running the two together
  3. User watches both cards -> each shows its own run, progress and last-indexed commit, and neither reports the other's state
  4. User asks a question spanning both -> the answer draws on both and attributes each part per SCN-141
- **Expected result:** two repositories coexist under one project, index independently, and both reach the agent
- **Alt paths:** the user removes the first repository -> the second keeps its knowledge untouched, per SCN-142
- **UI elements:** repository cards with per-repository status, per-repository Index action, queue position when one is waiting
- **States covered:** loading, empty, error, success
- **Errors & recovery:** one repository's index fails -> only its card reports the failure and the other stays indexed and queryable; **the indexes must not run concurrently** — one repository index measures 415 MiB of peak worker memory against a 512 MiB quota, so a second beside it is the R15 kill this product has already had, and serialising them is a requirement of this scenario rather than an optimisation
> **Parked 2026-09-08.** D1 took this into scope on 2026-09-07 and reversed the next day — one repository for now, deferred rather than cancelled. The reason is measured: `CodeGraphService.save_incremental` merges by file path within a PROJECT, and a path is unique only inside a repository, so two repositories sharing `README.md` would delete each other's symbols on every incremental run. That makes this a change of identity in seven places plus the symbol `uid`, and moving the `uid` forces a full rebuild — 3.3 h on the one real repository. The scenario stands as designed; only its schedule changed. Today a second repository is created and never indexed. The CRUD writes `project_repositories` while every consumer reads `Project.repo_url`, so `POST /api/repos/{id}/index` on a project whose only repository is a table row answers `400 "Project has no repository URL configured"` (measured 2026-09-07). Implementing this scenario means giving the indexing pipeline, the code graph, the BM25 snapshot, the docs and GitAgent a repository dimension. That work is now in scope; this scenario is the acceptance test for it.
- **Status:** draft
- **Coverage:** none yet; planned: backend/app/knowledge/pipeline_runner.py, planned: backend/app/api/routes/repos.py, planned: backend/app/agents/git_agent.py, backend/app/models/repository.py

### SCN-139: Say what a repository is for, and what to ignore
- **Persona:** editor
- **Feature:** repos
- **Traces:** FLW-03
- **Entry point:** workspace → repository card → "Describe"
- **Preconditions:** editor/owner; a repository is connected
- **Steps:**
  1. User opens Describe on a repository -> system shows three fields: what this repository is, which data source it owns, and paths to ignore
  2. User fills them — e.g. "Laravel API, owns the nicegram DB", ignore `vendor/`, `storage/`, `*.generated.php` -> system saves them onto the repository
  3. User re-indexes -> system applies the ignore list during extraction and records the ownership claim for the code-to-database map
  4. User opens the code-to-database map -> tables are attributed to the repository that declares them instead of to a guess
- **Expected result:** the analyser is told what the repository is, and the answer's provenance improves visibly rather than as a claim
- **Alt paths:** no context set -> extraction behaves as it does today and the card says the analyser is inferring; the ignore list matches everything -> refused with the count it would have excluded
- **UI elements:** "Describe" action, role field, owned-source select, ignore-path list with add/remove, Save / Cancel, "the analyser is inferring" placeholder
- **States covered:** empty, loading, error, success
- **Errors & recovery:** an ignore pattern is invalid -> inline error naming the pattern, the rest still save; the owned-source select points at a deleted connection -> the claim renders as "source removed" and is not used, rather than silently matching nothing
> **Why this earns its place.** The code-to-database map for the one real customer named 39 tables of which six existed, because class names in generated `vendor/` code were pluralised into table names. A human-supplied ignore list and ownership claim is the input that shape rules alone cannot supply.
- **Status:** draft
- **Coverage:** none yet; planned: backend/app/models/repository.py (context columns and migration), planned: backend/app/knowledge/repo_analyzer.py, planned: frontend/src/components/workspace/DataWorkspace.tsx

### SCN-140: Index one repository without disturbing the other
- **Persona:** editor
- **Feature:** repos
- **Traces:** FLW-03
- **Entry point:** workspace → repository card → "Index"
- **Preconditions:** editor/owner; two or more repositories are connected
- **Steps:**
  1. User clicks Index on one repository -> system starts a run scoped to that repository and shows it on that card only
  2. User clicks Index on the second while the first runs -> system accepts it and shows "waiting for the running index" with its position, rather than refusing or running both
  3. First run finishes -> system starts the queued one automatically and the card moves from waiting to running
  4. User cancels the queued one -> system removes it from the queue and leaves the running one alone
- **Expected result:** repository indexes are independent in scope and serial in execution, and the interface says which of the two is true at any moment
- **Alt paths:** only one repository exists -> the queue notice never appears
- **UI elements:** per-card Index action, run state (waiting / running / failed / done), queue position, Cancel, per-card last-indexed commit
- **States covered:** loading, error, success
- **Errors & recovery:** the running index is reaped as stale -> the queued one still starts and the reaped card says it was reaped with the step it died on; the queue is lost to a restart -> the waiting card says so and offers the action again, because a queue position is not a promise the process can keep across a deploy
- **Status:** draft
- **Coverage:** none yet; planned: backend/app/api/routes/repos.py (`_indexing_locks` is per-project today and per-process only), planned: frontend/src/components/workspace/DataWorkspace.tsx

### SCN-141: The answer names the repository it came from
- **Persona:** analyst
- **Feature:** repos
- **Traces:** FLW-03
- **Entry point:** chat answer that used code knowledge, with more than one repository connected
- **Preconditions:** two or more repositories are indexed
- **Steps:**
  1. User asks a question about the code -> system answers and attributes each cited file to its repository by name
  2. User opens the seal -> system lists which repositories were searched and which returned nothing
  3. User clicks a citation -> system opens the document or symbol in the repository it belongs to
- **Expected result:** with several repositories connected, an answer is never ambiguous about which one it describes
- **Alt paths:** only one repository is connected -> the name is still shown, so the format does not change when a second is added
- **UI elements:** per-citation repository label, seal repository list with searched/empty state, citation links
- **States covered:** empty, success
- **Errors & recovery:** a citation's repository can no longer be resolved -> the label reads "repository removed" and the citation still renders, since it records what the answer used
- **Status:** draft
- **Coverage:** none yet; planned: frontend/src/components/ui/Seal.tsx, planned: backend/app/knowledge/pipeline_runner.py (chunk attribution), planned: backend/app/agents/knowledge_agent.py

### SCN-142: Disconnect a repository
- **Persona:** owner
- **Feature:** repos
- **Traces:** FLW-03
- **Entry point:** workspace → repository card → Delete
- **Preconditions:** owner; the repository is connected
- **Steps:**
  1. User clicks Delete -> system asks for confirmation and names exactly what will be removed: the repository, its documents, its symbols and edges, its search snapshot, and what will be kept
  2. User confirms by typing or pressing the destructive action -> system removes the repository and its derived knowledge
  3. User returns to the workspace -> the card is gone, the other repositories are untouched, and the document count has fallen by the removed repository's share
- **Expected result:** the repository and only its own knowledge are removed, and the user was told what that included before agreeing
- **Alt paths:** user cancels -> nothing is removed; the repository has an index running -> the confirmation says the run will be cancelled first
- **UI elements:** Delete action, confirmation dialog naming removed and kept artefacts, destructive-styled confirm, Cancel
- **States covered:** loading, error, success
- **Errors & recovery:** delete fails midway -> the card stays with a "partially removed" state and a Retry, rather than disappearing while its knowledge remains; cleanup of on-disk artefacts is best effort and the dialog says so, because a snapshot lives on an ephemeral disk the request cannot reach
- **Status:** draft
- **Coverage:** none yet; planned: backend/app/services/indexing_artifacts.py, planned: backend/app/api/routes/repos.py, planned: frontend/src/components/workspace/DataWorkspace.tsx

### SCN-143: Repository access is refused — recovery without losing the form
- **Persona:** owner
- **Feature:** repos
- **Traces:** FLW-03
- **Entry point:** repository form of SCN-137, on a failing access probe
- **Preconditions:** the URL or the key is wrong
- **Steps:**
  1. User submits a repository whose key has no access -> system reports "authenticated, but this key cannot read that repository" and keeps every field
  2. User switches the SSH key in the same form -> system re-probes without the user retyping the URL or branch
  3. Probe succeeds -> system enables Create and shows the resolved head
- **Expected result:** a failed probe is diagnosable and recoverable in place, and no input is lost to it
- **Alt paths:** the user has no key yet -> the form links to key creation and returns with the new key selected
- **UI elements:** probe result panel with the distinguished reason, SSH-key select, re-probe indicator, Create (disabled until a probe passes), preserved field values
- **States covered:** loading, error, success
- **Errors & recovery:** host unreachable, host-key unknown, key rejected, repository not found and branch not found are five different messages, not one "could not connect"; a key the user does not own is refused as not-found per SCN-121, and the message must not confirm the id exists
- **Status:** draft
- **Coverage:** none yet; planned: frontend/src/components/workspace/DataWorkspace.tsx, backend/app/api/routes/repos.py (`check-access`)
