# 04 — Живое E2E-тестирование API (Фаза 3.2)

Дата: 2026-07-24
Исполнитель: автоматизированный агент (live-прогон через HTTP)
Окружение: macOS, FastAPI backend на `uvicorn app.main:app --port 8000`, изолированная БД `backend/data/e2e_audit.db` (SQLite, `alembic upgrade head` с нуля), целевая БД PostgreSQL@16 `cmdb_e2e` (20 users / 23 orders). Рабочая dev-БД `agent.db` не затрагивалась.

## Краткая сводка

| # | Поток | Статус | Комментарий |
|---|-------|--------|-------------|
| 1 | Health endpoints | PASS | `/api/health` публичен; `/api/health/modules` требует auth (by design, разрыв с ожиданием/API.md) |
| 2 | Регистрация/логин/негатив | PASS | все 6 кейсов ожидаемо |
| 3 | Проекты | PASS | обнаружен гейт `can_create_projects` (by design, требуется ручной грант) |
| 4 | Подключение БД + невалидные креды | PASS | ошибки graceful (не 500); кейс «неверный пароль» недостижим из-за PG trust-auth |
| 5 | Индексация схемы | PARTIAL | пайплайн отработал, 2 таблицы проиндексированы; LLM-обогащение упало (мёртвый ключ), graceful degrade |
| 6 | Chat/ask (сквозной) | PARTIAL | HTTP 200 + `response_type=error`, graceful; SQL-путь агента не проверен — мёртвый OpenRouter-ключ |
| 7 | Notes | PASS | создание + список |
| 8 | Batch execute | PASS | completed, результаты корректны; путь в API.md неверен |
| 9 | Visualizations render/export | PASS | render + CSV + XLSX |
| 10 | Chat feedback | PASS | 200, рейтинг записан |
| 11 | Tenant isolation | PASS | все обращения чужим токеном → 403 без утечек |
| 12 | Rate limiting | PASS | 429 ровно на пороге лимита |
| 13 | SSE stream | PASS | полная последовательность событий, корректное завершение |

**Блокирующий фактор окружения:** `OPENROUTER_API_KEY` в `backend/.env` невалиден (проверено напрямую против `https://openrouter.ai/api/v1/auth/key` → 401 «User not found»), `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` пусты. Все LLM-вызовы падают с 401. Токены LLM не расходовались (все вызовы отклонены провайдером на этапе auth). Из-за этого потоки 5–6 и LLM-часть потока 13 проверены только по пути graceful-degradation, а не по «золотому» пути с реальным ответом агента.

---

## Детальные результаты по потокам

### Поток 1 — Health — PASS

| Действие | Код | Ключевые поля | Время |
|----------|-----|---------------|-------|
| `GET /api/health` без auth | 200 | `{"status":"ok"}` | 0.002 s |
| `GET /api/health/modules` без auth | **401** | `{"detail":"Authentication required"}` | 0.002 s |
| `GET /api/health/modules` с Bearer | 200 | все модули `ok`: database, vector_store, ssh_tunnels(0), connectors(0), llm | 0.013 s |

Код (`main.py:1225-1229`) намеренно требует auth для modules (docstring «auth required»). API.md декларирует публичность только для `/api/auth/*` и `/api/health` — формально противоречия нет, но ожидание «оба health публичны» не подтвердилось. Зафиксировано как документационное несоответствие (см. баг D2).

### Поток 2 — Auth — PASS

| Действие | Код | Ключевые поля | Время |
|----------|-----|---------------|-------|
| `POST /api/auth/register` (user A) | 200 | `token:""` (cookie-режим, F-AUTH-04), `email_verified:false`, `can_create_projects:false`, `expires_in:86400`; Set-Cookie: `cmd_session` (HttpOnly JWT) + `cmd_csrf` | 0.189 s |
| `POST /api/auth/login` (верный пароль) | 200 | та же форма ответа | 0.177 s |
| `POST /api/auth/register` (тот же email) | 409 | `An account with this email already exists.` | 0.003 s |
| `POST /api/auth/login` (неверный пароль) | 401 | `Invalid credentials` | 0.171 s |
| `GET /api/projects` без токена | 401 | `Authentication required` | 0.002 s |
| `GET /api/auth/me` с Bearer (JWT из cookie) | 200 | профиль совпадает | 0.003 s |

