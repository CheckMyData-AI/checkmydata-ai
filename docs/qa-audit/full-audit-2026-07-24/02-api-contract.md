# Фаза 3.1 — Контрактный аудит API

Дата: 2026-07-24. Метод: статический анализ (AST-парсинг `backend/app/api/routes/*.py`, сверка с `API.md`, ручная проверка негативных путей). Тесты/серверы не запускались.

## 1. Инвентаризация эндпоинтов

Всего извлечено **201 HTTP-эндпоинт** в 40 файлах роутеров + **1 WebSocket** (`chat.py:1396`, `/api/chat/ws/{project_id}/{connection_id}`) + **2 health-эндпоинта в `main.py`** (`/api/health` main.py:1208, `/api/health/modules` main.py:1225). Итого **204 точки входа**.

Префиксы взяты из `include_router` в `backend/app/main.py:419-465`.

| Роутер (файл) | Префикс | Кол-во | Auth | Rate limit |
|---|---|---|---|---|
| auth.py | /api/auth | 13 | частично (5 публичных — оправдано) | 10/13 |
| mcp_tokens.py | /api/auth | 3 | get_current_user | 2/3 |
| chat.py | /api/chat | 3 + WS | get_current_user + membership | 2/3 (ws-ticket без) |
| chat_sessions.py | /api/chat | 7 | get_current_user + owner-helper | 5/7 |
| chat_feedback.py | /api/chat | 2 | get_current_user + membership | 1/2 |
| chat_utility.py | /api/chat | 5 | get_current_user + membership | 5/5 |
| projects.py | /api/projects | 14 | get_current_user + membership | 6/14 (GET без — ок) |
| connections.py | /api/connections | 16 | get_current_user + membership | 10/16 (GET без — ок) |
| connection_learnings.py | /api/connections | 10 | get_current_user + membership | 7/10 |
| health_monitor.py | /api/connections | 3 | get_current_user + membership | 1/3 |
| repos.py | /api/repos | 11 | get_current_user + membership; webhook — HMAC | 9/11 |
| ssh_keys.py | /api/ssh-keys | 4 | get_current_user (user-scoped) | 2/4 |
| notes.py | /api/notes | 6 | get_current_user + owner/membership helpers | 4/6 |
| invites.py | /api/invites | 10 | get_current_user + membership | 7/10 |
| rules.py | /api/rules | 5 | мутации — require_admin; GET — user | 4/5 |
| dashboards.py | /api/dashboards | 5 | get_current_user + membership | 5/5 |
| logs.py | /api/logs | 9 | get_current_user + owner role | 9/9 |
| schedules.py | /api/schedules | 7 | get_current_user + membership | 4/7 |
| notifications.py | /api/notifications | 4 | get_current_user (user-scoped) | 2/4 |
| batch.py | /api/batch | 5 | get_current_user + owner check | 3/5 |
| billing.py | /api | 5 | 1 публичный (plans), webhook — подпись Stripe | 0/5 |
| data_validation.py | /api/data-validation | 7 | get_current_user + membership | 3/7 |
| data_investigations.py | /api/data-validation | 3 | get_current_user + membership | 1/3 |
| data_graph.py | /api/data-graph | 7 | get_current_user + membership | 4/7 |
| insights.py | /api/insights | 7 | get_current_user + membership | 4/7 |
| feed.py | /api/feed | 4 | get_current_user + membership | 4/4 |
| reconciliation.py | /api/reconciliation | 4 | get_current_user + membership | 4/4 |
| semantic_layer.py | /api/semantic-layer | 3 | get_current_user + membership | 2/3 |
| exploration.py | /api/explore | 1 | get_current_user + membership | 1/1 |
| temporal.py | /api/temporal | 2 | get_current_user + membership | 2/2 |
| usage.py | /api/usage | 1 | get_current_user | 1/1 |
| models.py | /api/models | 1 | get_current_user | 0/1 |
| tasks.py | /api/tasks | 1 | get_current_user | 1/1 |
| runs.py | /api/runs | 4 | get_current_user + membership | 2/4 |
| workflows.py | /api/workflows | 1 | get_current_user | 0/1 (SSE GET) |
| visualizations.py | /api/visualizations | 2 | get_current_user | 2/2 |
| demo.py | /api/demo | 1 | get_current_user | 1/1 |
| backup.py | /api/backup | 3 | **require_admin** | 1/3 |
| metrics.py | /api | 2 | **require_admin** | 0/2 |

