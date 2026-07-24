# 03 — Независимая верификация UX-сценариев (Фаза 2, уровень кода)

- **Дата:** 2026-07-24
- **Объект:** `docs/ux/scenarios.md` (112 сценариев SCN-001..112, 25 доменов) против кода `frontend/src/` (Next.js 15 + React 19) и, где требовалось, `backend/app/`.
- **Метод:** только статический анализ (Read/Grep/Glob). Тесты, dev-серверы и сборки не запускались (в фоне шёл тестовый прогон). Статусы `implemented` и прошлые аудиты в файле сценариев игнорировались — вердикты выставлены только по коду. Тексты тостов/сообщений, приведённые в сценариях в кавычках, сверялись дословно.
- **Критерии:** PASS — всё ключевое (шаги, элементы, состояния, тексты, роли) на месте; PARTIAL — заявленный элемент/состояние отсутствует, но основной флоу работает; FAIL — поведение отсутствует или принципиально иное.
- Пути в таблице относительны `frontend/src/`, если не указано иное.

## Сводка

| Вердикт | Кол-во |
|---|---|
| PASS | 109 |
| PARTIAL | 3 (SCN-041, SCN-054, SCN-077) |
| FAIL | 0 |

| Severity находок | Кол-во |
|---|---|
| Critical | 0 |
| High | 1 |
| Medium | 5 |
| Low | 15 |
| Info (подтверждённые задокументированные GAP'ы, дрейф ссылок) | 8 |

PARTIAL-вердикты выставлены за отсутствие конкретных заявленных UI-элементов, а не за поломку флоу: у SCN-041 нет auto-growing textarea, у SCN-054 нет per-step elapsed, у SCN-077 нет кнопки Cancel в модалке создания правила. Единственная High-находка — потеря пользовательской обратной связи на 401-пути истечения сессии (см. сквозные аспекты).

## Таблица верификации (112 сценариев)

| ID | Название | Вердикт | Evidence / комментарий |
|----|----------|---------|------------------------|
| SCN-001 | Onboarding wizard — happy path | PASS | `OnboardingWizard.tsx:127-188,549-660,781-793`; entry `app/app/page.tsx:122-123,175`. 5 шагов, auto-test + auto-advance, «Indexing complete», step 3 Optional, «Finish setup»; тексты ошибок дословно (:159,:209,:236,:583). Refs `page.tsx:121-122,174` уехали на +1 строку. |
| SCN-002 | Onboarding — test fails, retry/edit | PASS | `OnboardingWizard.tsx:498-547`: «Testing connection...», «Connection failed» + detail, «Edit connection» → step 0, «Retry» → re-run. |
| SCN-003 | Onboarding — skip / try demo | PASS | `OnboardingWizard.tsx:760-767,797-805,86-91,242-284`: «Try demo instead», «Skip setup entirely», Escape, step-3 «Skip»; тосты «Failed to set up demo» (:280), «Failed to skip onboarding» (:251) дословно. |
| SCN-004 | Request project access | PASS | `OnboardingWizard.tsx:310-315`; `ProjectSelector.tsx:277-288`; `RequestAccessModal.tsx:20-73,131`: prefilled email, «Send request», «Request sent» + toast, «Got it», «Failed to send request» (:40) — всё дословно. |
| SCN-005 | Register email+password | PASS | `login/page.tsx:146-253`; `auth-store.ts:112-123`: mode-switch, inline «Please enter a valid email address» (:222), «Password must be at least 8 characters» (:246), «Create Account», inline error + toast «Registration failed». Refs съехали (валидация реально :153-155,:220-224,:244-247). |
| SCN-006 | Log in email+password | PASS | `login/page.tsx:266-285`; `auth-store.ts:99-110`: «Sign In»/«Signing in...», inline error, toast «Login failed». Дрейф refs (кнопка :273-285, submit :151-162). |
| SCN-007 | Sign in with Google | PASS | `login/page.tsx:75-134,287-306`; `auth-store.ts:125-136`: GIS-кнопка только при `GOOGLE_CLIENT_ID` (иначе отсутствует полностью), nonce+CSRF, «Signing in with Google...», toast «Google sign-in failed». |
| SCN-008 | Log out | PASS | `AccountMenu.tsx:80-89`; `SettingsPanel.tsx:104-114`; `auth-store.ts:138-172`: «Sign Out», toast «Signed out» дословно, storage/stores cleared, server logout best-effort, AuthGate → /login. Двойного тоста нет. |
| SCN-009 | Change password | PASS | `AccountMenu.tsx:110-178`; `SettingsPanel.tsx:199-264`: скрыто для Google-only, «Password changed successfully», <8 → toast, fail → server msg или «Failed to change password». Refs SettingsPanel уехали ~20 строк. |
| SCN-010 | Delete account | PASS | `AccountMenu.tsx:180-230`; `SettingsPanel.tsx:266-316`: type-`DELETE` gate, «Account deleted», «Failed to delete account», logout. Нюанс: в SettingsPanel нет фразы «This action cannot be undone» (только в AccountMenu :202) — находка Low. |
| SCN-011 | Session expiry → forced re-login | PASS | `auth-store.ts:56-91` (точно :74,:87): toast «Your session has expired. Please log in again.» дословно → `logout()` → `AuthGate.tsx:16-36` «Redirecting...» → /login. NB: 401-перехватчик `_client.ts` использует ДРУГОЙ текст — см. находки M2/H1. |
| SCN-012 | Email verification | PASS | `EmailVerifyBanner.tsx:22-60`; `verify-email/page.tsx:23-137`; `app/app/page.tsx:323`; backend `auth.py:44,138-180,386`, `auth_service.py:131-156`: баннер скрыт для verified/Google, loading/success/error/missing-token состояния, resend 3/min, `already_verified` no-op, auto-accept invites. Тост длиннее цитаты («— check your inbox.») — Low. |
| SCN-013 | Forgot / reset password | PASS | `forgot-password/page.tsx`; `reset-password/page.tsx`; `login/page.tsx:255-264`; backend `auth.py:183-226`, `auth_service.py:162-221`, `user.py:42-45`: generic `{"ok": true}` без enumeration, SHA-256+1h, single-use, `token_version` bump (:218), 5/min, 422 при <8, все UI-состояния на месте. |
| SCN-014 | Accept invite | PASS | `PendingInvites.tsx:17-48,63-100`; `Sidebar.tsx:478,669`: auto-load, Spinner, скрыт при пустом, «Accept»→«...», row removed, projects reloaded, «Invite accepted»; load/accept fail → тосты. Coverage-ref «29-73» уехал (:17-48). |
| SCN-015 | Decline invite | PASS | `PendingInvites.tsx:50-61,85-101`; `lib/api/workspace.ts:106-107`; backend `invites.py:212-227`, `invite_service.py:122-158`: aria-label, обе кнопки disabled в полёте, «Invite declined», row удаляется сервером (constraint-safe re-invite), 400/403/404. |
| SCN-016 | Create a project | PASS | `ProjectSelector.tsx:295-328,467-658`; `Sidebar.tsx:749`: «Project created», «Name is required», repo access check 800ms debounce, «SSH URL detected — add an SSH key first», LLM details. Coverage-дрейф ~5 строк. |
| SCN-017 | Switch between projects | PASS | `ProjectSelector.tsx:379-425,687-723`: sequence guard `selectSeqRef`, role swap, connections/sessions reload, first connection auto-selected, welcome session ensured, «Failed to load project data» + reset, per-row Spinner. |
| SCN-018 | Edit a project | PASS | `ProjectSelector.tsx:339-377,745-753`: pencil только внутри owner-блока (:731), «Project updated», «Failed to update project», empty name inline, «Edit Project»/Save Changes. |
| SCN-019 | Delete a project | PASS | `ProjectSelector.tsx:427-457`; `ConfirmModal.tsx:64,126-127,182`: severity critical + detail + type-to-confirm именем проекта (строгое `typed === confirmText`), очистка active state, «Failed to delete project». Trash owner-only. |
| SCN-020 | Project overview — empty | PASS | `ProjectOverview.tsx:36-45,76,90`: «Select a project to see its overview», «No connections configured yet», «No recent pipeline errors» — дословно; last 5 failed (`slice(-5)`); embedded HomeAsk/Health/Usage. |
| SCN-021 | Invite member & set role | PASS | `ProjectSelector.tsx:733-773`; `InviteManager.tsx:186-212`: email+role select, Enter submit, «Invite sent», inline error, «Failed to load access data». Owner-only entry. |
| SCN-022 | Change member's role | PASS | `InviteManager.tsx:149-165,237-254`: optimistic apply → revert при ошибке + toast, «Role updated», select только для non-owner (owner — статичный бейдж), без confirm — как заявлено. |
| SCN-023 | Remove a member | PASS | `InviteManager.tsx:131-147,256-264`: confirm warning без type-to-confirm, «Member removed», fail toast. Цитата detail неточная (многоточие в сценарии) — Low. |
| SCN-024 | Resend / revoke invite | PASS | `InviteManager.tsx:92-129,271-305`: resend с cooldown ровно 60s → «Sent!», «Invite email resent»; revoke через confirm warning → «Invite deleted»; Pending скрыт при пустом. |
| SCN-025 | Add DB connection | PASS | `ConnectionSelector.tsx:623-835,1028-1035`; `Sidebar.tsx:536,786` (owner): DB-type select, auto-port с guard `knownDefaults.includes(prev.db_port)` (:651-653), «Connection created», «Failed to create connection», empty name → silent return. |
| SCN-026 | Connection-string autofill | PASS | `ConnectionSelector.tsx:732-772,836-840`; `lib/connection-string.ts`: «Use connection string» + paste-autofill, «Detected: {type}…», inline note про SSH tunnel. |
| SCN-027 | Add MCP connection | PASS | `ConnectionSelector.tsx:668-729,319-338,1132`: transport stdio/sse, command/args vs URL, env JSON, три валидационных тоста дословно, «MCP» badge, read-only/SSH скрыты. |
| SCN-028 | SSH tunnel на connection | PASS | `ConnectionSelector.tsx:843-1005,314-317,654`: SSH host/port/user/key, inline warning, Exec Mode + presets + templates, MongoDB — disabled + auto-off + «(not supported for MongoDB)». |
| SCN-029 | Read-only toggle | PASS | `ConnectionSelector.tsx:1010-1025,1134-1138`; `connection-form-helpers.ts:36` (default on); «RO» badge. Backend enforcement: `postgres.py:117`, `mysql.py:64`, `clickhouse.py:116`, `mongodb.py:224`, `core/safety.py`. |
| SCN-030 | Test a connection | PASS | `ConnectionSelector.tsx:1283-1289,497-515,1051-1063`: «Connected», «Not connected: …», error status stored, StatusDot «Checking...». |
| SCN-031 | Edit a connection | PASS | `ConnectionSelector.tsx:1290-1297,389-495`: `canManageProject`=owner (`usePermission.ts:25`), password blank keeps existing (:432), валидации как create, «Connection updated». |
| SCN-032 | Delete a connection | PASS | `ConnectionSelector.tsx:1307-1315,580-611`: `canDelete`=owner, critical confirm + type-`DELETE`, список удаляемого, active cleared, «Failed to delete connection». |
| SCN-033 | Index / re-index | PASS | `ConnectionSelector.tsx:1144-1184,116-169`: pulsing «IDX...», «DB indexed: n/m active tables», timeout/partial/failed/poll-lost тосты; `canIndex`=owner\|editor; viewer — статичный span-бейдж (:1163-1169). |
| SCN-034 | Code↔DB sync | PASS | `ConnectionSelector.tsx:1185-1247,171-219`; `SyncStatusIndicator.tsx:91-132`: «SYNC...», «Code-DB synced: n/m tables matched», «…ensure DB is indexed first»; gate `isActive && is_indexed && canIndex`; viewer — статичный бейдж. |
| SCN-035 | Refresh schema cache | PASS | `ConnectionSelector.tsx:1298-1306,517-530`: gated `isActive && !mcp && canIndex`, «Schema refreshed», «Schema refresh failed». |
| SCN-036 | Connection health & reconnect | PASS | `ConnectionHealth.tsx:73-151`: SSE-подписка, dot+tooltip, RECONNECT только при down, «Reconnect failed», fetch fail silent; row banner «Connection is unreachable» (`ConnectionSelector.tsx:1318-1323`). |
| SCN-037 | Connections — empty state | PASS | `ConnectionSelector.tsx:1076-1080,613`; `ConnectionsPanel.tsx:12-17`: «No connections yet» / «Select a project first». Задокументированный gap (нет list-level spinner) подтверждён. |
| SCN-038 | Add SSH key | PASS | `SshKeyManager.tsx:218-290`: name+key+passphrase, help с copyable commands, inline error, disabled до name+key, «SSH key added», type badge + fingerprint. |
| SCN-039 | Delete SSH key | PASS | `SshKeyManager.tsx:316-324,183-205`: warning confirm с текстом «Connections using this key will lose SSH tunnel access.» дословно, «SSH key deleted». |
| SCN-040 | SSH keys — empty state | PASS | `SshKeyManager.tsx:327-331,292,150-155`: «No SSH keys added yet», Spinner, «Failed to load SSH keys». |
| SCN-041 | Streaming happy path | PARTIAL | `ChatPanel.tsx:394-672,912-955`; `ChatInput.tsx:16-65`: streaming, PlanSummaryCard/ThinkingLog/ToolCallIndicator/StageProgress, «■ Stop generating», auto-create fail → toast + abort, char-counter. **Не реализован заявленный auto-growing textarea** — `ChatInput.tsx:32-48` жёстко `rows={1}` + `max-h-40 overflow-y-auto` (скролл вместо роста). |
| SCN-042 | Quick-ask from overview | PASS | `HomeAsk.tsx:16-55`: maxLength 2000, disabled + «Add a connection to start asking» дословно; pickup в `ChatPanel.tsx:706-714` с гардой от двойной отправки. |
| SCN-043 | Stop / abort answer | PASS | `ChatPanel.tsx:674-696,925-951`: суффикс `*(Generation stopped by user)*` дословно (:690); abort при смене сессии с коммитом partial в prev-сессию (:353-390) — но суффикс другой (:382, «switched session») — Low. |
| SCN-044 | Empty chat + suggestion chips | PASS | `ChatPanel.tsx:824-851,982-988,334`; `SuggestionChips.tsx:11-63`: hero «Ready to query»/«Knowledge Base Mode», skeleton, «Could not load suggestions» дословно + chips скрыты. |
| SCN-045 | Readiness gate | PASS | `ReadinessGate.tsx:74-336`: checklist, per-step Run, «Re-index» на stale, «Chat anyway», «Start chatting», «Failed to check project readiness» + Retry дословно (:177-199), auto-bypass (:74-76), poll-timeout toast. Лёгкий дрейф refs. |
| SCN-046 | Mid-stream error + retry | PASS | `ChatPanel.tsx:611-633,854-872`; `ChatMessage.tsx:605-616`: красный «Error: …» в транскрипте, Retry только при `is_retryable !== false` и только для последнего сообщения. |
| SCN-047 | Knowledge-only chat | PASS | `ChatPanel.tsx:756-784`: «No database connection configured.», «Chat with Knowledge Base» → `knowledge_only`, баннер + Exit. |
| SCN-048 | Create/switch/delete sessions | PASS | `ChatSessionList.tsx:70-276`; `Sidebar.tsx:542,799`: «New chat», confirm «Delete this chat session?» дословно, очистка `messagesBySession`, «Show all N», тосты load/delete/create fail. Заявленный GAP (нет rename/bulk clear) подтверждён. |
| SCN-049 | Resume in-progress session | PASS | `ChatPanel.tsx:86-87,956-979`; `useSessionPolling.ts:26-91`; `lib/polling.ts:1-2`: «Processing in background…», poll 3с, кап 15 мин, network errors молча ретраятся; спиннер в строке сессии (`ChatSessionList.tsx:90-92`); backend `chat.py:740`. |
| SCN-050 | Pipeline checkpoint | PASS | `ChatPanel.tsx:131-213,883-911`; `StageProgress.tsx:150-177`; `CheckpointCard.tsx:92-148`; `StageRow.tsx:114-118`: «Continue pipeline»/«Modify plan»+input/«Retry stage» дословно, failed stage inline красным, «Show all N stages». |
| SCN-051 | Clarification request | PASS | `ClarificationCard.tsx:42-121`: yes/no, multiple-choice, free-text, numeric-range; «You answered: …» дословно (:30); submit → handleSend (`ChatMessage.tsx:411-417`). |
| SCN-052 | Rate answer / wrong data | PASS | `ChatMessage.tsx:264-295,648-679`: thumbs disabled в полёте, «Failed to submit feedback» дословно, thumbs-down на SQL → canned investigation prompt. GAP подтверждён: `WrongDataModal.tsx` нигде не импортируется. |
| SCN-053 | Save answer to notes | PASS | `ChatMessage.tsx:297-327,682-694`: «Query saved to notes» + «Failed to save note» дословно, prepend (`notes-store.ts:64`), панель открывается (`setOpen(true)`), bookmark pulse/disabled/«Saved to notes». |
| SCN-054 | Reasoning panel | PARTIAL | `ChatMessage.tsx:156-181` (кнопка скрыта без trace); `ReasoningPanel.tsx:110-256`: Plan/Thinking/steps, «No reasoning data available», close X, mobile bottom-sheet. **Per-step elapsed НЕ рендерится** (StepRow :42-86 — только label+agent; `elapsed_ms` собирается в `ChatPanel.tsx:467`, но нигде не выводится; общий elapsed — в шапке :117-134). |
| SCN-055 | Step-limit → continue | PASS | `ChatMessage.tsx:619-642` («Partial Result», «Continue analysis» дословно); `ChatPanel.tsx:215-315,874-876` (pipeline_action continue_analysis + continuation_context); backend `orchestrator.py:1735,1767`. |
| SCN-056 | Session-continuation banner | PASS | `ChatPanel.tsx:644-667`; `ChatMessage.tsx:252-262`; `SessionContinuationBanner.tsx:18-60`: «Conversation continued (N messages summarized)» дословно, summary preview + topic chips. |
| SCN-057 | View & switch chart type | PASS | `SQLResultSection.tsx:70-93,127-150,175-181`; `VizToolbar.tsx:61-80`; `viz-utils.ts:4-20`: 5 типов, спиннер, мобильный «Tap to view chart», re-render fail → «Failed to re-render visualization» + revert типа. Backend `visualizations.py:30`. |
| SCN-058 | Export CSV/JSON/XLSX | PASS | `DataTable.tsx:11,23-39,49-61,104-113`; backend `visualizations.py:43-78`: три формата blob-download, cap 500 («Showing 500 of N rows — click to show all»), «Export failed». |
| SCN-059 | Compound multi-query | PASS | `ChatMessage.tsx:419-432`; `SQLResultSection.tsx:97-208`: «Query {i} of {N}», per-block toolbar/SQLExplainer/InsightCards, per-block re-render error → тост. |
| SCN-060 | Chart failure → table fallback | PASS | `ChartRenderer.tsx:64-116,220-228`: error boundary → «Chart could not be rendered» + «Try switching to Table view using the toolbar above» (вторая строка длиннее цитаты — Low), без тоста и краша; «No chart data available», «Unsupported chart type». |
| SCN-061 | Browse indexed docs | PASS | `KnowledgeDocs.tsx:44-173`; `KnowledgeHub.tsx:71-117`: табы, Spinner, «No indexed documents yet.…», list/doc fail → тосты (:54,:76-79), inline viewer + X, «Show all N». |
| SCN-062 | Knowledge health & re-index | PASS | `KnowledgeHealthPanel.tsx:75-253`; `RunCard.tsx:79-179`: «Could not load knowledge health», «Action failed», start-тосты, Cancel/Retry/History, live-прогресс. **Находка (Medium): action-кнопки не gated по роли в UI** — viewer видит Re-index/Index DB/Sync, backend отклоняет 403 (`connections.py:698,1039`, `repos.py:155`). |
| SCN-063 | Knowledge freshness warnings | PASS | `KnowledgeHealthPanel.tsx:27-31,158-251`: «Everything is fresh», pipeline-running banner, warnings с severity-стилями + per-warning actions; инъекция в промпт (`git_agent.py:212-217`). Severity только цветом, без текстового тега — Low. |
| SCN-064 | Nightly sync history | PASS | `SyncHistoryPanel.tsx:106-205` (монтирован над Knowledge Health, `KnowledgeHealthPanel.tsx:138`): loading, «Could not load sync history», «No scheduled syncs yet.» дословно, per-run expanders + error messages, «Show all N runs». |
| SCN-065 | Insights feed & filters | PASS | `InsightFeedPanel.tsx:280-347`: фильтры all/critical/warning/info/positive со счётчиками, спиннер, «Couldn't load insights» + Retry, «No insights yet.…». Нюансы: фильтры скрыты при `total_active===0`, кастомный div-спиннер вместо `Spinner` — Low. |
| SCN-066 | Confirm/dismiss/resolve insight | PASS | `InsightFeedPanel.tsx:137-176,223-263`: тосты «Insight confirmed»/«dismissed»/«marked as resolved» дословно + per-action error тосты; Dismiss без confirm; «Investigate» не wired (`KnowledgeHub.tsx:99` без `onDrillDown`) — как заявлено. |
| SCN-067 | Metric catalog | PASS | `MetricCatalogPanel.tsx:74-192`; `KnowledgeHub.tsx:43-115`: поиск, category-фильтры, error `{error}` + Retry отделён от empty «No metrics found» дословно, Retry через `reloadNonce`. |
| SCN-068 | Saved-queries panel | PASS | `NotesPanel.tsx:82-127`; `notes-store.ts:78-82`; `app/app/page.tsx:192-202`: scope tabs All/Mine/Shared, skeletons, Batch при ≥2, «Failed to load saved queries» дословно → empty. Scope-aware copy различается только shared vs all/mine — Low. |
| SCN-069 | Run saved query | PASS | `NoteCard.tsx:93-127,210-238,370-385`: «Query executed successfully», «Query error: …», «Execution failed» — дословно; inject в чат; inline-таблица первых 20 rows; disabled без connection + title «No connection». |
| SCN-070 | Share / unshare query | PASS | `NoteCard.tsx:129-141,193-207`: toggle только owner (`note.user_id === currentUserId`), «Shared with team»/«Unshared», «Failed to update sharing» дословно. |
| SCN-071 | Edit query comment | PASS | `NoteCard.tsx:143-152,245-281`: owner — textarea+Save/Cancel, non-owner — read-only `<p>`, «Failed to save comment» дословно. |
| SCN-072 | Delete saved query | PASS | `NoteCard.tsx:81-91,208-226`: confirm «Delete this saved query?» destructive, owner-only, «Note deleted», «Failed to delete» — дословно. |
| SCN-073 | View agent learnings | PASS | `ConnectionSelector.tsx:1267-1277,1324-1332` (pill «LEARN {n}» при count>0); `LearningsPanel.tsx:240-432`: category pills, 4 сортировки, skeleton, confidence bars + counts, «Failed to load learnings» (только тост — см. сквозную находку M5). |
| SCN-074 | Confirm/contradict/edit/deactivate | PASS | `LearningsPanel.tsx:68-140,321-402`: hover-иконки при `canEdit`, confirm «Delete this learning?», per-action тосты; у toggleActive и saveEdit одинаковый текст «Failed to update» (:85,:99) — Low. |
| SCN-075 | Recompile learnings | PASS | `LearningsPanel.tsx:103-110,213-225`: «Learnings prompt recompiled», «Failed to recompile» дословно, без confirm, `canEdit`. |
| SCN-076 | Clear all learnings | PASS | `LearningsPanel.tsx:142-158,226-233`; `ConfirmModal.tsx:126-127,156-169`: critical + type-`DELETE`, `canDelete`=owner, «Cleared N learnings», «Failed to clear». |
| SCN-077 | Create custom rule | PARTIAL | `RulesManager.tsx:62-101,201-224`; `Sidebar.tsx:561,831` (`canEdit`): name+content validation, «Rule created», «Failed to create rule» дословно. **В модалке создания нет заявленной кнопки Cancel** (:226 — Cancel только в edit-режиме; закрытие через X FormModal). |
| SCN-078 | Edit custom rule | PASS | `RulesManager.tsx:60,117-123,195-233`: dirty-state Save (`disabled` пока не dirty), default-rule warning banner, «Rule updated», «Failed to update rule». |
| SCN-079 | Delete rule (default vs normal) | PASS | `RulesManager.tsx:150-163,282-290`: разные копии дословно («…won't be re-created automatically.» vs «Delete this rule?»), «Failed to delete rule». |
| SCN-080 | View rule read-only | PASS | `RulesManager.tsx:117-123,186-192,261-298`: viewer → `setViewingId` → read-only `<pre>`, edit/delete только `canEdit`, бейджи «default»/«global», «No custom rules yet», list fail → тост. |
| SCN-081 | Dashboard list & empty | PASS | `DashboardList.tsx:88-103,111,118-120`; `Sidebar.tsx:569`: спиннер, «Couldn't load dashboards» + Retry (реально :92-101, дрейф), «No dashboards yet», shared-иконка, navigate. |
| SCN-082 | Create dashboard | PASS | `DashboardBuilder.tsx:53,74-102,131-221`: title/layout/Add Card/remove/Refresh All/Save; «Title is required», «Dashboard created», save/notes-load fail тосты — дословно. |
| SCN-083 | Edit dashboard / refresh all | PASS | `DashboardBuilder.tsx:60-63,89,113-123,246`; `app/dashboard/[id]/page.tsx:234-244,273-281`: «Dashboard saved», «Note already on dashboard», «Refreshed: N succeeded, M failed» (error/info), «This query was deleted»; Edit gated `canEditDashboard`. Дрейф Coverage. |
| SCN-084 | View shared dashboard | PASS | `app/dashboard/[id]/page.tsx:140-338`: AuthGate, auto-refresh по `refresh_interval`, Refresh All с реальными счётчиками, viewers без Edit/Add (`user_role` :232), ResultTable cap 50, «This dashboard has no cards yet.», «Note not found»/«No data», «Back to app». |
| SCN-085 | Dashboard link invalid/expired | PASS | `app/dashboard/[id]/page.tsx:127-128,216-228`; `AuthGate.tsx:16-20`: unauth → /login; любой фейл → toast + «Dashboard not found» + «Back to app». Задокументированный GAP (один экран на все причины) подтверждён. |
| SCN-086 | Delete dashboard | PASS | `DashboardList.tsx:66-76,122-135`: confirm destructive, `api.dashboards.delete`, row removed, «Dashboard deleted», «Failed to delete dashboard», `stopPropagation`, `canEdit`-gated, hover-reveal. Тест `DashboardList.test.tsx` существует. |
| SCN-087 | Run batch of queries | PASS | `BatchRunner.tsx:103-170,217-327`; вход `app/app/page.tsx:292-300`: title/connection/queries+move/remove, «Run All (N)», прогресс current/total; тосты валидации, terminal, poll ≥10 → «Lost connection to batch — check results later» (длиннее цитаты — Low). |
| SCN-088 | Batch from saved notes | PASS | `BatchRunner.tsx:302-414`; `NotesPanel.tsx:54-78`: «Batch» при ≥2, «From Saved Notes» disabled при 0, NotePicker checkboxes/Cancel/«Add (N)», «No saved notes». |
| SCN-089 | View batch results | PASS | `BatchResults.tsx:49-236`; handoff `BatchRunner.tsx:172-174`: fetch+parse, success-таблицы (total_rows+duration), failed/blocked error+SQL, Export xlsx blob, Back/Close, «Couldn't load batch results» + Retry, empty-тексты (расширены относительно цитат — Low). Тест существует. |
| SCN-090 | Create schedule + alerts | PASS | `ScheduleManager.tsx:179-247,444-612`; `Sidebar.tsx:565` (owner): 5 валидационных тостов дословно, «Schedule created», «Failed to save», connection select только при >1, cron preset/custom, alert-condition rows. |
| SCN-091 | Edit/pause/run-now schedule | PASS | `ScheduleManager.tsx:150-177,261-291,358-404`: «Scheduled query failed», `alert_triggered` → info toast, «Query executed successfully», «Toggle failed», edit prefilled (cron+alerts парсятся). Минимальный дрейф refs. |
| SCN-092 | Delete schedule | PASS | `ScheduleManager.tsx:249-259`: confirm destructive, «Schedule deleted», «Failed to delete». |
| SCN-093 | Schedule run history | PASS | `ScheduleManager.tsx:293-309,407-440`: «Failed to load run history» + empties, «Loading...», «No runs yet», last-10 `slice(0,10)`, per-run outcomes. |
| SCN-094 | Feedback analytics | PASS | `FeedbackAnalyticsPanel.tsx:38-213`; `Sidebar.tsx:574-587` (owner): ConfidenceScore, MiniStats, VerdictBar с tooltips, top-errors, «Failed to load analytics» + Retry, empty-guidance дословно. |
| SCN-095 | Open settings & navigate | PASS | `SettingsPanel.tsx:42-197`; `app/app/page.tsx:279-289`: gear → панель, Change Password (скрыт для google-only), Sign Out/Delete Account/Edit Project/Manage Connections, Team & Invites только owner (:164-173), McpTokenManager, Terms/Privacy. Лёгкий дрейф Coverage. |
| SCN-096 | Change theme | PASS | `ThemeToggle.tsx:41-60`; `theme-store.ts:7,27,41-58`; `ThemeWatcher.tsx:9-17`: 3 кнопки `aria-pressed`, persist `cmd_theme`, default Light, System слушает OS, storage-ошибки глотаются. |
| SCN-097 | Reduced-motion honored | PASS | `globals.css:23-31`; `app/app/page.tsx:386` (`<MotionConfig reducedMotion="user">`; ref «:384» — комментарий, дрейф 2 строки); `ChartRenderer.tsx:142-153` (`animation: false`). In-app тумблера нет — подтверждено. Маркетинг — см. сквозной аспект 2. |
| SCN-098 | Upgrade → Stripe checkout | PASS | `PricingTable.tsx:96-112,160`; `login/page.tsx:19-29,69-73`: createCheckout → `window.location.href`, «Redirecting…», «Billing is not enabled on this deployment» (:101 дословно), «Checkout failed» (fallback при отсутствии err.message), logged-out → `/login?next=/pricing` с open-redirect guard. |
| SCN-099 | Manage billing (portal) | PASS | `BillingPanel.tsx:92-160`; `Sidebar.tsx:574-583` (owner): «Manage billing»/«Opening…», portal redirect, «Could not open billing portal» (fallback), plan/status badges, usage bars, past-due/cancel-at-period-end notices. |
| SCN-100 | HTTP 402 limit | PASS | `_client.ts:127-135`: «Plan limit reached. Upgrade at /pricing to continue.» (:133); `ToastContainer.tsx:18-31,46`: «/pricing» рендерится кликабельным `<Link>`. |
| SCN-101 | Billing disabled degradation | PASS | `BillingPanel.tsx:72-87`: 404 catch → `return null`; `PricingTable.tsx:10-47,73-102`: FALLBACK_PLANS статический каталог + тост «Billing is not enabled on this deployment»; usage работает через `/usage`. |
| SCN-102 | View usage stats | PASS | `UsageStatsPanel.tsx:61-176`; `Sidebar.tsx:580-583`; `ProjectOverview.tsx:122` (compact): StatCards, MiniBarChart, «Loading usage...», «Failed to load usage stats» + Retry. Empty = молчаливый `return null` (:95) — Low. |
| SCN-103 | Mint & copy MCP token | PASS | `McpTokenManager.tsx:49,87-104,147-286`: «New», name/expiry, «Create token», issued-модалка shown-once + copy + `<details>` config + «I've saved it»; тосты валидации/create/copy дословно; «No MCP tokens yet.» |
| SCN-104 | Revoke MCP token | PASS | `McpTokenManager.tsx:110-123,189-198`; `ConfirmModal.tsx:126-171`: «Revoke» только для live, warning + type-`Revoke` (строгое совпадение регистра), «Token revoked», «Failed to revoke token». |
| SCN-105 | Background tasks widget | PASS | `ActiveTasksWidget.tsx:106-278`; `app/app/page.tsx:263`: пилюля со счётчиком, Cancel/Retry/Dismiss, «Failed to cancel task»/«Failed to retry task» дословно, прогресс+elapsed, empty → `return null`. Cancel без confirm — как заявлено. |
| SCN-106 | Request history & trace | PASS | `LogsScreen.tsx:76,119-213`; `LogsTraceDetail.tsx:44-141`; `LogsSpanRow.tsx`: date/status filters, пагинация, span-tree с input/output/tokens, «Failed to load trace». **Подтверждено: баннер «Failed to load logs» + Retry — только на табе queries** (:147) — см. сквозной аспект 4. |
| SCN-107 | Runs & Errors tabs | PASS | `RunsTab.tsx:16-69`; `ErrorsTab.tsx:11-149`: kind select + Refresh, «Failed to load runs» + Retry vs «No runs recorded»; source/status selects, цикл open→acknowledged→resolved, cycle fail → toast, inline error + Retry vs empty. Дрейф refs ~3 строки. |
| SCN-108 | Live activity log | PASS | `LogPanel.tsx:131-264`; `app/app/page.tsx:327`: toggle + unread badge (99+ cap), StatusDot, Clear (без confirm), Close, «Waiting for events...» дословно; разрыв — только точка, без тоста — как заявлено. |
| SCN-109 | Landing → Get Started | PASS | `app/(marketing)/page.tsx:227-229,429-434,488,976-981`; `FaqAccordion.tsx`: «Get Started Free» → /login в hero и final CTA, «View on GitHub», stars скрыты при fetch-failure, FAQ. |
| SCN-110 | Pricing CTA (logged out) | PASS | `PricingTable.tsx:91-99`; `login/page.tsx:19-29,71`: free → /login, paid → `/login?next=/pricing`; `resolveRedirect` — same-origin only, отклонены `//host`, `/\`, absolute URL; тесты `LoginPage.test.tsx:128-174`. |
| SCN-111 | Support/Contact/Legal | PASS | `support/page.tsx:117-253`; `contact/page.tsx:90-163`: FAQ `<details>`, mailto-only (формы нет — подтверждено), GitHub/docs/cross-links; terms/privacy существуют. |
| SCN-112 | Logged-in → /app | PASS | `AuthRedirect.tsx:12-22`; `(marketing)/page.tsx:263`: restore → `router.replace("/app")`, `return null`, без loading UI. |

## Сквозные аспекты

### 1. Мобильный viewport — OK

- **Breakpoint 767px — единый источник:** `hooks/useMobileLayout.ts:5,11` (`MOBILE_BREAKPOINT = 768`, `matchMedia("(max-width: 767px)")`), используется в `app/app/page.tsx:76`, `ReasoningPanel.tsx:225`, `Sidebar.tsx:58,63`; CSS-дубль `globals.css:606`.
- **Drawer/bottom-sheets:** Sidebar как drawer с backdrop, `role="dialog"`, focus-trap, Escape, autofocus (`Sidebar.tsx:400-453`); мобильный хедер с гамбургером (`app/app/page.tsx:178-207`); Notes bottom-sheet (`page.tsx:345-376`); ReasoningPanel bottom-sheet (`ReasoningPanel.tsx:236-256`); ChatInput с safe-area-inset (`ChatInput.tsx:29`).
- **Touch-цели ≥44px:** явные `min-h/min-w-[44px]` на ключевых контролах (`page.tsx:183,195,364`; `Sidebar.tsx:470`; `ChatInput.tsx:53`) + **глобальная страховка** `globals.css:589-597`: `@media (pointer: coarse)` принудительно ставит 44px на все `button, [role="button"], a`. Мелкие по классам контролы (табы логов `LogsScreen.tsx:136`, ActionButton xs/sm 24/32px `ActionButton.tsx:29-31`, строки `DashboardList.tsx:112`, move/remove `BatchRunner.tsx:233-251`) на тач-устройствах покрыты глобальным правилом. Замечание: `.compact-touch` (`globals.css:599-603`) определён, но нигде не используется — мёртвый CSS (Low).

### 2. prefers-reduced-motion — OK

- Глобальный CSS-нейтрализатор `globals.css:23-31`; `<MotionConfig reducedMotion="user">` `app/app/page.tsx:386`; `useReducedMotion` в `StageRow.tsx:46` и `FaqAccordion.tsx:18`; charts: `ChartRenderer.tsx:142-153`.
- **Маркетинг (GSAP/Lenis):** `CinematicEngine.tsx:19-32` — при reduced-motion `.cmd-reveal` сразу `is-visible`, parallax выключен (и при `pointer: coarse`); `DataStory.tsx:69-72` — JS-гейт `(min-width:1024px) and (prefers-reduced-motion: no-preference) and (pointer:fine)` + зеркальный CSS-гейт со статичным `.cmd-story-fallback` (`globals.css:459-465`); `WordLight.tsx:32`, `CountUp.tsx:25` — ранний return с финальным состоянием; `SmoothScroll.tsx:20` — Lenis не инициализируется; `<noscript>`-фолбэк в `(marketing)/layout.tsx:55-57`. Полное соответствие SCN-097, включая маркетинговые страницы.

### 3. Состояния loading/empty/error в списках — PARTIAL

| Список | Loading | Empty | Error | Вердикт |
|---|---|---|---|---|
| connections | нет спиннера списка | «No connections yet» (`ConnectionSelector.tsx:1078`) | **только тост** (`ProjectSelector.tsx:418-421`) → обманчивый empty-state | PARTIAL |
| dashboards | спиннер `:88-91` | «No dashboards yet» | inline + Retry `:92-101` | OK |
| schedules | skeleton `:329-335` | «No scheduled queries yet.» | **только тост** (`ScheduleManager.tsx:112`) → обманчивый empty-state | PARTIAL |
| batch | прогресс/спиннер | «Batch is still running…» | inline + Retry (`BatchResults.tsx:164-175`) | OK |
| logs (3 таба) | есть у всех | есть у всех | баннер только queries (`LogsScreen.tsx:147`); Runs/Errors — свои inline + Retry | OK |
| insights | спиннер | «No insights yet…» | inline + Retry `:314-327` | OK |
| learnings | skeleton | «No learnings yet…» | **только тост** (`LearningsPanel.tsx:58`) → обманчивый empty-state | PARTIAL |

Слабый паттерн: в connections/schedules/learnings после неудачной загрузки показывается empty-state — пользователь не отличит «пусто» от «сломалось» и не имеет Retry.

### 4. Истечение сессии (401) и ошибки сети — ISSUE

- **401:** `_client.ts:117-119` → `handleSessionExpired()` — одноразовый флаг (`:9-10`), lazy-import auth-store → `logout()`, тост «Session expired, please log in again» (`:16`), жёсткий `window.location.href = "/login"` (`:17`). Вызывается также из `chat.ts:147`, `workspace.ts:204,306`, `sse.ts:64`.
- **`sessionExpiredHandled` не сбрасывается — подозрение подтверждено формально, опровергнуто функционально:** объявлен `:6`, ставится `:10`, сброса нет нигде в frontend. Работоспособность держится на полной перезагрузке документа после `window.location.href` (модуль переинициализируется). Конструкция хрупкая: переход на SPA-навигацию молча отключит обработку повторных 401.
- **Тост на 401-пути практически невидим:** тост кладётся в in-memory zustand (`toast-store.ts`, без персистентности) и тут же документ выгружается редиректом; на `/login` нет никакого сообщения об истечении сессии (grep `expired|session` по `app/login/page.tsx` пуст). Пользователь видит внезапную перезагрузку на логин без объяснений. Таймерный путь (SCN-011, `auth-store.ts:74,87` → SPA-logout) тост показывает корректно.
- **Два разных текста:** 401-путь — «Session expired, please log in again» (`_client.ts:16`, `chat.ts:152`); таймерный путь — «Your session has expired. Please log in again.» (`auth-store.ts:74,87`, цитируется в SCN-011).
- **Network error:** ретраи только GET/HEAD (до 2, backoff 600/1500ms) и 502/503/504 (`_client.ts:42-45,63-66,104,110-113`); затем сырая ошибка уходит вызывающему коду — глобальной обратной связи нет, часть мест молчит (`ConnectionHealth.tsx:63-65` — вечный «unknown»). Timeout → «Request timed out. Please try again.» (`:100-102`).
- **LogsScreen.tsx:147 — подтверждено:** баннер «Failed to load logs» + Retry рендерится только при `tab === "queries"`. Компенсировано собственными inline-ошибками RunsTab/ErrorsTab, но верхнеуровневый `error` на этих табах невидим.
- **SSE:** `useGlobalEvents.ts:48-59` — автореконнект с backoff (2с→30с); обрыв отражается только серой точкой StatusDot (`LogPanel.tsx:141-145,219-223`) — соответствует задокументированному SCN-108. В чате есть баннеры «Connection may be slow»/«Connection is down…Retry» (`ChatPanel.tsx:796-822`).

## Находки (по severity)

### High

- **H1. 401 → принудительный разлогин без видимого объяснения.** `_client.ts:16-17`: тост «Session expired…» уничтожается жёстким редиректом `window.location.href = "/login"` (in-memory store), а страница `/login` не содержит сообщения об истечении сессии. Самый частый путь истечения сессии (любой API-вызов → 401) даёт пользователю внезапную перезагрузку на логин без причины. Рекомендация: query-param (`/login?reason=session_expired`) + сообщение на странице логина, или персистентный тост.

### Medium

- **M1. `sessionExpiredHandled` никогда не сбрасывается.** `_client.ts:6,10` — работает только благодаря полной перезагрузке страницы; переход на SPA-редирект молча сломает повторную обработку 401 до конца жизни вкладки. Рекомендация: явный сброс при login/restore.
- **M2. Три разных текста об истечении сессии.** Тост 401-перехватчика (`_client.ts:16`, `chat.ts:152`): «Session expired, please log in again»; брошенная ошибка того же перехватчика (`_client.ts:119`): «Session expired. Please log in again.»; таймерный путь (`auth-store.ts:74,87`): «Your session has expired. Please log in again.» — только последний совпадает с текстом SCN-011. Несогласованность + пересечение с H1.
- **M3. Нет глобальной обратной связи при сетевых ошибках.** `_client.ts:97-106`: после ретраев TypeError уходит наверх; часть списков ловит, часть молчит (`ConnectionHealth.tsx:63-65` — вечный «unknown» без индикации сбоя опроса).
- **M4. SCN-062: action-кнопки Knowledge Health не gated по роли в UI.** `KnowledgeHealthPanel.tsx:204,213`, `RunCard.tsx:108-116` — viewer видит Re-index/Index DB/Sync/Cancel/Retry; backend корректно отклоняет 403 (`connections.py:698,1039`, `repos.py:155`), но пользователь получает «Action failed» вместо скрытой кнопки. Несогласованно с IDX/SYNC-бейджами (`ConnectionSelector.tsx:1163-1169`), где viewer видит статичные бейджи.
- **M5. Connections/schedules/learnings: ошибка загрузки только тостом → обманчивый empty-state.** `ProjectSelector.tsx:413-421` (тост + `setConnections([])` → «No connections yet»), `ScheduleManager.tsx:112` (→ «No scheduled queries yet.»), `LearningsPanel.tsx:58` (→ «No learnings yet…»). Нет inline-ошибки и Retry — слабее стандарта остальных списков (dashboards/insights/logs/batch).

### Low

- **L1. SCN-041 (PARTIAL): auto-growing textarea не реализован.** `ChatInput.tsx:32-48` — жёстко `rows={1}`, роста по контенту нет, `max-h-40 overflow-y-auto`.
- **L2. SCN-054 (PARTIAL): per-step elapsed не рендерится.** `ReasoningPanel.tsx:42-86` (StepRow — только label+agent); `elapsed_ms` собирается (`ChatPanel.tsx:467`), но не выводится; общий elapsed — в шапке (`:117-134`).
- **L3. SCN-077 (PARTIAL): нет кнопки Cancel в модалке создания правила.** `RulesManager.tsx:226` — Cancel только в edit-режиме; закрытие создания — через X FormModal.
- **L4. SCN-010: в SettingsPanel-варианте Delete Account нет «This action cannot be undone».** `SettingsPanel.tsx:286-288` (только «This will permanently delete…») vs `AccountMenu.tsx:202` (фраза есть).
- **L5. SCN-043: разные суффиксы partial-commit.** Stop — `*(Generation stopped by user)*` (`ChatPanel.tsx:690`), смена сессии — `*(Generation stopped — switched session)*` (`:382`).
- **L6. SCN-106/сквозной: баннер ошибки LogsScreen только на табе queries.** `LogsScreen.tsx:147` — подтверждено; Runs/Errors компенсируют своими inline+Retry (`RunsTab.tsx:61-67`, `ErrorsTab.tsx:95-101`), но при переключении таба ошибка queries теряется из вида.
- **L7. SCN-063: severity warning показан только цветом.** `KnowledgeHealthPanel.tsx:27-31,233` — нет текстовой метки info/warning/critical.
- **L8. SCN-068: scope-aware empty copy минимально дифференцирован.** `NotesPanel.tsx:116,119-121` — all/mine идентичны, отличается только shared.
- **L9. SCN-074: одинаковый текст error-тоста у разных действий.** `LearningsPanel.tsx:85,99` («Failed to update» и у toggleActive, и у saveEdit).
- **L10. SCN-102: empty-состояние — молчаливый `return null`.** `UsageStatsPanel.tsx:95` — панель исчезает без empty-текста.
- **L11. SCN-012: тост resend длиннее цитаты.** «Verification email sent — check your inbox.» (`EmailVerifyBanner.tsx:31`, `verify-email/page.tsx:54`).
- **L12. SCN-023/060/087/089: цитаты текстов — префиксы/парафразы фактических.** `InviteManager.tsx:134-135`; `ChartRenderer.tsx:80-83`; `BatchRunner.tsx:161`; `BatchResults.tsx:180`.
- **L13. Тосты SCN-098/099/103/104 — fallback-строки, а не основной текст.** `PricingTable.tsx:109`, `BillingPanel.tsx:98`, `McpTokenManager.tsx:104,121` — при наличии `err.message` показывается оно.
- **L14. Мёртвый CSS `.compact-touch`.** `globals.css:599-603` — opt-out определён, нигде не используется.
- **L15. SCN-065: severity-фильтры скрыты при пустой сводке; кастомный спиннер вместо `Spinner`.** `InsightFeedPanel.tsx:280,287,309-310`.

### Info (подтверждённые задокументированные GAP'ы и дрейф ссылок — код соответствует описанию)

- **I1. SCN-048:** rename UI и bulk clear-history отсутствуют — подтверждено (заявлено в сценарии).
- **I2. SCN-052:** `WrongDataModal.tsx` существует, но нигде не импортируется; thumbs-down шлёт canned prompt — подтверждено.
- **I3. SCN-066:** «Investigate» drill-down не wired (`KnowledgeHub.tsx:99` без `onDrillDown`) — как заявлено.
- **I4. SCN-085:** invalid/expired/forbidden схлопываются в один «Dashboard not found» (`app/dashboard/[id]/page.tsx:216-228`) — подтверждено.
- **I5. SCN-037:** у списка connections нет list-level loading spinner — подтверждено.
- **I6. SCN-108:** обрыв SSE отражается только StatusDot — подтверждено (`LogPanel.tsx`, `useGlobalEvents.ts:48-59` — автореконнект есть).
- **I7. SCN-025:** auto-fill порта не затирает кастомный порт (guard `knownDefaults.includes`, `ConnectionSelector.tsx:651-653`) — улучшение относительно буквы сценария.
- **I8. Дрейф line-ссылок Coverage** (не влияет на вердикты, требует косметической синхронизации scenarios.md): SCN-001 `page.tsx:121-122,174`→`:122-123,175`; SCN-005/006/007 refs login/page; SCN-009/010 SettingsPanel ~-20 строк; SCN-014 `29-73`→`:17-48`; SCN-016 `461-655`→`:467-658`; SCN-045 `159-199`→`:177-199`; SCN-050 `73-176`→`:73-177`; SCN-052 `271-292`→`:264-295`; SCN-062 `RunCard.tsx:82,91`→`:87,101`; SCN-081 `76-85`→`:92-101`; SCN-083/084/085 page.tsx refs; SCN-091 `264-287`→`:261-291`; SCN-095/096/097 refs; SCN-100 `ToastContainer.tsx:20-40`→`:18-31`; SCN-107 refs ±3 строки; SCN-108 `131-259`→`:131-264`.

## Расхождения scenarios.md ↔ код (сводка)

1. **Поведение реализовано иначе, чем описано (3 сценария, PARTIAL):** SCN-041 (нет auto-growing textarea), SCN-054 (нет per-step elapsed), SCN-077 (нет Cancel в create-модалке).
2. **Текстовые расхождения (цитата ≠ фактический текст, поведение совпадает):** SCN-010 (SettingsPanel), SCN-012, SCN-023, SCN-060, SCN-087, SCN-089, SCN-098/099/103/104 (fallback-природа тостов), SCN-043 (два суффикса), SCN-074 (одинаковые тексты), SCN-063 (severity только цветом), SCN-068 (минимальная дифференциация), SCN-102 (empty = null).
3. **Ролевая модель:** везде соответствует (owner/editor/viewer гейты проверены точечно: project/connection edit-delete — owner, IDX/SYNC — editor+, viewer — статичные бейджи, Team & Invites/Billing/Usage/Schedules/Analytics — owner), **кроме** Knowledge Health actions (M4).
4. **Фоновые процессы чата:** abort при смене сессии с коммитом partial, background polling с капом 15 мин и silent-retry, спиннер processing в строке сессии — всё подтверждено (SCN-043/048/049).
5. **Billing 402 → upgrade:** подтверждено полностью, включая кликабельный `/pricing` в тосте (SCN-100).
6. **Задокументированные GAP'ы:** все 6 (SCN-037, 048, 052, 066, 085, 108) подтверждены кодом — документация честна.
7. **Line-refs:** массовый мелкий дрейф (±1-25 строк) в ~18 сценариях — сценарии требуют ресинхронизации ссылок (I8), но ни одна ссылка не указывает на несуществующее поведение.

**Итог:** 109 PASS / 3 PARTIAL / 0 FAIL. Критических расхождений нет; единственная High-находка — невидимое объяснение при принудительном разлогине по 401 (H1). Документ scenarios.md в целом точно отражает код, включая собственные GAP'ы.
