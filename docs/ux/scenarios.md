# UX Scenarios

<!-- Managed with super-ux (scenario-format v1). Update in the same change as any user-facing behavior change. -->

Source of truth for all user-facing behavior of CheckMyData.ai. Built by an
Init (existing-code) inventory sweep on 2026-07-19 — every entry is reverse-
engineered from shipped code with `file:line` evidence, and every gap the sweep
found is recorded as a `draft` scenario with `Coverage: none yet`. Paths are
relative to `frontend/src/` unless noted. All entries start `draft`; only a
human review moves them to `validated`.

## Index

| ID | Title | Feature | Persona | Status | Last audit |
|----|-------|---------|---------|--------|------------|
| SCN-001 | First-run onboarding wizard — happy path | onboarding | new-user | implemented | 2026-07-19 PASS |
| SCN-002 | Onboarding — connection test fails, retry/edit | onboarding | new-user | implemented | 2026-07-19 PASS |
| SCN-003 | Onboarding — skip setup / try demo | onboarding | new-user | implemented | 2026-07-19 PASS |
| SCN-004 | Request project access (non-approved user) | onboarding | new-user | implemented | 2026-07-19 PASS |
| SCN-005 | Register with email + password | auth | new-user | implemented | 2026-07-19 PASS |
| SCN-006 | Log in with email + password | auth | analyst | implemented | 2026-07-19 PASS |
| SCN-007 | Sign in with Google | auth | analyst | implemented | 2026-07-19 PASS |
| SCN-008 | Log out | auth | analyst | draft | 2026-07-19 PARTIAL |
| SCN-009 | Change password | auth | analyst | implemented | 2026-07-19 PASS |
| SCN-010 | Delete account | auth | analyst | implemented | 2026-07-19 PASS |
| SCN-011 | Session expiry → forced re-login | auth | analyst | implemented | 2026-07-19 PASS |
| SCN-012 | Email verification after registration | auth | new-user | draft | 2026-07-19 FAIL |
| SCN-013 | Forgot / reset password | auth | analyst | draft | 2026-07-19 FAIL |
| SCN-014 | Accept a pending project invite | invites | analyst | implemented | 2026-07-19 PASS |
| SCN-015 | Decline / reject an invite | invites | analyst | draft | 2026-07-19 FAIL |
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
| SCN-037 | Connections — empty state | connections | owner | implemented | 2026-07-19 PASS |
| SCN-038 | Add an SSH key | ssh-keys | owner | implemented | 2026-07-19 PASS |
| SCN-039 | Delete an SSH key | ssh-keys | owner | implemented | 2026-07-19 PASS |
| SCN-040 | SSH keys — empty state | ssh-keys | owner | implemented | 2026-07-19 PASS |
| SCN-041 | Ask a data question — streaming happy path | chat | analyst | implemented | 2026-07-19 PASS |
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
| SCN-054 | View the agent reasoning panel | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-055 | Step-limit reached → continue analysis | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-056 | Session-continuation (auto-summary) banner | chat | analyst | implemented | 2026-07-19 PASS |
| SCN-057 | View & switch chart type | viz | analyst | implemented | 2026-07-19 PASS |
| SCN-058 | Export a result (CSV / JSON / XLSX) | viz | analyst | implemented | 2026-07-19 PASS |
| SCN-059 | Compound multi-query results | viz | analyst | implemented | 2026-07-19 PASS |
| SCN-060 | Chart render failure → table fallback | viz | analyst | implemented | 2026-07-19 PASS |
| SCN-061 | Browse indexed docs | knowledge | analyst | implemented | 2026-07-19 PASS |
| SCN-062 | Knowledge health & re-index actions | knowledge | editor | validated | 2026-07-19 PARTIAL |
| SCN-063 | Knowledge freshness warnings | knowledge | analyst | implemented | 2026-07-19 PASS |
| SCN-064 | Nightly sync history | knowledge | owner | implemented | 2026-07-19 PASS |
| SCN-065 | View & filter the insights feed | insights | analyst | implemented | 2026-07-19 PASS |
| SCN-066 | Confirm / dismiss / resolve an insight | insights | analyst | implemented | 2026-07-19 PASS |
| SCN-067 | Browse the metric catalog | insights | analyst | validated | 2026-07-19 PARTIAL |
| SCN-068 | Saved-queries panel (scopes & empty) | notes | analyst | implemented | 2026-07-19 PASS |
| SCN-069 | Run a saved query | notes | analyst | implemented | 2026-07-19 PASS |
| SCN-070 | Share / unshare a saved query | notes | analyst | implemented | 2026-07-19 PASS |
| SCN-071 | Edit a saved-query comment | notes | analyst | implemented | 2026-07-19 PASS |
| SCN-072 | Delete a saved query | notes | analyst | implemented | 2026-07-19 PASS |
| SCN-073 | View agent learnings | learnings | editor | implemented | 2026-07-19 PASS |
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
| SCN-084 | View a shared dashboard | dashboards | viewer | validated | 2026-07-19 PARTIAL |
| SCN-085 | Shared dashboard link invalid / expired | dashboards | viewer | implemented | 2026-07-19 PASS |
| SCN-086 | Delete a dashboard | dashboards | editor | draft | 2026-07-19 FAIL |
| SCN-087 | Run a batch of queries | batch | analyst | implemented | 2026-07-19 PASS |
| SCN-088 | Build a batch from saved notes | batch | analyst | implemented | 2026-07-19 PASS |
| SCN-089 | View batch results | batch | analyst | draft | 2026-07-19 FAIL |
| SCN-090 | Create a scheduled query + alerts | schedules | owner | implemented | 2026-07-19 PASS |
| SCN-091 | Edit / pause / run-now a schedule | schedules | owner | implemented | 2026-07-19 PASS |
| SCN-092 | Delete a schedule | schedules | owner | implemented | 2026-07-19 PASS |
| SCN-093 | View schedule run history | schedules | owner | implemented | 2026-07-19 PASS |
| SCN-094 | Feedback analytics panel | analytics | owner | implemented | 2026-07-19 PASS |
| SCN-095 | Open settings & navigate | settings | analyst | implemented | 2026-07-19 PASS |
| SCN-096 | Change theme (light / system / dark) | settings | analyst | implemented | 2026-07-19 PASS |
| SCN-097 | Reduced-motion honored | settings | analyst | implemented | 2026-07-19 PASS |
| SCN-098 | Upgrade via pricing → Stripe checkout | billing | owner | validated | 2026-07-19 PARTIAL |
| SCN-099 | Manage billing (Stripe portal) | billing | owner | implemented | 2026-07-19 PASS |
| SCN-100 | Hit token / quota limit (HTTP 402) | billing | analyst | validated | 2026-07-19 PARTIAL |
| SCN-101 | Billing disabled (self-hosted) degradation | billing | owner | implemented | 2026-07-19 PASS |
| SCN-102 | View usage stats | usage | owner | implemented | 2026-07-19 PASS |
| SCN-103 | Mint & copy an MCP token | mcp-tokens | api-consumer | implemented | 2026-07-19 PASS |
| SCN-104 | Revoke an MCP token | mcp-tokens | api-consumer | implemented | 2026-07-19 PASS |
| SCN-105 | Background tasks — view/cancel/retry/dismiss | tasks | analyst | validated | 2026-07-19 PARTIAL |
| SCN-106 | Request history & trace detail | logs | owner | implemented | 2026-07-19 PASS |
| SCN-107 | Runs & Errors log tabs | logs | owner | validated | 2026-07-19 PARTIAL |
| SCN-108 | Live activity log stream | logs | analyst | implemented | 2026-07-19 PASS |
| SCN-109 | Landing page → Get Started | marketing | visitor | implemented | 2026-07-19 PASS |
| SCN-110 | Pricing CTA (logged out) | marketing | visitor | validated | 2026-07-19 PARTIAL |
| SCN-111 | Support / Contact / Legal pages | marketing | visitor | implemented | 2026-07-19 PASS |
| SCN-112 | Logged-in visitor auto-redirect to /app | marketing | analyst | implemented | 2026-07-19 PASS |

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
- **Errors & recovery:** create fails → toast "Failed to create connection"; index timeout → inline "Indexing had issues, but you can still use the app" + toast + Continue; complete fails → toast "Failed to complete onboarding" (`OnboardingWizard.tsx:159,209,236`)
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
- **Expected result:** onboarding is dismissed (demo path sets up sample data); wizard does not reappear (`is_onboarded` set)
- **UI elements:** "Try demo instead" button, "Skip setup entirely" button, Escape-to-skip, step-3 "Skip"
- **States covered:** success, error
- **Errors & recovery:** demo setup fails → toast "Failed to set up demo"; skip fails → toast "Failed to skip onboarding" (`OnboardingWizard.tsx:280,251`)
- **Status:** implemented
- **Coverage:** components/onboarding/OnboardingWizard.tsx:761-766,798-804,88-90

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
- **Status:** implemented
- **Coverage:** components/projects/RequestAccessModal.tsx:26,38-73,90-132

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
- **Errors & recovery:** invalid email → inline "Please enter a valid email address"; password <8 → inline "Password must be at least 8 characters"; register fails → inline error block + toast "Registration failed" (`login/page.tsx:133-135,224-227`; `auth-store.ts:118-122`)
- **Status:** implemented
- **Coverage:** app/login/page.tsx:34,166-254; stores/auth-store.ts:111-123

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
- **Errors & recovery:** invalid email → inline message; login fails → inline error + toast "Login failed" (`auth-store.ts:105-109`)
- **Status:** implemented
- **Coverage:** app/login/page.tsx:242-254,116-122; stores/auth-store.ts:98-110

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
- **Expected result:** stores/storage cleared, `user=null`, AuthGate redirects to `/login`
- **UI elements:** "Sign Out" button
- **States covered:** success
- **Errors & recovery:** none surfaced — server logout is best-effort and swallowed (`auth-store.ts:147`). GAP: no confirm and no loading/success feedback on logout
- **Status:** draft
- **Coverage:** components/auth/AccountMenu.tsx:80-86; stores/auth-store.ts:138-172
- **Decision (2026-07-19):** rework approved — add success feedback (and/or confirm) on logout; stays draft until built (task spawned)

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
- **Entry point:** any authenticated screen when the refresh timer expires
- **Preconditions:** authenticated session reaches expiry
- **Steps:**
  1. Refresh timer fires