Суммарно: **120 мутаций** (POST/PUT/PATCH/DELETE), из них **112 с `@limiter.limit`**, **8 без** (см. находку N-1). 81 GET, большинство без лимита (часть GET ограничена — dashboards 60/min, logs 30–60/min, rules 60/min, tasks 60/min, chat GET-утилиты 30/min).

Auth-покрытие: все эндпоинты, кроме перечисленных ниже, требуют `get_current_user` или `require_admin`:
- Публичные по дизайну: `auth.py:106` register, `:140` verify-email, `:157` resend-verification, `:185` forgot-password, `:206` reset-password, `:231` login, `:250` google — все с rate limit. **Оправдано.**
- `billing.py:41` GET /api/plans — публичный каталог тарифов (docstring «Public plan catalog for the pricing page»). **Оправдано.**
- `billing.py:130` POST /api/webhook — без сессии, но с верификацией подписи Stripe (`verify_webhook`, billing.py:134-141). **Оправдано.**
- `repos.py:363` POST /api/repos/{project_id}/webhook — без сессии, HMAC-подпись (repos.py:379-383), гейтинг `GIT_WEBHOOK_ENABLED`, rate limit 30/min. **Оправдано.**
- `main.py:1208,1225` /api/health* — публичные. **Оправдано.**

Membership/ownership: **все 96 эндпоинтов с `{project_id}`/`{connection_id}` в пути имеют проверку** `MembershipService.require_role`/`can_access` (проверено построчно). Вложенные ресурсы (insight→project, learning→connection, metric→project, investigation→project, doc→project, error→project) проверяются на принадлежность родителю — паттерн подтверждён в insights.py:170-172, connection_learnings.py:131-134, data_graph.py:241-243, data_investigations.py:198-204, repos.py:764-768. ID-scoped ресурсы (notes, sessions, batch, ssh_keys, mcp_tokens, notifications) проверяют владельца через хелперы (`_require_note_access` notes.py:87, `_require_session_owner` chat_sessions.py:126, `batch.user_id != user` batch.py:124, `user_id=` фильтры в ssh_keys.py:92, mcp_tokens.py:113, notifications.py:72-76). Критичных пропусков авторизации не найдено.

## 2. Сверка с API.md

### 2.1. Эндпоинты в коде, отсутствующие в API.md — 65 шт. (severity: Medium, документационный долг)

- **auth.py (5)**: `POST /api/auth/verify-email` (:140), `POST /api/auth/resend-verification` (:157), `POST /api/auth/forgot-password` (:185), `POST /api/auth/reset-password` (:206), `POST /api/auth/logout` (:343) — весь password-reset/email-verify flow и logout не задокументированы.
- **billing.py (5)**: `GET /api/plans` (:41), `GET /api/subscription` (:65), `POST /api/checkout` (:91), `POST /api/portal` (:111), `POST /api/webhook` (:130) — раздел Billing отсутствует целиком.
- **connection_learnings.py (10)**: весь ресурс `/api/connections/{id}/learnings*` (:33-:283) не задокументирован.
- **connections.py (7)**: `GET/DELETE /{id}/index-db` (:797,:819), `GET /{id}/index-db/status` (:759), `GET/DELETE /{id}/sync` (:1143,:1165), `GET /{id}/sync/status` (:1109), `POST /{id}/test-ssh` (:587).
- **health_monitor.py (3)**: `GET /api/connections/health` (:46), `GET /api/connections/{id}/health` (:23), `POST /{id}/reconnect` (:69).
- **chat (10)**: `POST /api/chat/ws-ticket` (chat.py:1375), `POST /api/chat/sessions` (chat_sessions.py:46), `POST /sessions/ensure-welcome` (:81), `PATCH /sessions/{id}` (:138), `POST /sessions/{id}/generate-title` (:154), `GET /api/chat/search` (chat_utility.py:227), `POST /explain-sql` (:337), `POST /summarize` (:432), `GET /api/chat/analytics/feedback/{project_id}` (chat_feedback.py:469).
- **logs.py (5)**: `GET/PATCH .../errors*` (:120,:156), `GET .../query-failures*` (:174,:204), `GET .../runs` (:221).
- **projects.py (5)**: `POST /api/projects/access-requests` (:193), `GET /{id}/runs` (:595), `POST /{id}/sync-now` (:548), `GET/PUT /{id}/sync-schedule` (:502,:527).
- **repos.py (5)**: `POST /api/repos/check-access` (:105), `POST /{id}/check-updates` (:645), `GET /{id}/docs/{doc_id}` (:756), `GET /{id}/status` (:593), `POST /{id}/webhook` (:363).
- **runs.py (4)**: `POST /{id}/cancel` (:60), `POST /{id}/retry` (:75), `GET /{id}` (:91), `GET /{id}/events` (:102) — раздел Runs отсутствует.
- **batch.py (2)**, **notes.py (2)**, **invites.py (2)**, **rules.py (1)**: `POST /api/batch/execute` (см. 2.2), `POST /api/batch/{id}/export` (метод, см. 2.2), `GET /api/notes/{id}` (:159), `POST /api/notes/{id}/execute` (:226), `POST /api/invites/decline/{id}` (:214), `PATCH /api/invites/{project_id}/members/{member_user_id}` (:282), `GET /api/rules/{id}` (:114).