Форма токена: при `auth_cookie_enabled=true` (дефолт) тело ответа содержит пустой `token`, JWT живёт в HttpOnly-cookie `cmd_session`; значение cookie — валидный JWT, принимается и как `Authorization: Bearer` (документированный путь API-клиентов, `deps.py:45-51`). Все дальнейшие вызовы делались Bearer-способом. `email_verified:false` — письмо верификации «отправляется» (в dev без SMTP — no-op), статус честно отражён.

### Поток 3 — Проекты — PASS

| Действие | Код | Ключевые поля | Время |
|----------|-----|---------------|-------|
| `POST /api/projects` без гранта | 403 | `You are not eligible to create projects. Please request access.` | 0.004 s |
| (админский грант `can_create_projects=1` напрямую в изолированной БД) | — | — | — |
| `POST /api/projects` | 200 | `id:cf4024a1…`, `user_role:"owner"` | 0.011 s |
| `GET /api/projects` | 200 | проект в списке | 0.003 s |

Важная находка окружения/by-design: свежерегистрированный пользователь **не может создать проект** — флаг `can_create_projects` по умолчанию `false`, и ничто в коде приложения его не выставляет (миграция `c6d7e8f9g0h1` проставила `true` только существовавшим на момент миграции пользователям; дальше — ручная выдача админом после `/api/projects/access-requests`). Для E2E флаг выставлен SQL-апдейтом в изолированной БД (эквивалент действия админа). См. наблюдение N1.

### Поток 4 — Подключение БД — PASS

| Действие | Код | Ключевые поля | Время |
|----------|-----|---------------|-------|
| `POST /api/connections` (валидное) | 200 | `id:03fc55d0…`, `is_read_only:true` | 0.008 s |
| `POST /api/connections/{id}/test` (валидное) | 200 | `{"success":true}` | 0.024 s |
| `POST /api/connections/{id}/test` (несуществующая БД `no_such_db_e2e`) | 200 | `{"success":false,"error":"database \"no_such_db_e2e\" does not exist"}` | 0.014 s |
| `POST /api/connections/{id}/test` (мёртвый порт 55999) | 200 | `{"success":false,"error":"[Errno 61] Connection refused"}` | **3.013 s** |

- Ошибки подключения возвращаются как `success:false` с человекочитаемым текстом — ни одного 500.
- Кейс «невалидный пароль» в этом окружении недостижим: локальный PostgreSQL (homebrew) сконфигурирован `trust` в `pg_hba.conf` для всех local/127.0.0.1 — любой пароль принимается (проверено `psql` напрямую). Вместо него проверены эквивалентные отказы: несуществующая БД и закрытый порт.
- Замечание по таймингу: отказ по мёртвому порту занимает ~3 с (connect timeout/ретрай коннектора) — приемлемо, но заметно в UX.
- Создание подключения не валидирует коннективность (dead port принят с 200) — осознанный дизайн (test — отдельный шаг), см. наблюдение N2.
- `auto_index_db_on_test=false` (дефолт, `config.py:202`) — автоиндексация после test не стартует, что и наблюдалось.

### Поток 5 — Индексация схемы — PARTIAL

| Действие | Код | Ключевые поля | Время |
|----------|-----|---------------|-------|
| `POST /api/connections/{id}/index-db` | 202 | `status:"started"`, `run_id`, `workflow_id` | 0.092 s |
| `GET …/index-db/status` (поллинг) | 200 | `indexing_status:"completed"`, `is_indexed:true`, `total_tables:2` | 0.004 s |
| `GET …/index-db` | 200 | таблицы `orders`(5 кол.), `users`(4 кол.), `query_hints` с PK/FK | 0.004 s |