- **Expected result:** toast "Your session has expired. Please log in again." then auto-logout → `/login`
- **UI elements:** toast, AuthGate "Redirecting..."
- **States covered:** error
- **Errors & recovery:** this IS the recovery path — user re-authenticates via SCN-006/007
- **Status:** implemented
- **Coverage:** stores/auth-store.ts:74,87; components/auth/AuthGate.tsx:16-36

### SCN-012: Email verification after registration
- **Persona:** new-user
- **Feature:** auth
- **Entry point:** post-registration (backend `POST /api/auth/verify-email`, F-PROJ-01)
- **Preconditions:** email/password registration with `email_verified=False`
- **Steps:**
  1. User registers and should be prompted to verify their email before email-invite auto-accept
- **Expected result:** a visible verification prompt / status and a way to resend
- **UI elements:** (none in frontend)
- **States covered:** none
- **Errors & recovery:** n/a
- **Status:** draft
- **Coverage:** none yet — GAP: backend enforces email verification (CLAUDE.md F-PROJ-01) but no frontend UI exists (`lib/api/auth.ts` has no verify endpoint; no verification screen)
- **Decision (2026-07-19):** confirmed bug — build email-verification UI (prompt + resend + `POST /api/auth/verify-email`); task spawned

### SCN-013: Forgot / reset password
- **Persona:** analyst
- **Feature:** auth
- **Entry point:** `/login` (would-be "Forgot password?" link)
- **Preconditions:** password-based account, user cannot log in
- **Steps:**
  1. User requests a reset from the login screen
  2. User sets a new password via a reset link