### 2.2. Расхождения путь/метод (код vs API.md)

| Severity | API.md | Код | Комментарий |
|---|---|---|---|
| Medium | `POST /api/batch` | `POST /api/batch/execute` (batch.py:59) | Неверный путь в доке: клиент по доке получит 404/405 |
| Medium | `GET /api/batch/{id}/export` | `POST /api/batch/{id}/export` (batch.py:175) | Неверный метод в доке |

### 2.3. Описано в API.md, но отсутствует в коде

Реальных «мёртвых» описаний **нет**. Кажущиеся расхождения: `/api/health`, `/api/health/modules` существуют в `main.py:1208,1225`; `WS /api/chat/ws/...` существует (chat.py:1396); `POST /api/batch` и `GET /api/batch/{id}/export` — это расхождения 2.2, а не отдельные эндпоинты.

### 2.4. Неточности вводного текста API.md

- **Low** — API.md:4: «All endpoints except `/api/auth/*` and `/api/health` require authentication» — неверно: публичны также `GET /api/plans` (billing.py:41) и два webhook с подписью (`POST /api/webhook` billing.py:130, `POST /api/repos/{project_id}/webhook` repos.py:363).
- **Low** — API.md:362-365: «Mutating endpoints are rate-limited per IP» — 8 мутаций без лимита (см. N-1). Кроме того, slowapi по умолчанию лимитирует по IP, что для аутентифицированных эндпоинтов за общим NAT даёт ложные срабатывания, а для злоумышленника с пулом IP — слабую защиту; стоит задокументировать/перевести на per-user ключи (Info, архитектурное замечание).
- **Info** — API.md:35: перечислены лимиты только части auth-эндпоинтов; не указаны refresh 30/min, change-password 5/min, delete-account 3/min, verify-email 10/min.

## 3. Негативные пути

### N-1. Мутации без rate limit — 8 шт.

| Severity | Эндпоинт | Evidence | Обоснование |
|---|---|---|---|
| Medium | `POST /api/checkout` | billing.py:91 | Обращение к Stripe API (создание Checkout Session); без лимита можно спамить платёжные сессии/нагружать Stripe-квоту |
| Medium | `POST /api/portal` | billing.py:111 | Аналогично — создание Stripe portal sessions |
| Low | `PATCH /api/schedules/{schedule_id}` | schedules.py:167 | Единственная мутация расписаний без лимита (create/delete/run-now имеют); также у хендлера нет параметра `request: Request`, необходимого slowapi |
| Low | `POST /api/data-validation/investigate/{id}/confirm-fix` | data_investigations.py:237 | Мутация состояния расследования без лимита; start_investigation (:84) ограничен 5/min |
| Low | `POST /api/chat/ws-ticket` | chat.py:1375 | Выдача WS-тикетов без лимита; сам ask ограничен 20/min, тикеты можно фармить |
| Info | `POST /api/auth/logout` | auth.py:343 | Низкий риск (идемпотентная операция) |
| Info | `POST /api/auth/complete-onboarding` | auth.py:391 | Низкий риск (флаг в профиле) |
| Info | `POST /api/webhook` | billing.py:130 | Stripe ретраит при 5xx; лимит мог бы сломать доставку — отсутствие лимита осознанно, но стоит зафиксировать в комментарии/доке |

### N-2. Оракул существования ресурса: 404 до проверки доступа (паттерн)