Факт: индексация завершилась за ~6 с (14:52:44 → 14:52:50). Обе таблицы проиндексированы, FK-связь `orders.user_id → users` извлечена. **НО:** LLM-обогащение упало — `business_description:"Table with N columns"` (placeholder), `relevance_score:3`, `row_count:null`, `orphan_tables:2`. Лог: `Provider openrouter … 401 Unauthorized` → `LLMAllProvidersFailedError`, пайплайн при этом корректно завершился (`pipeline_end: completed (2 tables indexed (2 active))`), BM25-индекс построен. Деградация graceful — функциональный индекс есть, семантического обогащения нет. Причина — окружение (мёртвый ключ), не код.

### Поток 6 — Chat/ask (сквозной) — PARTIAL

| Действие | Код | Ключевые поля | Время |
|----------|-----|---------------|-------|
| `POST /api/chat/ask` «How many users are in the users table?» | 200 | `response_type:"error"`, `error:"LLMAllProvidersFailedError"`, `answer:"AI service is temporarily unavailable. Please try again shortly."`, созданы `session_id`, `user_message_id`, `assistant_message_id` | 0.489 s |
| `GET /api/chat/sessions/{id}/messages` | 200 | оба сообщения сохранены, metadata с `response_type:"error"` | 0.006 s |

Факт: сквозной оркестратор дошёл до LLM-вызова и graceful-вернул ошибку: HTTP 200 (не 500), user-friendly текст, `response_type:"error"`, сессия и сообщения персистированы — контракт API.md для типа `error` соблюдён. Fail-fast: 0.49 s, без ретрай-шторма (401 — non-retryable, `router.py`). **Золотой путь (оркестратор → SQLAgent → execution → ответ с числом ~20) не проверен** — единственный настроенный LLM-провайдер недоступен. Для полной валидации нужен валидный ключ любого провайдера (openrouter/openai/anthropic) и повтор потоков 5, 6, 13.

### Поток 7 — Notes — PASS

| Действие | Код | Ключевые поля | Время |
|----------|-----|---------------|-------|
| `POST /api/notes` (title + sql + answer_text) | 200 | `id:17db8025…`, все поля сохранены | 0.008 s |
| `GET /api/notes?project_id=` | 200 | заметка в списке | 0.003 s |

### Поток 8 — Batch — PASS

| Действие | Код | Ключевые поля | Время |
|----------|-----|---------------|-------|
| `POST /api/batch/execute` (2 SELECT) | 202 | `batch_id`, `status:"pending"` | 0.008 s |
| `GET /api/batch/{id}` через ~3 с | 200 | `status:"completed"`, оба запроса `success` | 0.003 s |
| `POST /api/batch` (путь из API.md) | **405** | `Method Not Allowed` | — |

Результаты: `users_count=20` ✓; `orders by status`: completed 15 / 2974.63, pending 6 / 642.87, cancelled 2 / 110.74 ✓ (сходится с сидом). Батч исполнился < 1 с (created 14:56:27.0 → completed 14:56:27.59). Подтверждено живьём: документированный путь `POST /api/batch` не существует (405), реальный — `POST /api/batch/execute` (`batch.py:57`). См. баг D1.

### Поток 9 — Visualizations — PASS

| Действие | Код | Ключевые поля | Время |
|----------|-----|---------------|-------|
| `POST /api/visualizations/render` (`viz_type:"bar"`) | 200 | `type:"table"` — **тихий fallback**: валидные типы — `bar_chart/line_chart/pie_chart/scatter/table/text/number` | 0.004 s |
| `POST /api/visualizations/render` (`viz_type:"bar_chart"`) | 200 | `type:"chart"`, Chart.js-spec: labels + dataset | 0.003 s |
| `POST /api/visualizations/export` (csv) | 200 | `text/csv`, корректный CSV | 0.003 s |
| `POST /api/visualizations/export` (xlsx) | 200 | `content-disposition: attachment; filename=export.xlsx`, 4947 байт | 0.005 s |

