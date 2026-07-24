# 11 — Единый реестр находок полного аудита 2026-07-24

**Дата компиляции:** 2026-07-24 · **Версия проекта:** 1.15.1 (main, `e695caa`)
**Источники:** отчёты `00-baseline.md` … `09-performance.md` в этой папке. Существующие открытые находки — `docs/qa-audit/issues.md` (аудит июня: ~33 Medium + ~49 Low + 3 High, релизы R1–R14).

## Правила компиляции

- Каждая находка — одна строка с ID `FA-NNN`. Повторы между отчётами объединены: ведётся первичный источник, остальные указаны в колонке «Источник».
- **Дедупликация выполнена:** git-SSRF (02 N-4 = 07 S-01, эскалирован до High); неверный путь batch в API.md (01 F-03 + 02 §2.2 + 04 D1 — одна находка, подтверждена живьём); API.md-дрейф (01 F-03 + 02 §2.1); rate-limit multi-dyno (07 S-07 + 08 RES-7 + 09 §4.3); `sessionExpiredHandled` (03 H1/M1/M2 — три находки одного кластера, оставлены раздельно с перекрёстными ссылками).
- **Статус:** NEW — находка впервые зафиксирована этим аудитом; DUP — явный дубль уже открытого пункта `issues.md` (связь указана); NEW (пересечение с …) — новая находка в уже известном семействе.
- Отчёт 01 не присваивает severity — грейды для F-01..F-10 выставлены при компиляции реестра. Отчёт 09 использует градацию «Low-Medium» — отображена в Low с пометкой в тексте. Отчёт 02 заявляет 5 Medium, включая git-SSRF; после слияния с 07 S-01 находка учтена как High (первичный источник 07).

## Сводный tally (severity × источник)

| Severity | 00 | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | Итого |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 🔴 Critical | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 0 | **1** |
| 🟠 High | 0 | 0 | 0 | 1 | 0 | 1 | 2 | 3 | 3 | 2 | **12** |
| 🟡 Medium | 0 | 2 | 4 | 5 | 1 | 1 | 6 | 5 | 4 | 7 | **35** |
| 🟢 Low | 0 | 5 | 10 | 15 | 2 | 3 | 8 | 5 | 4 | 9 | **61** |
| ⚪ Info | 0 | 2 | 12 | 8 | 4 | 1 | 0 | 4 | 1 | 3 | **35** |
| **Итого** | 0 | 9 | 26 | 29 | 7 | 7 | 16 | 17 | 12 | 21 | **144** |

Объединённые находки учтены один раз по первичному источнику: FA-004 (07+02), FA-014/FA-015/FA-016 (02+01+04), FA-036 (07+08+09), FA-111 (01+00), FA-141 (08+04), FA-144 (09+04).

---

## Реестр

### Critical

| ID | Severity | Домен | Находка | Evidence | Источник | Статус |
|---|---|---|---|---|---|---|
| FA-001 | 🔴 | Connectors / MongoDB | **MongoDB-коннектор неработоспособен с реальным motor**: `if not self._db` бросает `NotImplementedError` (motor не реализует truth-value). Падают ВСЕ операции: execute/introspect/sample/W4-статистика; в `execute_query` проверка стоит до `try` → 500 на API. Юнит-тесты маскируют баг фейком `_FakeDB`. Фикс: `if self._db is None:` ×5. | `connectors/mongodb.py:212,319,387,413,436`; `tests/unit/test_mongodb_connector.py` | 05 (B1) | NEW |

### High

| ID | Severity | Домен | Находка | Evidence | Источник | Статус |
|---|---|---|---|---|---|---|
| FA-002 | 🟠 | Learnings / Feedback | **AQ-1: downvote-цикл неидемпотентен.** Каждый повторный rating=-1 по тому же сообщению: −0.3 к top-3 exposed learnings (до деактивации) + накачка мусорного урока «User flagged incorrect results…» (+0.1 dedup, → ★CRITICAL после 5 повторов). Доступ — роль viewer; endpoint `submit_feedback` покрыт тестами на 0%. | `chat_feedback.py:64-101,418-465`; `agent_learning_service.py:365-374,588-602`; `learning_analyzer.py:284-295` | 06 (AQ-1) | **DUP → issues.md F-LEARN-08** (открыт, релиз R6; подтверждён с новыми деталями: cap=3, сортировка по влиятельности, 0% coverage) |
| FA-003 | 🟠 | Prompt-injection / Learnings | **AQ-2: indirect prompt injection → персистентное отравление памяти агента.** Строки БД вставляются в tool message verbatim (без «untrusted»-framing и анти-инъекционных инструкций), `record_learning` пишет с conf=0.8 (> порога 0.5 попадания в промпт), compiled prompt оформляет learnings авторитетно (★CRITICAL). Crafted-значение в БД → poisoned learning рулит всеми будущими запросами соединения, переживает сессию. | `result_handler.py:28-29`; `sql_agent.py:812-885`; `prompts/sql_prompt.py`; `agent_learning_service.py:893-934` | 06 (AQ-2) | NEW (пересечение с issues.md F-SQL-01 + F-LEARN-01 — известное семейство, впервые собрана полная персистентная цепочка с file:line) |
| FA-004 | 🟠 | SSRF / Git | **git-SSRF подтверждён двумя фазами.** `validate_repo_url` фильтрует транспорт (https/ssh/scp, блок `file://`/`ext::`/option-injection), но не блокирует loopback/private/link-local/metadata (`169.254.169.254`, `localhost`, RFC1918) → серверный `git ls-remote`/`clone` к внутренним адресам (сканирование, cloud metadata). | `knowledge/repo_url.py:47-66`; `repos.py:105-136` | 07 (S-01) + 02 (N-4) | NEW (07: «подтверждает находку более раннего аудита»; пересечение с issues.md F-CONN-04 — семейство SSRF, релиз R5) |
| FA-005 | 🟠 | Frontend deps | **Next.js 15.5.12 — HTTP request smuggling in rewrites (GHSA-ggv3-7p47-pfv8)**, prod-зависимость, диапазон 9.3.4-canary.0–16.3.0-preview.7. Фикс: `npm audit fix` / обновление согласно advisory. | `frontend/node_modules/next/package.json`; `npm audit --omit=dev` | 07 (S-02) | NEW |
| FA-006 | 🟠 | Config / Secrets | **On-disk `.env.local`: `JWT_SECRET=change-me-in-production` + `DEBUG=true`, `ENVIRONMENT` не задан.** Production-валидатор при этом не сработает (см. FA-033): уезжает в реальное развёртывание = дефолтный JWT-секрет + debug. Файл не трекается git (`.gitignore:23`). | `.env.local`; `config.py:100` | 07 (S-03) | NEW |
| FA-007 | 🟠 | Resilience / Reaper | **RES-1: ложный reap живого IndexingRun необратим.** Reaper флипает run → failed по stale heartbeat; `_on_event` отбрасывает все события терминального run, включая финальный `pipeline_end` → вечный фантомный `failed` при реально успешной индексации; `/repos/{id}/status` и Runs UI противоречат друг другу. | `run_coordinator.py:371`; `stale_run_reaper.py:64-73` | 08 (RES-1) | NEW (пересечение с issues.md F-SCHED-03 — другой race того же контура, R8) |
| FA-008 | 🟠 | Resilience / Heartbeat | **RES-2: шаги >300с без heartbeat на IndexingRun** — `code_symbol_embed`, `bm25_build`, `ast_parse`, `clone_or_pull`, `analyze_files`, `graph_*`: тики только на границах шагов/emit'ах → прямой триггер FA-007 на больших репозиториях. | `pipeline_runner.py:549,1233,518,200,558,766`; `run_coordinator.py:417-432` | 08 (RES-2) | NEW |
| FA-009 | 🟠 | Resilience / Worker | **RES-3: duplicate-dispatch окно.** Post-index шаги (overview LLM + probes) вне heartbeat (`worker.py:115-116`); reap живого run → guards (`connections.py:207,716`) видят `failed` и запускают второй индекс параллельно (in-memory `_db_index_tasks` в ARQ-режиме пуст). Двойной расход LLM/CPU, гонки upsert'ов в ChromaDB. | `worker.py:115-116`; `connections.py:960-965,207,716,113-115` | 08 (RES-3) | NEW |
| FA-010 | 🟠 | UX / Auth | **H1: 401 → принудительный разлогин без видимого объяснения.** Тост «Session expired…» кладётся в in-memory zustand и уничтожается `window.location.href="/login"`; страница логина сообщения не содержит. Самый частый путь истечения сессии = внезапная перезагрузка без причины. | `_client.ts:16-17`; `toast-store.ts`; `app/login/page.tsx` | 03 (H1) | NEW (кластер с FA-020, FA-021) |
| FA-011 | 🟠 | Connectors / ClickHouse | **B2: CH-коннектор клинит после client-side timeout.** `asyncio.wait_for(to_thread(...))`: отмена корутины не останавливает поток с HTTP-стримом — session-lock занят → все последующие запросы падают «concurrent queries within the same session» до завершения серверного запроса (минуты). Усилитель: `distinct_values`/`approx_stats` глушат ошибки → молчаливая деградация индекса схемы. | `connectors/clickhouse.py:174-196` | 05 (B2) | NEW |
| FA-012 | 🟠 | Frontend perf | **F-1: триада gsap+lenis+motion (~90 KB gzip дублирующей функциональности).** gsap/lenis грузятся на всех marketing-страницах (даже текстовых: ~235 KB факт) и утекают в `/app` через общий root-layout manifest (факт /app ≈ 400 KB gzip). Консолидация на motion: −90 KB на `/`, −49 KB на текстовых, ~−60 KB на `/app`. | `(marketing)/layout.tsx:4`; `lib/motion/gsap.ts`; `SmoothScroll.tsx:4` | 09 (F-1) | NEW |
| FA-013 | 🟠 | Infra / Task queue | **C-1: тихий in-process fallback очереди без `REDIS_URL`.** Без Redis DB-индексация/sync/repo-index выполняются в web-процессе (1 vCPU, 512 MB) — API-латентность и RAM под индексацией, shutdown обрывает in-flight; отсутствие Redis = скрытая деградация без алерта. Prod Heroku-конфигурация из репозитория не видна — требуется ручная проверка. | `task_queue.py:21-40`; `connections.py:106,117-121` | 09 (C-1) | NEW (пересечение с issues.md F-SCHED-04 — семейство in-process fallback, R8) |