- **Expected result:** user regains access without contacting support
- **UI elements:** (none)
- **States covered:** none
- **Errors & recovery:** n/a
- **Status:** draft
- **Coverage:** none yet — GAP: no forgot/reset-password flow anywhere; only authenticated "Change Password" (requires current password) exists
- **Decision (2026-07-19):** confirmed bug — build forgot/reset-password flow (request + reset-via-link); task spawned

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
- **Entry point:** Pending Invitations banner
- **Preconditions:** ≥1 pending invite
- **Steps:**
  1. User declines an unwanted invite
- **Expected result:** invite removed from the user's pending list without joining
- **UI elements:** (none)
- **States covered:** none
- **Errors & recovery:** n/a
- **Status:** draft
- **Coverage:** none yet — GAP: only "Accept" exists; there is no decline/reject affordance (`PendingInvites.tsx:67-73`)
- **Decision (2026-07-19):** confirmed bug — add Decline/Reject action in PendingInvites; task spawned

## projects

### SCN-016: Create a project
- **Persona:** owner
- **Feature:** projects
- **Entry point:** sidebar "New project" action → "New Project" FormModal
- **Preconditions:** authenticated with `can_create_projects`
- **Steps:**
  1. User opens New Project
  2. User enters a name, optionally a Git repo URL (+ SSH key/branch), optionally LLM models
  3. User clicks "Create"