Тихий fallback невалидного `viz_type` на `table` без предупреждения в ответе (`renderer.py:43`) — наблюдение N3.

### Поток 10 — Chat feedback — PASS

| Действие | Код | Ключевые поля | Время |
|----------|-----|---------------|-------|
| `POST /api/chat/feedback` `{message_id, rating:1}` | 200 | `{"ok":true,"message_id":…,"rating":1}` | 0.007 s |

Использован `assistant_message_id` из потока 6 (сообщение существует несмотря на error-ответ — feedback-петля работает и для failed-ответов).

### Поток 11 — Tenant isolation — PASS

Зарегистрирован user B (`e2e-audit-b@example.com`). Его токеном:

| Действие | Код | detail | Время |
|----------|-----|--------|-------|
| `GET /api/projects/{A}` | 403 | `Not a member of this project` | 0.002 s |
| `GET /api/connections/{A}` | 403 | `Not a member of this project` | 0.002 s |
| `GET /api/connections/project/{A}` | 403 | `Not a member of this project` | 0.002 s |
| `POST /api/chat/ask` в проект A | 403 | `Not a member of this project` | 0.003 s |
| `GET /api/notes?project_id={A}` | 403 | `Not a member of this project` | 0.002 s |
| `GET /api/projects` (свои) | 200 | `[]` — чужое не протекает в листинг | 0.002 s |

Ни одного 200/утечки. Код отвечает 403 (а не 404) — соответствует ожиданию задания; существование ресурса при этом формально различимо (403 vs 404 на несуществующий id) — принятая в проекте семантика (`require_role`).

### Поток 12 — Rate limiting — PASS

Прогон по `POST /api/auth/register` (лимит 5/мин per IP, slowapi, скользящее окно):

```
req#1..4: 409 (2.5–3.7 ms)   — внутри лимита
req#5..6: 429 (1.8–1.9 ms)   — сверх лимита
```

Факт: 429 появляется ровно на 6-м запросе в окне (5 разрешено); неуспешные ответы (409) тоже расходуют лимит — стандартное поведение slowapi. Всего в прогоне 6 быстрых запросов — в пределах бюджета ≤15, дудоса не было.

### Поток 13 — SSE stream — PASS (протокол), LLM-путь PARTIAL

`POST /api/chat/ask/stream` «What tables exist?» → HTTP 200, `text/event-stream`, завершение за 0.466 s. Последовательность событий:

1. `step: pipeline_start (started)`
2. `thinking: Routing request…` → `Route: explore (moderate)`
3. `plan_summary` — **без LLM**: из DB-индекса подтянуты таблицы `["orders","users"]`, стратегия `single_query`, применены дефолтные правила проекта (GMV, Net Revenue, AOV, … — сидинг default-правил работает)
4. `thinking: Analyzing request (step 1/20)`
5. `agent_start: orchestrator:llm_call` → `agent_end: failed` (`401 Unauthorized`, 64.4 ms)
6. `step: pipeline_end (failed, LLMAllProvidersFailedError)`
7. `result` — финальный payload, идентичный по схеме ответу `/ask` (`response_type:"error"`, user-friendly answer, `session_id`, message ids)

Стрим открывается, события workflow/step/agent/result приходят в документированном формате, стрим корректно завершается после `result` (закрытие соединения, без висячих чанков). Ошибка LLM доставлена in-band — соответствует описанию в API.md.

---

## Найденные баги

### B1 — Medium: периодический decay заметок сессий падает на SQLite (`greatest`)