### Medium

| ID | Severity | Домен | Находка | Evidence | Источник | Статус |
|---|---|---|---|---|---|---|
| FA-014 | 🟡 | API docs | **65 эндпоинтов кода отсутствуют в API.md** — целиком разделы Billing (5), Connection Learnings (10), Runs (4), health_monitor (3) + 43 точечных (password-reset flow, logout, chat sessions/search/summarize, sync-now, test-ssh и др.). | перечень: 02 §2.1 | 02 (§2.1) + 01 (F-03) | NEW |
| FA-015 | 🟡 | API docs | **API.md: `POST /api/batch` vs код `POST /api/batch/execute`** — клиент по доке получит 404/405. Подтверждено живьём (405). | `batch.py:57-59`; 04 (D1) | 02 (§2.2) + 01 (F-03) + 04 (D1) | NEW |
| FA-016 | 🟡 | API docs | **API.md: `GET /api/batch/{id}/export` vs код `POST`** — неверный метод. | `batch.py:173-175` | 02 (§2.2) + 01 (F-03) | NEW |
| FA-017 | 🟡 | Billing / Rate limit | **`POST /api/checkout` и `POST /api/portal` без rate limit** — обращения к Stripe API; спам платёжными сессиями, нагрузка Stripe-квоты. | `billing.py:91,111` | 02 (N-1) | NEW (пересечение с issues.md F-BILL-03 — тот про webhook, R9) |
| FA-018 | 🟡 | Business logic | **F-01: дублирующиеся эндпоинты аналитики фидбека** под одним клиентским именем `getFeedbackAnalytics`: chat-вариант (агрегат `user_rating`) и data-validation-вариант (verdicts+learnings+benchmarks). UI использует только второй; chat-вариант мёртв; два источника правды о качестве ответов могут расходиться. | `chat_feedback.py:468`; `data_validation.py:145`; `frontend/src/lib/api/chat.ts:75`, `analytics.ts:88` | 01 (F-01) | NEW |
| FA-019 | 🟡 | Business logic | **F-02: мёртвая «intelligence» REST-поверхность (~17 эндпоинтов + мёртвые UI-компоненты).** feed/temporal/explore/reconciliation/data-graph/semantic-layer-build: клиентские namespaces определены, ни один компонент не вызывает; `TemporalReport/ReconciliationCard/ExplorationReport` нигде не рендерятся. Движки живы через chat-инструменты. HTTP-тестов роутов нет. | `frontend/src/lib/api/analytics.ts:254-483`; `feed.py`, `temporal.py`, `exploration.py`, `reconciliation.py`, `data_graph.py`, `semantic_layer.py` | 01 (F-02) | NEW |
| FA-020 | 🟡 | UX / Auth | **M1: `sessionExpiredHandled` никогда не сбрасывается.** Одноразовый флаг держится только на полной перезагрузке документа; переход на SPA-редирект молча отключит обработку повторных 401 до конца жизни вкладки. | `_client.ts:6,10` | 03 (M1) | NEW (кластер с FA-010) |
| FA-021 | 🟡 | UX / Auth | **M2: три разных текста об истечении сессии** — 401-тост («Session expired, please log in again»), брошенная ошибка перехватчика, таймерный путь («Your session has expired…»); только последний совпадает с SCN-011. | `_client.ts:16,119`; `chat.ts:152`; `auth-store.ts:74,87` | 03 (M2) | NEW (кластер с FA-010) |
| FA-022 | 🟡 | UX / Network | **M3: нет глобальной обратной связи при сетевых ошибках.** После ретраев (GET/HEAD ×2, 502/503/504) TypeError уходит наверх; часть списков молчит — `ConnectionHealth` застревает в вечном «unknown». | `_client.ts:97-106`; `ConnectionHealth.tsx:63-65` | 03 (M3) | NEW |
| FA-023 | 🟡 | UX / RBAC | **M4: action-кнопки Knowledge Health не gated по роли в UI.** Viewer видит Re-index/Index DB/Sync/Cancel/Retry; backend корректно отклоняет 403 → пользователь получает «Action failed» вместо скрытой кнопки. Несогласованно с IDX/SYNC-бейджами (там viewer видит статичные бейджи). | `KnowledgeHealthPanel.tsx:204,213`; `RunCard.tsx:108-116`; `connections.py:698,1039`; `repos.py:155` | 03 (M4) | NEW |
| FA-024 | 🟡 | UX | **M5: connections/schedules/learnings — ошибка загрузки только тостом → обманчивый empty-state.** Пользователь не отличит «пусто» от «сломалось», нет inline-ошибки и Retry — слабее стандарта остальных списков (dashboards/insights/logs/batch). | `ProjectSelector.tsx:413-421`; `ScheduleManager.tsx:112`; `LearningsPanel.tsx:58` | 03 (M5) | NEW |
| FA-025 | 🟡 | Session notes | **B1: периодический decay заметок падает на SQLite** — `func.greatest` отсутствует в SQLite → `OperationalError` каждый тик цикла. На SQLite-деплое (dev/дефолт) decay confidence заметок молча не работает вообще; на PostgreSQL не воспроизводится. | `session_notes_service.py:439` | 04 (B1) | NEW |
| FA-026 | 🟡 | ClickHouse / EXPLAIN | **B3: EXPLAIN-warnings — ложные «full MergeTree scan» на CH 24.8.** Plain `EXPLAIN` никогда не содержит `prewhere`/`where` (условие прячется в `ReadFromMergeTree`) → warning срабатывает и на `WHERE id = 5` (key lookup). Фикс: `EXPLAIN indexes = 1` + анализ `Indexes:/Condition/Granules`. | `core/explain_validator.py:133-142,58-59` | 05 (B3) | NEW (пересечение с issues.md F-SQL-07 — асимметрия EXPLAIN по диалектам, R11) |
| FA-027 | 🟡 | Result gate | **AQ-3: на flat-пути «block» — advisory-текст, не enforcement.** Даже `action="block"` лишь дописывает «[DATA-GATE BLOCK — DO NOT USE THIS RESULT]» в tool output; результат с «невозможными» числами возвращается оркестратору, блокировка отдана instruction-following LLM. На pipeline-пути — истинное принуждение (retry/replan). Асимметрия: самый частый путь защищён слабее. | `sql_agent.py:997-1045` vs `stage_executor.py:415-431,760-766` | 06 (AQ-3) | NEW |
| FA-028 | 🟡 | DataGate | **AQ-4: native `datetime` обходит date hard-check.** Ветки проверки — только `str` и `int/float`; asyncpg/pymysql возвращают `datetime`-объекты → year-range hard check мёртв на PostgreSQL/MySQL (воспроизведено: год 1500 → passed). | `data_gate.py:423-480` | 06 (AQ-4) | NEW (вариант семейства issues.md F-DG-01, R12) |
| FA-029 | 🟡 | DataGate | **AQ-5: строковые числа обходят все value-range проверки.** `"150"` в percent-колонке → passed (воспроизведено). Коннекторы, отдающие числа текстом (часть драйверов/CSV/MongoDB), молча обходят hard checks. | `data_gate.py:366-367` | 06 (AQ-5) | NEW (семейство F-DG-01, R12) |
| FA-030 | 🟡 | DataGate | **AQ-6: false-positive hard-fail на денежных «conversion_*» колонках.** `conversion_amount`=150 (валютная конверсия) → kind=percent → hard fail → retry×2 → replan → stage_failed (воспроизведено). Аналогично `occupancy`>100% при овербукинге. | `data_gate.py:58-68,321-326` | 06 (AQ-6) | NEW (пересечение с issues.md F-DG-03, R12) |
| FA-031 | 🟡 | Learnings | **AQ-7: API confirm/contradict без per-user dedup — накрутка confidence.** 4-5 кликов confirm: 0.6→1.0/★CRITICAL; 2 клика contradict деактивируют чужой learning. Один редактор единолично управляет ранжированием корпуса проекта; аудита голосовавших нет. | `connection_learnings.py:248-311`; `agent_learning_service.py:526-602` | 06 (AQ-7) | **DUP → issues.md F-LEARN-03** (открыт, R6; подтверждён + новый вектор: contradict-деактивация) |
| FA-032 | 🟡 | DataGate | **AQ-8 (by design): классификация только по имени колонки** — `AS x` прячет 150% conversion; LLM-семантика (`data_gate_llm_semantics`) нигде в коде не подключена. Главный структурный обход гейта. | `data_gate.py:291-335`; `config.py:680` | 06 (AQ-8) | NEW (пересечение с issues.md F-DG-03, R12) |
| FA-033 | 🟡 | Config / Auth | **S-04: `environment: str = "development"` входит в `_SAFE_ENVIRONMENTS`** — unset `ENVIRONMENT` молча = development, проверки секретов (JWT, MASTER_ENCRYPTION_KEY, DEBUG, CORS `*`) пропускаются. Заявленный fail-closed («unset = production») подорван дефолтом. | `config.py:62` vs `:51-55`, `:773-808` | 07 (S-04) | NEW |
| FA-034 | 🟡 | Backend deps | **Уязвимые зависимости backend (pip-audit):** `gitpython 3.1.50` (3 GHSA → fix 3.1.51), `mcp 1.27.2` (CVE-2026-59950 → fix 1.28.1), `pyasn1 0.6.3` (3 CVE → fix 0.6.4), `chromadb 1.5.9` (CVE-2026-45829, фикса нет), `ecdsa 0.19.2` (CVE-2024-23342, фикса нет; уйдёт с jose→PyJWT). | вывод `pip-audit --skip-editable --aliases` | 07 (S-05) | NEW |
| FA-035 | 🟡 | Frontend deps | **Прочие prod-уязвимости frontend (все с fix):** `sharp <0.35.0` (4 libvips CVE), `postcss ≤8.5.11` (XSS через `</style>`), `fast-uri` (host confusion), `brace-expansion` (DoS ×2), `@opentelemetry/*` (DoS). `npm audit fix` закрывает все. | `npm audit --omit=dev` (8: 5 high/3 moderate) | 07 (S-06) | NEW |
| FA-036 | 🟡 | Rate limit / Multi-dyno | **Multi-dyno без Redis:** slowapi на `memory://` → эффективный лимит ×N процессов, при рестарте счётчики сбрасываются; WS-тикеты не redeem'ятся cross-dyno; cron single-flight off (каждый dyno запускает git-poll/daily-sync волну); in-memory `agent_limiter` умножает per-user cap на число dyno. | `rate_limit.py:20-28`; `ws_tickets.py:101-110`; `distributed_lock.py:24-25`; `agent_limiter.py:96-120` | 07 (S-07) + 08 (RES-7) + 09 (§4.3) | NEW (пересечение с issues.md F-SCHED-05, R8) |
| FA-037 | 🟡 | Secrets | **S-08: notes.md — проблема «credentials on disk» устранена (файла нет на диске)**, но креды формально остаются скомпрометированными: нужна ротация + обновить запись в `docs/agent-status.md:42`. Закоммиченных секретов в git нет. | `find`/`git ls-files`; `.gitignore:74` | 07 (S-08) | NEW (подтверждение устранения; остаток — ротация) |
| FA-038 | 🟡 | Resilience / Startup | **RES-4: module-level `VectorStore()` в repos.py без try/except** — крах Chroma `PersistentClient` (битая локальная БД/права) при импорте = приложение не стартует вообще. | `repos.py:46`; `vector_store.py:111-121` | 08 (RES-4) | NEW |
| FA-039 | 🟡 | Resilience / ChromaDB | **RES-5: Chroma outage ≡ «нет KB»** — `has_knowledge_base` при любой ошибке молча возвращает False без лога; роутер не предлагает KB-инструменты, freshness-warning не показывается. Аутедж неотличим от «проект не проиндексирован»; теряются doc-RAG и provenance. | `context_loader.py:167-172` | 08 (RES-5) | NEW (семейство silent-degradation issues.md F-KNOW-07, R7) |
| FA-040 | 🟡 | Resilience / Worker | **RES-6: post-index и final-status сбои worker'а логируются на DEBUG** — в проде с LOG_LEVEL=INFO невидимы ни в логах, ни в метриках; проект молча остаётся без overview/probes, статус `completed` вводит в заблуждение. Уровень ниже, чем в in-process пути (там WARNING). | `worker.py:103-131,176-190` | 08 (RES-6) | NEW (пересечение с issues.md CB-M5) |
| FA-041 | 🟡 | Resilience / Embeddings | **RES-8: сбой embedding reconcile / проверки окна токенов — log-only/беззвучно** — устаревшие/усечённые векторы продолжают обслуживаться без сигнала оператору. | `main.py:135-136`; `vector_store.py:41-43` | 08 (RES-8) | NEW |
| FA-042 | 🟡 | Frontend perf | **F-2: статический импорт `remark-gfm` обесценивает lazy-границу react-markdown** — micromark/gfm-дерево (28 KB gzip) грузится eager в `/app`. Фикс: импорт плагина внутри lazy-обёртки → 353→~325 KB First Load. | `ChatMessage.tsx:6`; `SQLExplainer.tsx:5` | 09 (F-2) | NEW |
| FA-043 | 🟡 | Backend perf | **P-1: COUNT через полную материализацию четырёх store'ов** (`_artifact_counts`, knowledge_health) — все ORM-строки (вкл. Text/JSON-поля) ради `len()`. Для 1000 таблиц — тысячи объектов на каждый health-запрос. Фикс: `select(func.count())`. | `knowledge_catalog_service.py:595-637` | 09 (P-1) | NEW |
| FA-044 | 🟡 | Backend perf | **P-2: LIMIT в Python — `get_index` без SQL-лимита**, срез `rows[:limit]` после полной выборки. Горячий путь: ContextPack на каждый chat-запрос; критично на схемах 500+ таблиц. | `db_index_service.py:55-65`; `knowledge_catalog_service.py:290` | 09 (P-2) | NEW |
| FA-045 | 🟡 | Backend perf | **P-3: `get_learnings` — limit/table_filter/sort в Python** (`scalars().all()` → подстрочная фильтрация → срез). Горячий путь prompt-compile (смягчается кэшем compiled_prompt). | `agent_learning_service.py:631-653,896` | 09 (P-3) | NEW |
| FA-046 | 🟡 | DB indexes | **I-1: нет индекса `chat_messages(session_id, created_at DESC, id DESC)`** — каждый chat-запрос (последние 20 сообщений) делает sort после index-scan по session_id. | `chat_service.py:158-163`; `chat_session.py:54` | 09 (I-1) | NEW |
| FA-047 | 🟡 | DB indexes | **I-2: нет индекса `agent_learnings(connection_id, is_active, confidence DESC, times_confirmed DESC)`** — compile prompt фильтрует и сортирует в памяти. | `agent_learning_service.py:631-642` | 09 (I-2) | NEW |
| FA-048 | 🟡 | DB indexes | **I-3: нет индекса `notifications(user_id, is_read, created_at DESC)`** — polling бейджа непрочитанных с фронта; `is_read` не индексирован. | `notification.py:15,18` | 09 (I-3) | NEW |