- **Expected result:** project created, prepended, set active; toast "Project created"
- **UI elements:** name input, repo URL input, SSH key select, branch select/input, LLM "details", "Use Agent model" checkbox, Create button
- **States covered:** loading (repo access check), error, success
- **Errors & recovery:** empty name → inline "Name is required"; repo access denied → inline red text; SSH URL without key → inline "add an SSH key first"; create fails → toast (`ProjectSelector.tsx:296-299,322-327,512-538`)
- **Status:** implemented
- **Coverage:** components/projects/ProjectSelector.tsx:461-655; components/Sidebar.tsx:749

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
- **Errors & recovery:** parallel load fails → toast "Failed to load project data" and connections/sessions reset; stale responses ignored via sequence guard (`ProjectSelector.tsx:379-425`)
- **Status:** implemented
- **Coverage:** components/projects/ProjectSelector.tsx:379-425,679-729

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
- **Status:** implemented
- **Coverage:** components/projects/InviteManager.tsx:237-254,149-165

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
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:1144-1184,116-165

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
- **States covered:** empty
- **Errors & recovery:** n/a. Known gap: the connections list has no list-level loading spinner (populated via project switch)
- **Status:** implemented
- **Coverage:** components/connections/ConnectionSelector.tsx:1076-1080,613; components/connections/ConnectionsPanel.tsx:12-37

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
- **UI elements:** auto-growing textarea, send button, char-remaining counter, PlanSummaryCard, ThinkingLog, ToolCallIndicator, StageProgress, "■ Stop generating"
- **States covered:** loading, success, error
- **Errors & recovery:** session auto-create fails → toast + abort; stream error → in-transcript red "Error: …" bubble with optional Retry (`ChatPanel.tsx:417-420,611-621`)
- **Status:** implemented
- **Coverage:** components/chat/ChatPanel.tsx:394-672,912-955; components/chat/ChatInput.tsx:16-65

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
- **Expected result:** feedback recorded; negative SQL feedback triggers a "wrong data" investigation message
- **UI elements:** thumbs up/down buttons (disabled while submitting)
- **States covered:** loading, error, success
- **Errors & recovery:** submit fails → toast "Failed to submit feedback" (`ChatMessage.tsx:290-292`). GAP: the richer WrongDataModal investigation flow is not wired in — thumbs-down sends a canned prompt instead
- **Status:** implemented
- **Coverage:** components/chat/ChatMessage.tsx:271-292,648-679

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
- **Expected result:** Plan (tables/strategy/rules/learnings/warnings), Thinking log, and per-step timeline with elapsed time
- **UI elements:** reasoning toggle button, ReasoningPanel (close X, mobile bottom-sheet)
- **States covered:** empty ("No reasoning data available"), success
- **Errors & recovery:** none (trace is in-store; no async fetch). Button hidden when no trace
- **Status:** implemented
- **Coverage:** components/chat/ReasoningPanel.tsx:92-215; components/chat/ChatMessage.tsx:156-181

### SCN-055: Step-limit reached → continue analysis
- **Persona:** analyst
- **Feature:** chat
- **Entry point:** an answer returned with `response_type: step_limit_reached`
- **Preconditions:** the agent hit its live step budget
- **Steps:**
  1. User clicks "Continue analysis"
- **Expected result:** the agent resumes from where it stopped
- **UI elements:** "Continue analysis" button
- **States covered:** success
- **Errors & recovery:** as the normal stream (SCN-046)
- **Status:** implemented
- **Coverage:** components/chat/ChatMessage.tsx:619-642; components/chat/ChatPanel.tsx:215-315

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
- **Errors & recovery:** health fetch fails → "Could not load knowledge health"; trigger fails → toast "Action failed"; run failed → inline red text. Known gap: Cancel/Retry errors are swallowed silently (`KnowledgeHealthPanel.tsx:129-164`, `RunCard.tsx:82,91`)
- **Status:** validated
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
- **States covered:** loading, empty, success
- **Errors & recovery:** GAP — catalog fetch failure is swallowed to an empty list, so an error is indistinguishable from "No metrics found" (no error UI) (`KnowledgeHub.tsx:52-54`)
- **Status:** validated
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
- **States covered:** loading, empty, success
- **Errors & recovery:** load fails → toast "Failed to load learnings" (no inline error) (`LearningsPanel.tsx:58`)
- **Status:** implemented
- **Coverage:** components/learnings/LearningsPanel.tsx:240-432

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
- **Errors & recovery:** create fails → toast "Failed to create rule" (`RulesManager.tsx:97-101`). Requires non-empty name+content
- **Status:** implemented
- **Coverage:** components/rules/RulesManager.tsx:62-70,201-233

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
- **UI elements:** "Back to app", "Refresh All", card grid, ResultTable (cap 50 rows)
- **States covered:** loading, empty, success
- **Errors & recovery:** empty → "This dashboard has no cards yet."; per-card "No data" / "Note not found". Note: Refresh-All swallows per-card errors and still toasts success
- **Status:** validated
- **Coverage:** app/dashboard/[id]/page.tsx:198-325

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
- **Entry point:** dashboard list / viewer (would-be delete control)
- **Preconditions:** owner/editor of the dashboard
- **Steps:**
  1. User deletes a dashboard they no longer need