- **Где:** `backend/app/services/session_notes_service.py:439` — `.values(confidence=func.greatest(0.1, SessionNote.confidence - decay_amount))`
- **Симптом:** каждый интервал фонового цикла в логе: `WARNING app.main: Periodic note decay failed` → `sqlite3.OperationalError: no such function: greatest`.
- **Воспроизведение:** запустить backend с `DATABASE_URL=sqlite+aiosqlite:///...` и дождаться тика decay-цикла (в прогоне сработал через ~30 с после старта, 14:46:13).
- **Влияние:** на SQLite-деплое (dev/дефолт) decay confidence заметок молча не работает вообще + шум в логах каждый цикл. На PostgreSQL (prod) функция есть — не воспроизводится. Запросы API не затрагиваются (исключение поймано в цикле).
- **Рекомендация:** заменить на диалект-независимое выражение (`sa.case` / `func.max` через `CASE WHEN`), либо ветвить по `session.bind.dialect.name`.

### B2 — Low: `/api/health/modules` сообщает `llm: ok` при мёртвом ключе провайдера

- **Где:** `backend/app/main.py:1225+` (модуль llm в module_health).
- **Симптом:** `{"llm":{"status":"ok","provider":"openrouter","configured_providers":1}}` в то же время, когда 100% LLM-вызовов падают 401 (ключ отозван).
- **Влияние:** health-мониторинг не заметит отказа LLM — главной зависимости продукта. Проверка конфигурационная (ключ задан), а не живостная.
- **Рекомендация:** помечать `degraded`, если последние N вызовов завершились auth-ошибкой (роутер уже логирует), или делать дешёвый probe.

### D1 — Low (документация): API.md указывает неверный путь batch

- API.md: `POST /api/batch` → фактически 405; реальный роут `POST /api/batch/execute` (`backend/app/api/routes/batch.py:57`). Подтверждено живым запросом.

### D2 — Low (документация): публичность health-эндпоинтов

- Ожидание (и типичное соглашение): оба health публичны. Факт: `/api/health/modules` требует auth (намеренно, docstring «auth required», `main.py:1227`). В API.md это различие не отражено — стоит явно пометить modules как auth-required.

### N1 — Наблюдение (by design): новый пользователь не может создать проект без ручного гранта

- `can_create_projects=false` по умолчанию (`models/user.py:26`), гейт в `projects.py:137` → 403. В коде приложения пути автовыдачи нет — только ручной апдейт БД админом после access-request. Для self-hosted/first-run сценария первый пользователь упирается в 403 — стоит задокументировать процедуру бутстрапа (или завести env-флаг auto-grant).

### N2 — Наблюдение (by design): create connection не валидирует коннективность

- Подключение с мёртвым портом создаётся с 200; отказ всплывает только на `/test` (~3 с из-за connect-timeout). Осознанное разделение, но фронту стоит всегда вызывать test после create.

### N3 — Наблюдение: тихий fallback невалидного `viz_type`

- `viz_type:"bar"` → ответ `type:"table"` без предупреждения (`renderer.py:43`). Контракт терпим, но клиент не узнает, что запрошенный тип отклонён.

### E1 — Окружение (не код): невалидный `OPENROUTER_API_KEY` в backend/.env

- Ключ присутствует (формат `sk-or-…`, 73 символа), но `GET https://openrouter.ai/api/v1/auth/key` → 401 «User not found». `OPENAI_API_KEY`/`ANTHROPIC_API_KEY` пусты, `DEFAULT_LLM_PROVIDER=openrouter`. Любой LLM-функционал (chat, enrichment, summary) сейчас неработоспособен. Требуется замена ключа и повторный прогон потоков 5, 6, 13 по золотому пути.

---

## Тайминги API (wall-clock, curl `time_total`)