**Severity: Low (паттерн, системный).** Распространённый порядок «сначала fetch, потом membership»: несуществующий ID → 404, существующий чужой → 403, что позволяет перебором ID отличать существующие ресурсы. Примеры:
- `connections.py:474-477` get_connection (и аналогично update :493, delete :532, test :556, test-ssh :594, refresh-schema :611, index-db :695, sync :1036 — весь файл)
- `connection_learnings.py:114-117` (conn fetch → 404 → require_role)
- `chat_sessions.py:126-133` `_require_session_owner` (404 vs 403 «Not your session»)
- `batch.py:121-125` («Not your batch» 403 после 404)
- `notes.py:87-101` `_require_note_access` (404 → 403 membership → 403 «Note is private» — два различимых 403)
- `schedules.py:172-175`, `ssh_keys.py:92-94`

Смягчающие факторы: ID — UUID (перебор непрактичен), для project-path-scoped эндпоинтов `require_role` даёт uniform 403 независимо от существования проекта (membership_service.py:30-46 — хорошо). Риск — раскрытие факта существования connection/session/note по угаданному/утёкшему UUID. Рекомендация: для fetch-first эндпоинтов возвращать 404 и при отказе в доступе (как уже сделано в data_investigations.py:200-204, где и чужой project_id даёт 404).

### N-3. Эндпоинты без membership/ownership там, где ресурс проектный

**Не найдено.** Все 96 project/connection-scoped эндпоинтов проверяют роль; вложенные ID сверяются с родителем (см. раздел 1). `GET /api/rules?project_id=` без project_id возвращает только глобальные правила (`project_id IS NULL`, rule_service.py:35-46) — утечки между тенантами нет, **оправдано**.

### N-4. Валидация file paths / SQL / внешних URL

| Severity | Проверка | Evidence | Статус |
|---|---|---|---|
| OK | SQL | SafetyGuard применяется: notes.py:248-250 (READ_ONLY/ALLOW_DML по флагу), schedules.py:241-244, batch_service.py:219-224, validation_loop.py:82 (путь chat-агента) | Покрыто |
| OK | Repo URL | `validate_repo_url` (knowledge/repo_url.py:47-66): только https/http/ssh/scp, запрет `file://`, `ext::`, `git://`, опционной инъекции `-`; применяется в RepoCheckRequest (repos.py:90-93), AddRepoRequest (repos.py:790-793), проектном repo_url | Покрыто |
| OK | Path traversal по ID | `validate_safe_id` (deps.py:16-23) применяется в data_graph, semantic_layer, insights, mcp_tokens, repos webhook | Частично (см. ниже) |
| Medium | SSRF через git URL | repo_url.py:47-66 не блокирует внутренние адреса: `http://169.254.169.254/...`, `http://localhost:...`, приватные подсети проходят валидацию схемы; далее backend делает git ls-remote/clone (`check_access` repos.py:105-136, index). Нет allowlist/denylist хостов | Реальный риск в shared-хостинге; в self-hosted сценарии — by design |
| Low | SSRF-зонд через `POST /api/repos/check-access` | repos.py:105-136 | Аутентифицированный пользователь может probing'ать произвольные host:port через git-протокол; смягчается limiter 10/min и отсутствием возврата контента (только refs/branches) |
| Info | DB host в connections | connections.py:428+ | Подключение к произвольному host:port — суть продукта; read-only флаг и SafetyGuard ограничивают ущерб |
| Info | Непоследовательное применение `validate_safe_id` | connections.py, projects.py, batch.py, schedules.py path-ID не валидируются regex'ом | ID используются только в параметризованных SQL-запросах, в файловые пути не попадают — риск низкий, но единообразие желательно |

### N-5. Несогласованности кодов ошибок

- **Low (паттерн)** — 404 vs 403 оракул: см. N-2.
- **Low** — `logs.py:168-170` update_error: невалidный `error_id` и невалidный `status` оба дают 400 («Invalid error id or status»), тогда как в остальных роутерах отсутствующий ресурс → 404. Несогласованность контракта.
- **Info** — `connections.py:506-511` update_connection: бизнес-валидация («Provide either a connection string or db_host + db_name») возвращает 422 вручную; Pydantic-ошибки тоже 422 — клиент не может отличить ошибку схемы от бизнес-правила; в других местах для этого используется 400 (notes.py:152, connection_learnings.py:127).
- **Info** — `billing.py:137-138`: ошибка верификации конфигурации Stripe (`BillingError`) возвращается как 500 наряду с внутренними сбоями; семантически это 502/503.
- **Info** — chat: таймаут стрима возвращается in-band SSE error (задокументировано в API.md:81) — согласовано, отмечено как хорошая практика.

## 4. Пагинация и лимиты