### Low

| ID | Severity | Домен | Находка | Evidence | Источник | Статус |
|---|---|---|---|---|---|---|
| FA-049 | 🟢 | API surface | **F-04: query-failures API без потребителя** — 2 эндпоинта + клиент + 9 unit-тестов есть, UI-вкладки failures в LogsScreen нет. | `logs.py:172,202`; `analytics.ts:189-211` | 01 (F-04) | NEW |
| FA-050 | 🟢 | Business logic | **F-05: две параллельные реализации «каталога метрик»** — semantic_layer (UI читает) vs data_graph (полностью без потребителей); риск рассинхрона определений метрик для insights/reconciliation. | `semantic_layer.py`; `data_graph.py`; `KnowledgeHub.tsx:50` | 01 (F-05) | NEW |
| FA-051 | 🟢 | Routing | **F-06: хрупкий порядок монтирования health_monitor** — GET `/api/connections/health` резолвится только из-за порядка include; перестановка отдаст путь под `{connection_id}` → 404. Теста, фиксирующего порядок, нет. | `main.py:426-427`; `health_monitor.py:17,45`; `connections.py:471` | 01 (F-06) | NEW |
| FA-052 | 🟢 | UX docs | **F-09: центр уведомлений и выбор LLM-модели — user-facing фичи вне scenarios.md** — нарушение hard-rule «scenarios.md is source of truth» (4 эндпоинта notifications + `LlmModelSelector`). | `LlmModelSelector.tsx:49`; notifications API | 01 (F-09) | NEW |
| FA-053 | 🟢 | Testing | **F-10: onboarding — единственный сквозной новопользовательский путь без сквозного backend integration-теста** (register → connect → test → index → first ask). | 01 (F-10) | 01 (F-10) | NEW |
| FA-054 | 🟢 | Rate limit | `PATCH /api/schedules/{id}` без rate limit (и без параметра `request: Request`, необходимого slowapi). | `schedules.py:167` | 02 (N-1) | NEW |
| FA-055 | 🟢 | Rate limit | `POST /api/data-validation/investigate/{id}/confirm-fix` без rate limit (start_investigation ограничен 5/min). | `data_investigations.py:237` | 02 (N-1) | NEW |
| FA-056 | 🟢 | Rate limit | `POST /api/chat/ws-ticket` без rate limit — тикеты можно фармить (ask ограничен 20/min). | `chat.py:1375` | 02 (N-1) | NEW |
| FA-057 | 🟢 | API contract | **N-2: 404/403-оракул существования ресурса (паттерн)** — fetch-first порядок различает несуществующий ID (404) и чужой (403). Смягчается UUID; рекомендация: uniform 404 (как в data_investigations). | `connections.py:474-477`; `chat_sessions.py:126-133`; `batch.py:121-125`; `notes.py:87-101` и др. | 02 (N-2) | NEW |
| FA-058 | 🟢 | API docs | API.md:4 — «только `/api/auth/*` и `/api/health` публичны» неверно: ещё `GET /api/plans` и два webhook с подписью. | `API.md:4`; `billing.py:41,130`; `repos.py:363` | 02 (§2.4) | NEW |
| FA-059 | 🟢 | API docs | API.md:362-365 — «mutating endpoints are rate-limited» неверно: 8 мутаций без лимита. | `API.md:362-365` | 02 (§2.4) | NEW |
| FA-060 | 🟢 | API contract | `logs.py` update_error: невалидный `error_id` и невалидный `status` оба → 400 (в остальных роутерах отсутствующий ресурс → 404). | `logs.py:168-170` | 02 (N-5) | NEW |
| FA-061 | 🟢 | API contract | `connections.py` update_connection: бизнес-валидация возвращает 422 вручную — клиент не отличит от Pydantic-ошибки (в других местах 400). | `connections.py:506-511` | 02 (N-5) | NEW |
| FA-062 | 🟢 | Pagination | **7 списочных эндпоинтов без верхнего limit** (session messages le=2000, notes, dashboards, data-graph relationships/metrics, semantic catalog, repos docs, learnings) — тяжёлые ответы/память на больших объёмах. | `chat_sessions.py:262`; `notes.py:146-156`; `dashboards.py:81-89`; `data_graph.py:98,162-175`; `semantic_layer.py:68-90`; `repos.py:735-753`; `connection_learnings.py:33-60` | 02 (§4) | NEW (частичное пересечение с issues.md F-PROJ-13) |
| FA-063 | 🟢 | SSRF | `POST /api/repos/check-access` как SSRF-зонд — probing произвольных host:port через git-протокол (смягчается 10/min, возвращает только refs). | `repos.py:105-136` | 02 (N-4) | NEW |
| FA-064 | 🟢 | UX | SCN-041 (PARTIAL): auto-growing textarea не реализован — жёстко `rows={1}`, скролл вместо роста. | `ChatInput.tsx:32-48` | 03 (L1) | NEW |
| FA-065 | 🟢 | UX | SCN-054 (PARTIAL): per-step elapsed не рендерится (`elapsed_ms` собирается, не выводится). | `ReasoningPanel.tsx:42-86`; `ChatPanel.tsx:467` | 03 (L2) | NEW |
| FA-066 | 🟢 | UX | SCN-077 (PARTIAL): нет кнопки Cancel в модалке создания правила (только X FormModal). | `RulesManager.tsx:226` | 03 (L3) | NEW |
| FA-067 | 🟢 | UX | SCN-010: в SettingsPanel-варианте Delete Account нет фразы «This action cannot be undone». | `SettingsPanel.tsx:286-288` vs `AccountMenu.tsx:202` | 03 (L4) | NEW |
| FA-068 | 🟢 | UX | SCN-043: разные суффиксы partial-commit — stop vs switched session. | `ChatPanel.tsx:690,382` | 03 (L5) | NEW |
| FA-069 | 🟢 | UX | SCN-106: баннер «Failed to load logs» + Retry только на табе queries (Runs/Errors компенсируют своими inline). | `LogsScreen.tsx:147` | 03 (L6) | NEW |
| FA-070 | 🟢 | UX | SCN-063: severity warning показан только цветом, без текстовой метки. | `KnowledgeHealthPanel.tsx:27-31,233` | 03 (L7) | NEW |
| FA-071 | 🟢 | UX | SCN-068: scope-aware empty copy минимально дифференцирован (all/mine идентичны). | `NotesPanel.tsx:116,119-121` | 03 (L8) | NEW |
| FA-072 | 🟢 | UX | SCN-074: одинаковый текст error-тоста «Failed to update» у toggleActive и saveEdit. | `LearningsPanel.tsx:85,99` | 03 (L9) | NEW |
| FA-073 | 🟢 | UX | SCN-102: empty-состояние usage — молчаливый `return null`. | `UsageStatsPanel.tsx:95` | 03 (L10) | NEW |
| FA-074 | 🟢 | UX docs | SCN-012: тост resend длиннее цитаты («— check your inbox.»). | `EmailVerifyBanner.tsx:31`; `verify-email/page.tsx:54` | 03 (L11) | NEW |
| FA-075 | 🟢 | UX docs | SCN-023/060/087/089: цитаты текстов — префиксы/парафразы фактических. | `InviteManager.tsx:134-135`; `ChartRenderer.tsx:80-83`; `BatchRunner.tsx:161`; `BatchResults.tsx:180` | 03 (L12) | NEW |
| FA-076 | 🟢 | UX docs | SCN-098/099/103/104: тосты — fallback-строки, при наличии `err.message` показывается оно. | `PricingTable.tsx:109`; `BillingPanel.tsx:98`; `McpTokenManager.tsx:104,121` | 03 (L13) | NEW |
| FA-077 | 🟢 | Frontend | Мёртвый CSS `.compact-touch` (opt-out определён, нигде не используется). | `globals.css:599-603` | 03 (L14) | NEW |
| FA-078 | 🟢 | UX | SCN-065: severity-фильтры скрыты при пустой сводке; кастомный спиннер вместо `Spinner`. | `InsightFeedPanel.tsx:280,287,309-310` | 03 (L15) | NEW |
| FA-079 | 🟢 | Observability | **B2: `/api/health/modules` сообщает `llm: ok` при мёртвом ключе** — проверка конфигурационная (ключ задан), не живостная; health-мониторинг не заметит отказа главной зависимости. | `main.py:1225+` | 04 (B2) | NEW (пересечение с FA-100) |
| FA-080 | 🟢 | API docs | D2: `/api/health/modules` требует auth (by design, docstring) — в API.md различие с публичным `/api/health` не отражено. | `main.py:1227` | 04 (D2) | NEW |
| FA-081 | 🟢 | SafetyGuard / Mongo | **B4: `validate_mongo` не блокирует `$out`/`$merge`/server-side JS** — проходят SafetyGuard; перехватывает только коннекторный гард `_assert_mongo_read_safe` (проверено живьём). Слои асимметричны: путь «только SafetyGuard + non-RO» открыт. | `core/safety.py:127-145`; `connectors/mongodb.py:48-71` | 05 (B4) | NEW (остаток после закрытого релиза R1) |
| FA-082 | 🟢 | SafetyGuard | B5 (by design): `;` внутри строкового литерала → ложное «multiple statements» (`WHERE name = 'a;b'` блокируется). Задокументированный tradeoff regex-подхода. | `core/safety.py:93-99` | 05 (B5) | NEW (задокументировано) |
| FA-083 | 🟢 | Cross-DB | B6: Mongo `approx_stats` считает explicit `null` отдельным distinct-значением (10 vs 9 у MySQL/CH); missing-поле не учитывается ни как distinct, ни как null. | `connectors/mongodb.py:428-486` | 05 (B6) | NEW |
| FA-084 | 🟢 | AnswerValidator | AQ-9: `bool("false")==True` — строковый verdict от LLM засчитан как адресующий; `confidence=float(...)` при нечисловом кидает вне try. | `answer_validator.py:197-201` | 06 (AQ-9) | NEW |
| FA-085 | 🟢 | Reconcile | AQ-10: reconcile требует точного float-равенства `round(total,2)` — копеечное расхождение SUM → защитная recon-заметка не строится. | `sql_result_reconciliation.py:121-134` | 06 (AQ-10) | NEW (подтверждает задокументированный xfail DATA-15) |
| FA-086 | 🟢 | DataGate | AQ-11: cartesian-порог 100× — 2× fan-out от плохого JOIN молча проходит. | `data_gate.py:523-530`; `config.py:676` | 06 (AQ-11) | NEW (xfail DATA-21, strict — сторожит поведение) |
| FA-087 | 🟢 | Learnings | AQ-12: dedup-race SELECT-then-INSERT в `create_learning` — ловится только ValueError; IntegrityError эскалирует до stage error вместо корректного merge. | `sql_agent.py:861-874`; `models/agent_learning.py:30-36` | 06 (AQ-12) | NEW |
| FA-088 | 🟢 | Eval / CI | AQ-13: CI retrieval-gate гоняет только synthetic-ретриверы — регресс качества реального HybridRetriever/SchemaRetriever гейтом не ловится. | `.github/workflows/ci.yml:99-105`; `test_retrieval_eval.py:114-152` | 06 (AQ-13) | NEW |
| FA-089 | 🟢 | Learnings | AQ-14: subject-blocklist exact-match без strip — «pg_stat_user_tables», «columns » (с пробелом) проходят. | `agent_learning_service.py:55-68,81` | 06 (AQ-14) | NEW |
| FA-090 | 🟢 | Learnings | AQ-15: `expose_learning` без flush — хрупкий контракт «caller commits» (apply_learning flush'ит — несогласованность). | `agent_learning_service.py:558-572` | 06 (AQ-15) | NEW |
| FA-091 | 🟢 | AnswerQualityGate | AQ-16: action `requery` на pipeline-пути не requery (пайплайн завершён) — misleading contract, фактически downgrade-маркер. | `result_validation.py:241-245`; `response_builder.py:104-109` | 06 (AQ-16) | NEW |
| FA-092 | 🟢 | Backend deps | S-09: `python-jose 3.5.0` заброшен (текущих CVE для версии нет, использование безопасно — HS256 whitelist); риск — отсутствие будущих патчей. План: PyJWT. | `auth_service.py:8,64,68`; `config.py:101` | 07 (S-09) | NEW |
| FA-093 | 🟢 | Auth | S-10: email-verification токен без срока действия (SHA-256, одноразовый; у password-reset expiry 1ч) — утёкшая ссылка живёт бесконечно. | `auth_service.py:131-156` vs `:181-183` | 07 (S-10) | NEW |
| FA-094 | 🟢 | MCP | S-11: `mcp_allowed_hosts=[]` — DNS-rebinding protection mount'а выключена по умолчанию (смягчается `mcp_enabled=False` + bearer-auth). | `config.py:636-639`; `mcp_server/asgi.py:56-77` | 07 (S-11) | NEW |
| FA-095 | 🟢 | Auth / JWT | S-12: `jwt_expire_minutes=1440` (24ч) — длинное окно access-токена (компенсируется token_version + refresh + httpOnly). | `config.py:102` | 07 (S-12) | NEW |
| FA-096 | 🟢 | CORS | S-13: `allow_methods=["*"]`, `allow_headers=["*"]` при `allow_credentials=True` (origins строгие; поверхность шире необходимого). | `main.py:411-417`; `config.py:283-287` | 07 (S-13) | NEW |
| FA-097 | 🟢 | Resilience | RES-9: summary-статусы после reap без причины — `DbIndexSummary`/`CodeDbSyncSummary` получают голый `failed` (фронт рендерит generic error). | `stale_run_reaper.py:46-58`; `OnboardingWizard.tsx:200-201` | 08 (RES-9) | NEW |
| FA-098 | 🟢 | Resilience | RES-10: early return в worker (connection/project not found) → run висит `running` 300с, причина перезаписывается на «stale run reaped». | `worker.py:42-43`; `repos.py:326-330` | 08 (RES-10) | NEW |
| FA-099 | 🟢 | Resilience | RES-11: отказ heartbeat-writer беззвучен (DEBUG) — при partition до БД >300с живой run будет reap'нут с искажённой причиной. | `heartbeat.py:22-28` | 08 (RES-11) | NEW |
| FA-100 | 🟢 | Observability | RES-12: LLM health-check при старте — failure на DEBUG (спасает per-call fail-fast 0.49с, но сигнал оператору на DEBUG). | `main.py:176-177` | 08 (RES-12) | NEW (пересечение с FA-079) |
| FA-101 | 🟢 | Frontend | F-3 (принято): Sentry в shared chunk для всех страниц (~15–25 KB gzip мёртвого веса на marketing-трафике). | `next.config.ts:66` | 09 (F-3) | NEW (принято отчётом) |
| FA-102 | 🟢 | Frontend | F-4: `next.config.ts` без `optimizePackageImports`/`modularizeImports`; двойной lockfile путает `outputFileTracingRoot` (размер standalone-образа). | `next.config.ts` | 09 (F-4) | NEW |
| FA-103 | 🟢 | Frontend | F-5: `msw` — мёртвая devDependency (0 использований в `src/`). | `package.json:49` | 09 (F-5) | NEW |
| FA-104 | 🟢 | Backend perf | P-4 (Low-Medium): `decay_stale_learnings` — full-scan всех подключений + поштучные ORM-апдейты + N+1 инвалидация summary. | `agent_learning_service.py:1239-1271` | 09 (P-4) | NEW |
| FA-105 | 🟢 | Backend perf | P-5 (Low-Medium): блокирующий sync `vector_store.query` (Chroma+ONNX) на event loop при выключенном hybrid — десятки мс блокировки на запрос. | `knowledge_catalog_service.py:539`; `context_loader.py:377` | 09 (P-5) | NEW |
| FA-106 | 🟢 | Backend perf | P-6: `list_requests` тянет все 19 колонок RequestTrace (Text-поля question/error_message зря на каждой странице логов). | `logs_service.py:77` | 09 (P-6) | NEW |
| FA-107 | 🟢 | DB indexes | I-4 (Low-Medium): `request_traces.session_id` (FK) без индекса — seq-scan при `ON DELETE SET NULL` из chat_sessions. | `request_trace.py:28-32` | 09 (I-4) | NEW |
| FA-108 | 🟢 | DB indexes | I-5: нет индекса `agent_learnings(is_active, updated_at)` — decay-джоба full-scan (см. FA-104). | 09 (§3) | 09 (I-5) | NEW |
| FA-109 | 🟢 | DB indexes | I-6: `request_traces.message_id` (FK, SET NULL) без индекса — аналогично FA-107. | 09 (§3) | 09 (I-6) | NEW |

### Info

| ID | Severity | Домен | Находка | Evidence | Источник | Статус |
|---|---|---|---|---|---|---|
| FA-110 | ⚪ | API surface | F-07: MCP-токены живут под `/api/auth` при отдельном роутере — путаница доменов при трассировке (SCN-103/104 → mcp, путь → auth). | `main.py:420` | 01 (F-07) | NEW |
| FA-111 | ⚪ | Docs | F-08: дрейф заявленного числа тестов — CLAUDE.md «4865+543», README «5,107», MASTER_TEST_PLAN «2,897+346» vs факт 5439 backend (00-базлайн подтвердил прогоном). | `CLAUDE.md`; 00-baseline.md | 01 (F-08) + 00 | NEW |
| FA-112 | ⚪ | Rate limit | `POST /api/auth/logout` без лимита (идемпотентно, низкий риск). | `auth.py:343` | 02 (N-1) | NEW |
| FA-113 | ⚪ | Rate limit | `POST /api/auth/complete-onboarding` без лимита (флаг в профиле, низкий риск). | `auth.py:391` | 02 (N-1) | NEW |
| FA-114 | ⚪ | Rate limit | `POST /api/webhook` (Stripe) без лимита — осознанно (Stripe ретраит при 5xx); зафиксировать в комментарии/доке. | `billing.py:130` | 02 (N-1) | NEW (связь с issues.md F-BILL-03) |
| FA-115 | ⚪ | Arch / Rate limit | slowapi лимитирует per-IP: ложные срабатывания за общим NAT, слабая защита от пула IP — рассмотреть per-user ключи для аутентифицированных эндпоинтов. | `API.md:362-365` | 02 (§2.4) | NEW |
| FA-116 | ⚪ | API docs | API.md:35 — перечислены лимиты не всех auth-эндпоинтов (нет refresh 30/min, change-password 5/min, delete-account 3/min, verify-email 10/min). | `API.md:35` | 02 (§2.4) | NEW |
| FA-117 | ⚪ | SSRF | DB host в connections — подключение к произвольному host:port суть продукта; read-only флаг + SafetyGuard ограничивают ущерб. | `connections.py:428+` | 02 (N-4) | NEW (семейство issues.md F-CONN-04) |
| FA-118 | ⚪ | Validation | `validate_safe_id` применяется непоследовательно — connections/projects/batch/schedules path-ID без regex (ID идут только в параметризованные запросы — риск низкий). | `deps.py:16-23` | 02 (N-4) | NEW |
| FA-119 | ⚪ | API contract | Billing: ошибка конфигурации Stripe (`BillingError`) → 500 наряду с внутренними сбоями (семантически 502/503). | `billing.py:137-138` | 02 (N-5) | NEW |
| FA-120 | ⚪ | Pagination | `GET /api/batch?project_id=` без limit (user+project scoped). | `batch.py:131-139` | 02 (§4) | NEW |
| FA-121 | ⚪ | Pagination | `GET /api/logs/{id}/users` без limit (owner-only, кардинальность = члены проекта). | `logs.py:33-45` | 02 (§4) | NEW |
| FA-122 | ⚪ | Pagination | `GET /api/invites/{id}/members`, `.../invites`, `/pending` без limit (низкая кардинальность). | `invites.py:102,231,253` | 02 (§4) | NEW (пересечение с issues.md F-PROJ-13) |
| FA-123 | ⚪ | Pagination / Perf | `GET /api/rules`, `GET /api/projects` без limit (низкая кардинальность); плюс N+1: `repos/{id}/docs/{doc_id}` грузит все docs проекта ради одного. | `rules.py:102`; `projects.py:214`; `repos.py:764-767` | 02 (§4) | NEW |
| FA-124 | ⚪ | UX docs | I1: SCN-048 — rename UI и bulk clear-history отсутствуют (задокументированный GAP, подтверждён кодом). | 03 (I1) | 03 | NEW |
| FA-125 | ⚪ | UX docs | I2: SCN-052 — `WrongDataModal.tsx` существует, но нигде не импортируется; thumbs-down шлёт canned prompt (подтверждено). | `WrongDataModal.tsx` | 03 (I2) | NEW |
| FA-126 | ⚪ | UX docs | I3: SCN-066 — «Investigate» drill-down не wired (`KnowledgeHub.tsx:99` без `onDrillDown`), как заявлено. | `KnowledgeHub.tsx:99` | 03 (I3) | NEW |
| FA-127 | ⚪ | UX docs | I4: SCN-085 — invalid/expired/forbidden схлопываются в один экран «Dashboard not found» (подтверждено). | `app/dashboard/[id]/page.tsx:216-228` | 03 (I4) | NEW |
| FA-128 | ⚪ | UX docs | I5: SCN-037 — у списка connections нет list-level loading spinner (подтверждено). | 03 (I5) | 03 | NEW |
| FA-129 | ⚪ | UX docs | I6: SCN-108 — обрыв SSE отражается только StatusDot (подтверждено; автореконнект есть). | `LogPanel.tsx`; `useGlobalEvents.ts:48-59` | 03 (I6) | NEW |
| FA-130 | ⚪ | UX | I7: SCN-025 — auto-fill порта не затирает кастомный порт (guard `knownDefaults.includes`) — улучшение относительно буквы сценария. | `ConnectionSelector.tsx:651-653` | 03 (I7) | NEW |
| FA-131 | ⚪ | UX docs | I8: массовый мелкий дрейф line-ссылок Coverage (±1–25 строк) в ~18 сценариях — требуется ресинхронизация scenarios.md; ни одна ссылка не указывает на несуществующее поведение. | 03 (I8) | 03 | NEW |
| FA-132 | ⚪ | Bootstrap | N1 (by design): новый пользователь не может создать проект без ручного гранта `can_create_projects` — первый пользователь self-hosted упирается в 403; задокументировать bootstrap (или env-флаг auto-grant). | `models/user.py:26`; `projects.py:137` | 04 (N1) | NEW |
| FA-133 | ⚪ | Connections | N2 (by design): create connection не валидирует коннективность (dead port → 200; отказ всплывает на `/test` ~3с) — фронту всегда вызывать test после create. | 04 (N2) | 04 | NEW |
| FA-134 | ⚪ | Viz | N3: тихий fallback невалидного `viz_type` на `table` без предупреждения в ответе. | `renderer.py:43` | 04 (N3) | NEW |
| FA-135 | ⚪ | Environment | E1: невалидный `OPENROUTER_API_KEY` в `backend/.env` (401 «User not found»), OPENAI/ANTHROPIC пусты — любой LLM-функционал в окружении неработоспособен; требуется замена ключа и повтор золотого пути (см. «Ограничения аудита»). | `backend/.env`; проверка `openrouter.ai/api/v1/auth/key` | 04 (E1) | NEW (окружение, не код) |
| FA-136 | ⚪ | Cross-DB | Наблюдения (не дефекты): семантика `connect()` различается (eager MySQL/CH vs lazy Mongo); пустой результат без имён колонок у всех трёх; косметика MySQL-интроспекции view; Mongo timeout на мёртвый хост 10.1с (ограничен); `UNRESTRICTED` пропускает DROP (by design). | 05 (раздел «Прочие наблюдения») | 05 | NEW |
| FA-137 | ⚪ | Logging | S-14: прямого логирования секретов не найдено (только email, user_id, публичные display-префиксы); email в логах — PII, учесть в retention-политике. | `mcp_server/auth.py:46-55`; `mcp_key_service.py:153`; `auth_service.py:115-120` | 07 (S-14) | NEW |
| FA-138 | ⚪ | Headers | S-15 (позитив): заголовки в порядке — nosniff, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, CSP enforce (не report-only), HSTS 1год+includeSubDomains; лимит тела 10 MB. | `main.py:318-372`; `config.py:587-607` | 07 (S-15) | NEW (позитив) |
| FA-139 | ⚪ | SSH / MCP | S-16 (позитив): подтверждены SSH host-key tofu + pre-command allowlist (по умолчанию включён), MCP auth fail-closed (`hmac.compare_digest`, per-user токены по SHA-256), `mcp_enabled=False` по умолчанию. | `config.py:712-725,868-869`; `ssh_pre_commands.py:53-86`; `mcp_server/auth.py:92-115,140-190` | 07 (S-16) | NEW (позитив) |
| FA-140 | ⚪ | Audit artifact | S-17: 6 уязвимостей `pip 25.0.1` в выводе pip-audit — артефакт установки pip для аудита, не зависимости проекта. | вывод pip-audit | 07 (S-17) | NEW |
| FA-141 | ⚪ | Runbook | RES-13 (внешний риск): `source .env` ломает `CORS_ORIGINS` (bash съедает кавычки JSON) → `SettingsError`. В доках репозитория паттерн не рекомендуется, но явно не запрещён; приложение читает `.env` само. | `.env.example:83`; 04 (процедура) | 08 (RES-13) + 04 | NEW |
| FA-142 | ⚪ | Concurrency | C-2: пул БД 5+10=15 — практический потолок ~10–15 одновременных agent-run на dyno (при условии, что целевые БД и LLM выдерживают); capacity planning. | `config.py:69-72`; `base.py:20-24` | 09 (C-2) | NEW |
| FA-143 | ⚪ | Retrieval / Prod | R-1 (принято, CHANGELOG 1.15.1): на 512 MB dyno — ONNX MiniLM 384-dim вместо bge 768-dim, reranker no-op; два из трёх усилителей качества retrieval в проде выключены инфраструктурно. Путь включения — dyno ≥1 GB + sentence-transformers + reindex. | `vector_store._get_embedding_function`; `reranker.py`; CHANGELOG 1.15.1 | 09 (R-1) | NEW |
| FA-144 | ⚪ | Perf / UX | P-7 (by design): 3.01с на мёртвом порту connection-test — `@retry(max_attempts=3, backoff=1.0)`; фронту показывать прогресс. | `connection_service.py:273-277`; замер 04 | 09 (P-7) + 04 | NEW |

---

## Пересечения с уже известными находками (`docs/qa-audit/issues.md`)

Явные дубли (находка этого аудита = уже открытый пункт):

| FA | Дубль | Комментарий |
|---|---|---|
| FA-002 (AQ-1) | F-LEARN-08 (🟡, R6) | Подтверждена и усилена: конкретный механизм накрутки (−0.3×N + dedup +0.1 до ★CRITICAL), endpoint 0% coverage |
| FA-031 (AQ-7) | F-LEARN-03 (🟢, R6) | Подтверждена + новый вектор: contradict-деактивация чужих уроков за 2 клика |

Пересечения (новая находка в известном семействе):

| FA | Известное семейство |
|---|---|
| FA-003 (AQ-2) | F-SQL-01 + F-LEARN-01 (R6) — известен канал инъекции; впервые собрана полная персистентная цепочка |
| FA-004 (git-SSRF) | F-CONN-04 (R5) — SSRF-семейство; 07 фиксирует «подтверждает более ранний аудит» |
| FA-007/FA-008/FA-009 (RES-1..3) | F-SCHED-03 (R8) — reaper-контур; новые race (необратимость, heartbeat-gaps, duplicate-dispatch) |
| FA-013 (C-1) | F-SCHED-04 (R8) — in-process fallback семейство |
| FA-026 (B3) | F-SQL-07 (R11) — асимметрия EXPLAIN по диалектам |
| FA-028/FA-029 (AQ-4/5) | F-DG-01 (R12) — обходы hard-check по типам (Decimal → datetime, строки) |
| FA-030/FA-032 (AQ-6/8) | F-DG-03 (R12) — классификация по имени колонки |
| FA-036 (S-07/RES-7) | F-SCHED-05 (R8) — отсутствие cross-process single-flight |
| FA-039 (RES-5) | F-KNOW-07 (R7) — молчаливая деградация knowledge-контура |
| FA-040 (RES-6) | CB-M5 (R11) — silent error swallowing (здесь: уровни логирования) |
| FA-062/FA-122 | F-PROJ-13 (R10) — отсутствие pagination cap |
| FA-081 (B4) | R1 (закрыт `50ce7c8`) — остаточный пробел в слое SafetyGuard (коннекторный гард закрывает) |
| FA-085/FA-086 (AQ-10/11) | xfail DATA-15 / DATA-21 — задокументированные ограничения, подтверждены |
| FA-114 | F-BILL-03 (R9) — webhook без лимита (здесь: осознанность решения) |

**Остальные ~125 находок — NEW**, не представленные в issues.md: весь контур 01 (осиротевшие эндпоинты/сценарии, API.md-дрейф), 03 (UX), 04 (живые баги), 05 (кросс-БД), 06 (AQ-3..6, AQ-8..16), 07 (CVE, конфиги), 08 (resilience), 09 (performance).

---

## Топ приоритетов исправления

### P0 — немедленно (8 находок)

| ID | Что | Обоснование |
|---|---|---|
| **FA-001** | MongoDB connector `if not self._db` → `is None` ×5 | Единственная CRITICAL: целый класс подключений неработоспособен в проде (любой Mongo-коннект = 500). Фикс тривиален, тесты маскируют — добавить тест с реальным motor-объектом или `__bool__`-spy. |
| **FA-002** | AQ-1: идемпотентность негативного feedback | Любой viewer (или double-click) разрушает общий корпус learnings и накачивает мусорный ★CRITICAL-урок. Прямое влияние на качество агента для всех пользователей подключения. Фикс по образцу позитивного пути (`learning_credited_at_validation`). |
| **FA-003** | AQ-2: prompt-injection → персистентное отравление | Crafted-значение в БД клиента → долгоживущий poisoned learning с авторитетным framing. Security-воздействие на все запросы соединения; не требует доступа злоумышленника к приложению — только к данным. |
| **FA-004** | git-SSRF: denylist loopback/private/metadata в `validate_repo_url` | Подтверждён двумя независимыми фазами; в shared/cloud-хостинге — доступ к metadata-endpoint и внутренней сети. Прямая security-дыра с аутентифицированным доступом. |
| **FA-005** | Next.js ≥ patched (GHSA-ggv3-7p47-pfv8) | Request smuggling в prod-зависимости; фикс доступен (`npm audit fix`). |
| **FA-007** | RES-1: ложный reap необратим | Живая успешная индексация навсегда помечается failed; UI-противоречие; пользовательский trust-домен. Фикс: не отбрасывать `pipeline_end` для reap'нутых run (или re-activate при событии). |
| **FA-008** | RES-2: heartbeat внутри долгих шагов | Прямой триггер FA-007 на реальных больших репозиториях (CPU-bound ONNX embed >300с — типично). Фикс: периодический tick внутри шагов или снапшот-прогресс. |
| **FA-010** | 401: видимое объяснение истечения сессии | Самый частый auth-инцидент у пользователя — сейчас внезапная перезагрузка без причины. Фикс дешёвый: `/login?reason=session_expired` + сообщение, либо персистентный тост. |

### P1 — ближайший релиз (9 находок)

| ID | Что | Обоснование |
|---|---|---|
| FA-006 | Сильный `JWT_SECRET` + явный `ENVIRONMENT` в `.env.local`; fail-fast проверка для docker-compose | Дефолтный секрет + debug в реальном развёртывании = компрометация всех сессий. Пара с FA-033. |
| FA-033 | `environment` обязательным / дефолт `"production"` (fail-closed) | Заявленный fail-closed подорван дефолтом pydantic; корневая причина класса «пропущенные prod-проверки секретов». |
| FA-034 | Обновить gitpython→3.1.51, mcp→1.28.1, pyasn1→0.6.4 | CVE с доступными фиксами в backend-зависимостях (git-контур, MCP-контур). |
| FA-009 | RES-3: heartbeat на post-index шагах / guard против duplicate dispatch | Двойной расход LLM и гонки записи в ChromaDB — деньги и консистентность. |
| FA-011 | ClickHouse: пересоздание клиента/`KILL QUERY` на TimeoutError | Коннектор клинит на минуты после любого таймаута + молчаливая деградация индекса схемы. |
| FA-013 | Стартовый алерт при prod без `REDIS_URL` + runbook-проверка | Тихая деградация prod: индексация на web-dyno, shutdown обрывает runs. Код к ARQ готов — нужен сигнал. |
| FA-012 | Консолидация gsap+lenis → motion | −90 KB gzip с маркетинга, ~−60 KB с `/app`; убирает и утечку чанков через manifest. Прямое влияние на всех холодных визитов. |
| FA-017 | `@limiter.limit` на `/api/checkout`, `/api/portal` | Спам Stripe-сессиями без ограничения — денежный контур. |
| FA-027 | AQ-3: детерминистический block на flat-пути | Самый частый путь агента защищён только instruction-following; в связке с FA-003 (инъекция перебивает маркер) — реальный канал «невозможных чисел» в ответе. |

### P2 — плановый бэклог (остальные)

- **Документационный долг (один проход):** FA-014..FA-016, FA-058, FA-059, FA-080, FA-111, FA-116, FA-131 — синхронизация API.md/CLAUDE.md/scenarios.md с кодом; заодно FA-052 (дописать SCN на notifications и выбор модели).
- **DataGate-кластер:** FA-028..FA-030, FA-032, FA-084..FA-086 — слить с планом R12 (issues.md F-DG-*), закрывает и пробелы покрытия веток.
- **Learnings-кластер:** FA-031, FA-087, FA-089, FA-090 — слить с R6.
- **Rate-limit добивка:** FA-054..FA-056 (+FA-036 — Redis в prod, см. P1 FA-013).
- **Resilience-гигиена:** FA-038..FA-041, FA-097..FA-100 — уровни логов, lazy VectorStore, сигналы деградации.
- **Performance-заказы:** FA-042..FA-048, FA-104..FA-109 (индексы одной миграцией), FA-101..FA-103.
- **UX Low-пакет:** FA-064..FA-078 (3 PARTIAL-сценария + косметика), FA-020..FA-024.
- **Security Low/Info:** FA-092..FA-096, FA-112..FA-115, FA-118, FA-119, FA-137 — с плановыми релизами R4/R5/R9/R11.
- **Observability:** FA-079, FA-100 (живостная LLM-проверка), FA-135 (заменить ключ и повторить золотой путь — см. ограничения).

---

## Позитивные подтверждения (проверено и НЕ сломано)

**Тестовая база (00):** 5439 backend + 526 frontend тестов зелёные (0 failed), coverage 77.74% (gate 72%), ruff/format/mypy чисто; все skip/xfail обоснованы.

**Авторизация и контракты (01/02/04):** все 96 project/connection-scoped эндпоинтов имеют membership-проверки (построчная проверка); вложенные ресурсы сверяются с родителем; критичных пропусков авторизации не найдено. Tenant isolation живьём: 6/6 проб чужим токеном → 403 без утечек. Rate limit: 429 ровно на пороге. Ошибок 500 за весь live-прогон не было; ошибки подключений возвращаются graceful (`success:false`). Всё, описанное в API.md, существует в коде (нет «мёртвых» описаний). SafetyGuard применяется на всех raw-SQL entry points.

**UX (03):** 109/112 сценариев PASS, 0 FAIL; ролевая модель (owner/editor/viewer) соответствует везде, кроме одной находки (FA-023); мобильный viewport (единый breakpoint, drawer, touch-цели 44px с глобальной страховкой) и prefers-reduced-motion (включая маркетинг GSAP/Lenis-гейты и noscript-фолбэк) — полное соответствие; billing 402 → кликабельный `/pricing` в тосте подтверждён; все 6 задокументированных GAP'ов подтверждены кодом (документация честна).

**Живые потоки (04):** регистрация/логин/негатив, проекты, подключение, индексация схемы (2 таблицы + FK за ~6с), notes, batch (результаты сходятся с сидом), visualizations render/export (CSV/XLSX), feedback, SSE-протокол (полная последовательность событий, корректное завершение, ошибка LLM доставлена in-band по контракту). LLM-полный-отказ — graceful: fail-fast 0.49с, user-friendly ответ, трейс сохранён.

**Кросс-БД (05):** read-only enforcement подтверждён живьём на всех трёх СУБД на двух слоях (MySQL `SET SESSION TRANSACTION READ ONLY` → ошибка 1792 на все 6 типов записи; CH `readonly=1` → Code 164; Mongo — app-гард + отсутствие write-путей в принципе); данные целы после всех попыток записи; кап 10000 строк + `truncated` работает; таймауты запросов ограничены (1с) и MySQL/Mongo после таймаута здоровы; Unicode/CJK/emoji/NULL/decimal/даты — корректный round-trip; SafetyGuard-матрица (DML/DDL/multi-statement/комментарии/INTO OUTFILE) блокирует корректно.

**Агентные гейты (06):** retrieval eval gate 18/18 в CI (пороги, golden-set, харнес валидны); decision table ResultValidation корректна на обоих путях (96.4% coverage); AnswerValidator fail-closed по умолчанию — честная деградация; orchestrator termination (step budget, emergency synthesis, wall-clock cutoff) и replan-limits (2 replan, anti-oscillation, dangling-deps) покрыты тестами; позитивное кредитование learnings идемпотентно; suspicious-результаты не кредитуются; tenant isolation global patterns — fail closed.

**Security (07):** JWT (HS256 whitelist алгоритма), cookies (HttpOnly+CSRF double-submit, Secure, SameSite), brute-force (лимиты на всех auth-эндпоинтах + timing-equalization), bcrypt 12, Google OAuth (audience/nonce/CSRF), password reset (SHA-256, 1ч, одноразовый, revoke сессий) — безопасны; закоммиченных секретов нет; заголовки безопасности в порядке (CSP enforce, HSTS); SSH/MCP контур подтверждён.

**Resilience (08):** миграции — полный round-trip 75/75 head⇄base на SQLite зелёный; reaper идемпотентен (6/6 тестов); БД при старте — fail-fast (3 ретрая, нет половинчатого состояния); Redis-отсутствие на single-dyno — все fallback корректны с WARNING-логами; фоновые циклы переживают крах итерации; streaming error path (трейс/статус сессии/SSE-ошибка) корректен.

**Performance (09):** классического N+1 в горячих сервисах нет (IN-батчинг, selectinload, SQL-агрегации); история чата ограничена на SQL-уровне; горячие пути логов/learnings/db_index покрыты индексами; фронтенд: 7 вторичных панелей через `dynamic(ssr:false)`, chart.js и react-markdown — lazy.

---

## Ограничения аудита

1. **Мёртвые LLM-ключи (E1/FA-135):** `OPENROUTER_API_KEY` невалиден (401), OPENAI/ANTHROPIC пусты → **золотой путь агента (оркестратор → SQLAgent → execution → численный ответ) живьём не проверен**. Потоки 5/6/13 в 04 проверены только по graceful-degradation пути; фаза 06 выполнена статикой + детерминистическими прогонами. Требуется: валидный ключ и повтор потоков 5, 6, 13.
2. **Браузерный E2E не автоматизирован:** верификация 112 сценариев (03) — статический анализ кода; RUM-метрик (LCP/INP) нет; выводы о bundle основаны на размерах чанков и script-тегах prerendered HTML (09).
3. **Нагрузочное тестирование не проводилось:** оценки конкурентности (~10–15 agent-run на dyno, пул 5+10) — статические, из конфигурации; CPU/память backend под нагрузкой не профилировались.
4. **Prod Heroku конфигурация не проверена:** наличие `REDIS_URL`, размер dyno, фактический `ENVIRONMENT`/`JWT_SECRET` в проде из репозитория не видны — FA-006, FA-013, FA-033, FA-036, FA-143 требуют ручной проверки прод-окружения.
5. **MongoDB-результаты 05 получены с monkeypatch-обходом FA-001** (`AsyncIOMotorDatabase.__bool__` в тестовом процессе) — до фикса коннектора повторить на честном коде.
6. **PG trust-auth в локальном окружении:** кейс «неверный пароль» недостижим (04) — проверены эквивалентные отказы (несуществующая БД, закрытый порт).
7. **Статические фазы без запуска:** 01, 02, 03 — только Read/Grep/Glob; MCP session manager при `mcp_enabled=True` живьём не проверялся (08); code_graph benchmark не запускался (06).