- **Expected result:** dashboard removed after confirmation
- **UI elements:** (none)
- **States covered:** none
- **Errors & recovery:** n/a
- **Status:** draft
- **Coverage:** none yet — GAP: no delete-dashboard UI exists anywhere (`dashboards.delete` unused). Dashboards can be created and edited but never deleted from the UI
- **Decision (2026-07-19):** confirmed bug — add a delete-dashboard action (list + viewer, owner/editor, with confirm); task spawned

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
- **Entry point:** after a batch completes
- **Preconditions:** a batch ran to completion
- **Steps:**
  1. User expects to see per-query results/detail
- **Expected result:** a results view with each query's output, errors, and export
- **UI elements:** (placeholder only)
- **States covered:** none
- **Errors & recovery:** n/a
- **Status:** draft
- **Coverage:** none yet — GAP: BatchResults is a stub rendering "Batch results for {id} (coming soon)"; there is no batch results/history screen (`components/batch/BatchResults.tsx:9-15`)
- **Decision (2026-07-19):** confirmed bug — build the batch results view (per-query output, errors, export); task spawned

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
- **Errors & recovery:** validation toasts (title/SQL/cron/connection); save fails → toast "Failed to save" (`ScheduleManager.tsx:181-243`)
- **Status:** implemented
- **Coverage:** components/schedules/ScheduleManager.tsx:444-612

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
- **Errors & recovery:** billing not live → toast "Billing is not enabled on this deployment"; checkout fails → toast "Checkout failed" (`PricingTable.tsx:101,109`). GAP: logged-out paid CTA routes to `/login?next=/pricing` but `/login` ignores `next`
- **Status:** validated
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
- **Errors & recovery:** GAP — the 402 message is plain text with no clickable upgrade CTA; upgrade lives only in BillingPanel/PricingTable (`lib/api/_client.ts:127-135`)
- **Status:** validated
- **Coverage:** lib/api/_client.ts:127-135

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
- **Errors & recovery:** GAP — Cancel/Retry failures are swallowed silently with no toast/inline feedback; Cancel has no confirm (`ActiveTasksWidget.tsx:119-149`)
- **Status:** validated
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
- **Errors & recovery:** queries load fails → banner "Failed to load logs" + Retry; trace fails → inline "Failed to load trace" (`LogsScreen.tsx:76,147-154`; `LogsTraceDetail.tsx:63-69`)
- **Status:** implemented
- **Coverage:** components/logs/LogsScreen.tsx:104-207; components/logs/LogsTraceDetail.tsx:44-141

### SCN-107: Runs & Errors log tabs
- **Persona:** owner
- **Feature:** logs
- **Entry point:** LogsScreen → Runs / Errors tabs
- **Preconditions:** active project
- **Steps:**
  1. User opens Runs (filter by kind) or Errors (filter source/status)
  2. In Errors, user cycles a row's status open → ack → resolved
- **Expected result:** runs / error rows listed; error status cycles
- **UI elements:** kind select + Refresh (Runs), source/status selects + Refresh + status-cycle button (Errors)
- **States covered:** loading, empty, error(silent), success
- **Errors & recovery:** GAP — Runs/Errors fetch failures silently show the empty state with no error message; status-cycle failure ignored (`RunsTab.tsx:19-21`, `ErrorsTab.tsx:31-49`)
- **Status:** validated
- **Coverage:** components/logs/RunsTab.tsx:34-59; components/logs/ErrorsTab.tsx:55-128

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
- **Errors & recovery:** GAP — the `next=/pricing` intent is dropped by `/login` (see SCN-098)
- **Status:** validated
- **Coverage:** components/marketing/PricingTable.tsx:91-99

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
- **Status:** implemented
- **Coverage:** app/(marketing)/support/page.tsx:117-249; app/(marketing)/contact/page.tsx:90-156

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