| Запрос | Код | Время |
|--------|-----|-------|
| GET /api/health | 200 | 0.002 s |
| GET /api/health/modules (без auth) | 401 | 0.002 s |
| GET /api/health/modules (Bearer) | 200 | 0.013 s |
| POST /api/auth/register | 200 | 0.185–0.189 s |
| POST /api/auth/login (верный) | 200 | 0.177 s |
| POST /api/auth/register (дубликат) | 409 | 0.003 s |
| POST /api/auth/login (неверный пароль) | 401 | 0.171 s |
| GET /api/projects (без токена) | 401 | 0.002 s |
| GET /api/auth/me | 200 | 0.003 s |
| POST /api/projects (без гранта) | 403 | 0.004 s |
| POST /api/projects | 200 | 0.011 s |
| GET /api/projects | 200 | 0.003 s |
| POST /api/connections | 200 | 0.005–0.008 s |
| POST /api/connections/{id}/test (ok) | 200 | 0.024 s |
| POST /api/connections/{id}/test (нет БД) | 200 | 0.014 s |
| POST /api/connections/{id}/test (мёртвый порт) | 200 | 3.013 s |
| POST /api/connections/{id}/index-db | 202 | 0.092 s |
| Индексация end-to-end (2 таблицы, без LLM) | — | ~6 s |
| GET …/index-db/status | 200 | 0.004 s |
| GET …/index-db | 200 | 0.004 s |
| POST /api/chat/ask (LLM-fail путь) | 200 | 0.489 s |
| GET /api/chat/sessions/{id}/messages | 200 | 0.006 s |
| POST /api/notes | 200 | 0.008 s |
| GET /api/notes?project_id= | 200 | 0.003 s |
| POST /api/batch/execute | 202 | 0.008 s |
| Batch исполнение (2 SELECT) end-to-end | — | ~0.6 s |
| GET /api/batch/{id} | 200 | 0.003 s |
| POST /api/visualizations/render | 200 | 0.003–0.004 s |
| POST /api/visualizations/export (csv) | 200 | 0.003 s |
| POST /api/visualizations/export (xlsx) | 200 | 0.005 s |
| POST /api/chat/feedback | 200 | 0.007 s |
| Tenant-isolation пробы (6 шт.) | 403/200 | 0.002–0.003 s каждая |
| Rate-limit пробы (4×409 + 2×429) | 409/429 | 0.002–0.004 s |
| POST /api/chat/ask/stream (полный стрим, LLM-fail путь) | 200 | 0.466 s |

Заметки: доминирующая стоимость auth-эндпоинтов (~0.18 s) — bcrypt (осознанно). Все CRUD-операции ≤ 0.013 s. Двухсекундных+ операций две: отказ коннекта по мёртвому порту (3 s, таймаут коннектора) и индексация (~6 s, из них 5.4 s — `store_results`).

---

## Процедура и чистота прогона

- Сервер: `DATABASE_URL=sqlite+aiosqlite:///./data/e2e_audit.db .venv/bin/uvicorn app.main:app --port 8000` (миграции `alembic upgrade head` с нуля). `.env` подхвачен самим приложением (pydantic-settings); ручной `source .env` ломает `CORS_ORIGINS` (bash съедает кавычки JSON-массива) — зафиксировано как практическая пометка для runbook'ов.
- LLM-бюджет: соблюдён — 2 входа в LLM-путь (`/ask`, `/ask/stream`), 0 потраченных токенов (401 на auth провайдера). Запрос B в чужой проект отклонён 403 до LLM.
- Запросов в rate-limit прогоне: 6 (≤15).
- Посторонних 5xx за весь прогон: нет (проверено по access-логу).
- По завершении: uvicorn остановлен (pid 79392 + дочерний 79393), `backend/data/e2e_audit.db*` удалён, `/tmp/e2e-audit/` и `/tmp/e2e-uvicorn.log` удалены. `cmdb_e2e` в PostgreSQL оставлена (тестовая БД, может быть удалена: `dropdb -U sshlg cmdb_e2e`).