Прецедент (notifications/insights) соблюдён в большинстве списочных эндпоинтов: ограничены `connections list` (le=200, connections.py:462-463), `chat_sessions list` (le=200, chat_sessions.py:107-108), `insights` (le=100/:77, le=50/:239), `logs` (le=200, logs.py:55,130,182,226), `notifications` (le=200, notifications.py:34), `schedules` (le=200, schedules.py:144-145,333-334), `repos repositories` (le=500, repos.py:850), `chat search` (le=100, chat_utility.py:231), `suggestions` (le=20, :309), `sync-history` (clamp 1–50, projects.py:491).

Оставшиеся места без верхних границ:

| Severity | Эндпоинт | Evidence | Обоснование |
|---|---|---|---|
| Low | `GET /api/chat/sessions/{id}/messages` | chat_sessions.py:262 | `limit` допускает до **2000** (default 500) сообщений с полным контентом в одном ответе — тяжёлый ответ/память |
| Low | `GET /api/notes?project_id=` | notes.py:146-156 (`list_by_project`) | Нет limit/offset; кардинальность ограничена проектом, но не ограничена кодом |
| Low | `GET /api/dashboards?project_id=` | dashboards.py:81-89 | Нет limit/offset |
| Low | `GET /api/data-graph/{id}/relationships` | data_graph.py:162-175 | Нет limit; граф связей может расти квадратично от числа метрик |
| Low | `GET /api/data-graph/{id}/metrics` + `GET /api/semantic-layer/{id}/catalog` | data_graph.py:98, semantic_layer.py:68-90 | Нет limit; catalog возвращает полный список метрик с `total` |
| Low | `GET /api/repos/{id}/docs` | repos.py:735-753 | Все документы проекта без пагинации; крупные репозитории → тяжёлый ответ |
| Low | `GET /api/connections/{id}/learnings` | connection_learnings.py:33-60 | Все learnings без limit |
| Info | `GET /api/batch?project_id=` | batch.py:131-139 | Без limit; user+project scoped |
| Info | `GET /api/logs/{id}/users` | logs.py:33-45 | Без limit; owner-only, кардинальность = число членов проекта |
| Info | `GET /api/invites/{id}/members`, `.../invites`, `/pending` | invites.py:102,231,253 | Без limit; низкая кардинальность |
| Info | `GET /api/rules`, `GET /api/projects` | rules.py:102, projects.py:214 | Без limit; глобальные правила/свои проекты, низкая кардинальность |
| Info (perf) | `GET /api/repos/{id}/docs/{doc_id}` | repos.py:764-767 | Загружает **все** docs проекта (`get_docs_for_project`) и фильтрует в Python ради одного — N+1 на уровне таблицы |

## 5. Сводка находок по severity

- **Critical**: 0
- **High**: 0
- **Medium**: 5 — недокументированные эндпоинты (65, в т.ч. Billing и Learnings целиком); batch path mismatch; batch method mismatch; checkout/portal без rate limit (2, считаются одной находкой-классом); SSRF через git URL без фильтра внутренних хостов
- **Low**: 10 — update_schedule/confirm-fix/ws-ticket без лимита; 404/403-оракул (паттерн); неточности API.md (2); logs 400-vs-404; connections 422-vs-400; session messages le=2000; 7 списочных эндпоинтов без limit; check-access как SSRF-зонд
- **Info**: 12 — logout/onboarding/webhook без лимита (оправдано/низкий риск); validate_safe_id не везде; billing 500; прочие мелкие несогласованности и perf-замечания

## 6. Рекомендации (приоритет)

1. Дописать API.md: разделы Billing, Connection Learnings, Runs, Health Monitor + 45 точечных эндпоинтов; исправить batch path/метод (раздел 2).
2. Добавить `@limiter.limit` на `POST /api/checkout`, `POST /api/portal` (billing.py:91,111) и — для консистентности — на `PATCH /api/schedules/{id}` (schedules.py:167, не забыть параметр `request: Request`), `confirm-fix` (data_investigations.py:237), `ws-ticket` (chat.py:1375).
3. Добавить denylist внутренних/loopback хостов в `validate_repo_url` (repo_url.py:47) либо на уровне git-клиента.
4. Унифицировать отказ в доступе к 404 для fetch-first эндпоинтов (N-2), как уже сделано в data_investigations.
5. Снизить верхнюю границу `limit` у session messages (2000 → 500) и добавить пагинацию в docs/relationships/learnings/notes/dashboards-списки.
