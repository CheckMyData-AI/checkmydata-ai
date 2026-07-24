# 09 — Производительность (Фаза 3.6)

Дата: 2026-07-24
Исполнитель: автоматизированный агент (статический анализ + production build фронтенда)
Границы: живые тайминги API не повторялись — база взята из `04-e2e-live.md` (CRUD 2–13 мс, connection-test fail-port 3.01 s, index-db 2 таблицы ~6 s из них 5.4 s `store_results`, batch 0.6 s). Файлы репозитория не изменялись; единственная запись — `frontend/.next` (gitignored) от `npm run build`.

## Краткая сводка

| Область | Статус | Главное |
|---------|--------|---------|
| Frontend bundle | ⚠️ | `/app` First Load 353 kB, `/` 287 kB; три анимационные библиотеки (gsap+lenis+motion); remark-gfm ломает lazy-границу react-markdown |
| Backend SQL | ⚠️ | N+1 как такового почти нет, но COUNT/LIMIT/фильтрация делаются в Python после полной выборки в трёх сервисах |
| Индексы БД | ⚠️ | горячие пути частично покрыты; не хватает 4–5 композитных индексов для PostgreSQL-масштаба |
| Конкурентность | ⚠️ | 1 uvicorn-процесс на dyno; per-user cap 3; пул БД 5+10; in-process queue без Redis — главный prod-риск |
| 512 MB dyno | ℹ️ | ONNX MiniLM 384-dim вместо bge, reranker no-op — осознанная деградация retrieval (CHANGELOG 1.15.1) |

---

## 1. Frontend bundle

### 1.1. Вывод `next build` (Next.js 15.5.12, 16 статических страниц, компиляция 7.2 s)

| Route | Size | First Load JS |
|-------|------|---------------|
| `/` (marketing) | 6.1 kB | **287 kB** |
| `/app` (продукт) | 112 kB | **353 kB** |
| `/dashboard/[id]` (ƒ dynamic) | 2.9 kB | 203 kB |
| `/login` | 5.12 kB | 200 kB |
| `/pricing` | 2.09 kB | 195 kB |
| `/about`, `/contact`, `/privacy`, `/support`, `/terms` | 793 B | 186 kB |
| auth-страницы (forgot/reset/verify) | 4.3–4.7 kB | 195–199 kB |
| Shared by all | — | 183 kB (`101` 126 kB + `4bd1` 54.2 kB + 3.29 kB) |

### 1.2. Реальный состав чанков (измерено по `.next/static/chunks`, gzip)

| Чанк | gzip | Содержимое | Кто тянет |
|------|------|-----------|-----------|
| `101-…js` | 122 KB | Next runtime + **Sentry SDK** | все страницы (shared) |
| `4bd1…js` | 54 KB | React DOM | все страницы (shared) |
| `674` + `c15bf2b0` | 24+19 = **43 KB** | **gsap + ScrollTrigger** | marketing layout → все marketing-страницы; фактически и `/app` (см. 1.3) |
| `133-…js` | 41 KB | **motion** (framer) | `/` (FaqAccordion) и `/app` (MotionConfig, ChatPanel, StageRow) |
| `(marketing)/layout-…js` | ~6 KB | **lenis** (SmoothScroll) | все marketing-страницы |
| `848-…js` | 28 KB | micromark/remark-gfm | `/app` — **eager**, не lazy (см. F-2) |
| `ca377847…js` | 48 KB | chart.js | lazy (async chunk) — корректно |
| `912-…js` | 32 KB | react-markdown | lazy (async chunk) — корректно, но частично обесценено (F-2) |
| `app/app/page-…js` | 81 KB | монолит `/app` (Sidebar+ChatPanel+ProjectOverview+SettingsPanel+ConnectionsPanel) | `/app` |

### 1.3. Эмпирическая проверка script-тегов (prerendered HTML)

Метрика First Load из build-вывода **занижает** реальную первую загрузку: проверка `<script src>` в `<head>` сгенерированных HTML показала:

- `/about` (текстовая страница, метрика 186 kB) фактически грузит gsap-чанки (43 KB gzip) и lenis-чанк — итого **~235 kB gzip**. Причина: `SmoothScroll` в `(marketing)/layout.tsx:4,58` статически импортирует gsap/ScrollTrigger/lenis, поэтому даже текстовые страницы (privacy/terms) получают весь анимационный стек.
- `/app` (метрика 353 kB) фактически грузит в `<head>` также **gsap-чанки (43 KB gzip) и чанк marketing-главной `(marketing)/page-…js` (18 KB raw)**, которые роут не использует. Подтверждено `app/page_client-reference-manifest.js`: в манифест клиентских ссылок `/app` попали все marketing-модули (общий root-layout для route-group `(marketing)` и `/app`). Реальная первая загрузка `/app` ≈ **400 kB gzip**.

### 1.4. Ленивая загрузка — что уже сделано хорошо

- `app/app/page.tsx:16-47`: семь вторичных панелей через `dynamic(ssr:false)` — LogPanel, NotesPanel, ReasoningPanel, ActiveTasksWidget, OnboardingWizard, BatchRunner, **LogsScreen** — в initial bundle не попадают.
- `VizRenderer.tsx:6`: ChartRenderer (chart.js) lazy.
- ReactMarkdown lazy в ChatMessage/ChatPanel/SQLExplainer.

### 1.5. Находки фронтенда

**F-1 (High) — Три анимационные библиотеки, gsap+lenis на всех marketing-страницах.**
`gsap` импортируется только в `lib/motion/gsap.ts` (используется DataStory/WordLight/CountUp/SmoothScroll), `lenis` — только в `SmoothScroll.tsx:4`, `motion` — в 4 компонентах. Дублирующая функциональность: smooth-scroll (lenis) и scroll-triggered анимации (gsap ScrollTrigger) покрываются `motion` (useScroll/useInView), который уже загружается и на `/`, и на `/app`. Консолидация на motion: **−43 KB gzip gsap, −6 KB lenis с каждой marketing-страницы** (текстовые: ~235→186 kB), с `/` −~90 KB gzip; заодно уходит утечка gsap в `/app` (механизм — общий root-layout manifest, см. 1.3).

**F-2 (Medium) — Статический импорт `remark-gfm` обесценивает lazy-границу react-markdown.**
`react-markdown` обёрнут в `dynamic()`, но `remark-gfm` импортирован статически: `components/chat/ChatMessage.tsx:6`, `components/chat/SQLExplainer.tsx:5`. ChatPanel статически входит в `/app` → micromark/gfm-дерево (чанк `848`, **28 KB gzip**) грузится eager. Рекомендация: передавать `remarkGfm` внутрь lazy-компонента (импорт рядом с `ReactMarkdown` в динамической обёртке). Эффект: 353→~325 kB First Load `/app`.

**F-3 (Low) — Sentry в shared-чанке для всех страниц (включая marketing).**
`101-…js` (122 KB gzip) содержит Next runtime + Sentry SDK; @sentry/nextjs интегрирован через `withSentryConfig` (`next.config.ts:66`). Точная доля Sentry ~15–25 KB gzip. Для marketing-трафика (SEO, холодные визиты) это мёртвый вес; изъятие требует отказа от автоинтеграции в пользу ленивой инициализации — соотношение цена/эффект низкое. Зафиксировано как принятое.

**F-4 (Low) — `next.config.ts` без bundle-оптимизаций.**
Нет `experimental.optimizePackageImports` (для `zod`, `chart.js`, `motion` в Next 15 список по умолчанию не покрывает), нет `modularizeImports`. Побочно: warning о двух lockfiles (`/Users/sshlg/package-lock.json` vs `frontend/package-lock.json`) — Next неверно выводит workspace root; чинится `outputFileTracingRoot` и влияет на корректность standalone-трейсинга (размер Docker-образа).

**F-5 (Low) — `msw` — мёртвая devDependency.**
`package.json:49`, использований в `src/` нет (grep — 0 совпадений). Удалить.

**Сводный потенциал снижения First Load JS:**
- `/`: 287 → ~200 kB (−30%) — консолидация анимаций на motion.
- текстовые marketing: ~235 → ~186 kB (−21%) — то же.
- `/app`: ~400 (факт) → ~325 kB gzip (−19%) — remark-gfm в lazy + устранение утечки gsap/marketing-чанка (консолидация стека или разделение root-layout'ов для `(marketing)` и продукта).

---

## 2. Backend: N+1 и горячие запросы (статически)

Классического N+1 (await в цикле по строкам) в горячих сервисах **не обнаружено**: `project_overview_service` батчит через `IN(connection_ids)`, `logs_service` использует `selectinload(RequestTrace.spans)` (`logs_service.py:141`) и SQL-агрегации, список проектов — `get_roles_bulk` (`projects.py:220`). Основной дефект иной: **LIMIT/COUNT/фильтрация выполняются в Python после полной материализации выборки**.

**P-1 (Medium) — COUNT через полную материализацию четырёх store'ов.**
`knowledge_catalog_service.py:595-637` (`_artifact_counts`, эндпоинт knowledge_health): `counts["tables"] = len(await DbIndexService().get_index(...))`, аналогично sync/learnings/insights — загружаются все ORM-строки (включая Text-поля `business_description`, `lesson`, JSON-колонки), чтобы посчитать `len()`. Для подключения с 1000 таблиц это тысячи ORM-объектов на каждый запрос health-виджета. Рекомендация: `select(func.count())` с теми же фильтрами.

**P-2 (Medium) — LIMIT в Python: `get_index` без SQL-лимита.**
`db_index_service.py:55-65` — `get_index` возвращает все строки подключения; `knowledge_catalog_service.py:290` режет `rows[:limit]` после выборки. ContextPack собирается на каждый chat-запрос (категория TABLES) — на больших схемах это доминирующая стоимость контекстной сборки. Рекомендация: опциональный `limit` в `get_index` с push-down в SQL (ORDER BY relevance_score уже там).

**P-3 (Medium) — `get_learnings`: limit и table_filter в Python.**
`agent_learning_service.py:631-653`: `result.scalars().all()` → фильтрация blocklist/table_filter подстрокой → срез `rows[:limit]`. Горячий путь: `get_prompt_learnings` (`:893-897`) вызывается при пересборке compiled prompt — грузит все learnings подключения (min_confidence=0.5) и сортирует в Python (`:896`), затем берёт 30. Смягчение: результат кэшируется в `AgentLearningSummary.compiled_prompt` (`:964-985`), пересборка только при инвалидации — поэтому severity не High. Рекомендация: SQL `LIMIT` + `ilike` для table_filter.

**P-4 (Low-Medium) — `decay_stale_learnings`: full-scan + поштучные апдейты + N+1 инвалидация.**
`agent_learning_service.py:1239-1245` — выборка ВСЕХ stale learnings всех подключений без лимита/батчинга; `:1254-1266` — поштучное изменение через ORM вместо одного `UPDATE`; `:1270-1271` — цикл `_invalidate_summary` по affected connections (1 запрос на подключение — N+1). Фоновая джоба (не API), но на PG-масштабе (десятки тысяч learnings) — долгая транзакция с тысячами row-локов. Рекомендация: один `UPDATE ... WHERE is_active AND updated_at < cutoff` с `CASE` по penalty + `UPDATE agent_learning_summaries ... WHERE connection_id IN (subquery)`; индекс `(is_active, updated_at)` (см. раздел 3).

**P-5 (Low-Medium) — Блокирующий `vector_store.query` на event loop при выключенном hybrid.**
`VectorStore.query` синхронный (`vector_store.py:161-176`, Chroma + ONNX-инференс внутри). Hybrid-путь чист (`hybrid_retriever.py:181,200` — `asyncio.to_thread`), но fallback при `hybrid_retrieval_enabled=false` вызывает его напрямую из async-кода: `knowledge_catalog_service.py:539`, `context_loader.py:377`. Каждый вызов — десятки мс блокировки цикла. Рекомендация: обернуть оба call-site в `asyncio.to_thread`.

**P-6 (Low) — `list_requests` тянет все колонки RequestTrace.**
`logs_service.py:77` — `select(RequestTrace)` для списочной выдачи из 19 полей; Text-поля `question`/`error_message` едут по сети и материализуются зря на каждой странице логов. Рекомендация: select нужных колонок.

**P-7 (Info, подтверждено живьём) — 3.01 s на мёртвом порту connection-test.**
`connection_service.py:273-277`: `@retry(max_attempts=3, backoff_seconds=1.0)` на connect — 3 попытки ≈ 3 s. Соответствует замеру из 04-e2e-live. By design, но фронту стоит показывать прогресс.

**Позитив:** история чата ограничена на уровне SQL (`chat_service.py:157-163`, `history_db_load_limit=20`, `config.py:324`); `logs_service` везде пагинирован; `project_overview_service` использует SQL `LIMIT` (`:272`) и IN-батчинг; `test_connection` не пробрасывает 500.

---

## 3. Индексы БД vs горячие пути

Покрыто хорошо: `request_traces(project_id, created_at)` и `(user_id, created_at)` + `workflow_id` (`request_trace.py:67-70`) — путь логов; `chat_messages.session_id` (`chat_session.py:54`); `agent_learnings.connection_id` + unique `(connection_id, category, subject, lesson_hash)` (`agent_learning.py:29-37`) — покрывает `find_similar`/`_resolve_conflicts`; `db_index` unique `(connection_id, table_schema, table_name)` покрывает лукапы по connection_id; `error_log`, `query_failures`, `indexing_runs`, `trace_spans(trace_id, order_index)` — осмысленные композиты.

**Отсутствующие индексы (SQLite dev прощает, PostgreSQL prod — нет):**

| # | Индекс | Горячий путь | Severity |
|---|--------|--------------|----------|
| I-1 | `chat_messages(session_id, created_at DESC, id DESC)` | каждый chat-запрос: последние 20 сообщений (`chat_service.py:158-163`) — сейчас sort после index-scan по session_id | Medium |
| I-2 | `agent_learnings(connection_id, is_active, confidence DESC, times_confirmed DESC)` | compile prompt (`agent_learning_service.py:631-642`) — filter+sort в памяти PG | Medium |
| I-3 | `notifications(user_id, is_read, created_at DESC)` | бейдж непрочитанных (polling с фронта); `user_id` и `project_id` индексированы по отдельности (`notification.py:15,18`), `is_read` — нет | Medium |
| I-4 | `request_traces.session_id` (FK) | лукапы трейсов по сессии; плюс PG не строит индексы по FK автоматически — `ON DELETE SET NULL` из `chat_sessions` сделает seq-scan по request_traces (`request_trace.py:28-32`) | Low-Medium |
| I-5 | `agent_learnings(is_active, updated_at)` | decay-джоба full-scan (P-4) | Low |
| I-6 | `request_traces.message_id` (FK, SET NULL) — аналогично I-4 | Low |

Дополнительно: FK-колонки без индекса опасны ещё и каскадами — `ON DELETE CASCADE`/`SET NULL` по неиндексированному FK на PG берёт row-локи с полным сканом дочерней таблицы.

---

## 4. Конкурентность

### 4.1. Конфигурация (факт)

- **Процессная модель:** `Procfile` — `web: uvicorn app.main:app` **без `--workers`** → 1 процесс = 1 event loop на dyno; `worker: arq app.worker.WorkerSettings` (heroku.yml подтверждает оба).
- **Пер-user лимиты агента:** `max_concurrent_agent_calls=3`, `max_agent_calls_per_hour=100` (`config.py:580-581`), `agent_limiter` — Redis Lua (cross-process, T-SCALE-1) при наличии `REDIS_URL`, иначе in-memory per-process (`agent_limiter.py:96-120`).
- **HTTP rate limit:** `chat/ask` и `ask/stream` — 20/min per IP (slowapi, `chat.py:213,576`, `rate_limit.py:39-40`).
- **Внутренние семафоры:** `max_parallel_tool_calls=2` на инстанс оркестратора (`orchestrator.py:242`); `pipeline_max_parallel_stages=3` (`stage_executor.py:189`); `batch_max_concurrency=4` (`batch_service.py:247`); индексация: LLM-sem 3, sample-sem 5 (`db_index_pipeline.py:426,750`).
- **Пул БД приложения:** `db_pool_size=5`, `max_overflow=10` → максимум 15 соединений (`config.py:69-72`, `base.py:20-24`), `pool_timeout=30 s`.

### 4.2. Оценка пропускной способности одного dyno (Standard-1X, 1 vCPU shared, 512 MB)

Chat-запрос — преимущественно I/O-ожидание (LLM round-trips секунды, SQL-к целевой БД), CPU на запрос мал. Event loop физически удержит десятки одновременных SSE/ask-сессий. Реальные потолки по порядку срабатывания:

1. **Per-user cap 3** — один пользователь не запустит больше трёх agent-run; многопользовательская нагрузка лимитом не сдерживается.
2. **Пул БД 5+10=15** — каждый активный agent-run держит сессию приложения (persist trace, learnings, context) периодически; при >~10–15 одновременных run'ах, активно пишущих в БД, запросы встанут в очередь пула и начнут падать по `pool_timeout=30 s`. **Практический потолок: ~10–15 одновременных chat-run'ов на dyno** (при условии, что целевые БД и LLM выдерживают).
3. **Память 512 MB** — каждый SSE-стрим + контекстная сборка (ContextPack, история) + Chroma PersistentClient + ONNX runtime в том же процессе; при параллельной индексации (см. 4.3) потолок ниже.

Tool-level параллелизм (`=2`/`=3`) на пропускную способность dyno не влияет — он ограничивает fan-out внутри одного run'а (защита целевых БД и LLM rate-limits), а не число одновременных run'ов.

### 4.3. In-process task queue — главный prod-риск

Механика: `task_queue.py:21-40` — без `REDIS_URL` очередь молча деградирует в `asyncio.create_task` **в web-процессе** (лог одной строкой INFO). Тогда DB-индексация (`connections.py:117-121`), code↔DB sync (`:185-187`), repo-index и embedding-reindex выполняются на том же event loop / vCPU / 512 MB, что и API:

- **CPU:** пайплайн обильно обёрнут в `asyncio.to_thread` (pipeline_runner — десятки вызовов; BM25 build `pipeline_runner.py:1290`; AST-parse с семафором 4 `:1467`), поэтому event loop не блокируется надолго, но треды делят тот же 1 vCPU — API-латентность деградирует на время индексации (замер: 2 таблицы ~6 s; реальная БД — минуты-десятки минут).
- **RAM:** Chroma PersistentClient + ONNX + repo-клон + AST-граф в одном 512 MB процессе — риск R14 (memory quota) на Heroku.
- **Shutdown:** `close_task_queue` отменяет fallback-таски (`task_queue.py:53-62`) — деплой/рестарт dyno обрывает in-flight индексацию (run остаётся `running` до heartbeat-recovery).
- **Лимиты:** in-memory `agent_limiter` на 2+ web-dyno фактически умножает cap на число dyno.

**Вывод:** `REDIS_URL` + worker-dyno для прода — обязательное требование (код к нему готов: dispatch через `is_arq_active()`, `connections.py:106`). Риск именно в **тихом fallback'е**: отсутствие аддона Redis превращается не в алерт, а в скрытую деградацию. Рекомендация: стартовый WARNING уровня ERROR/алерт при `ENV=production` и отсутствующем `REDIS_URL`; в runbook — проверка `Task queue: ARQ connected to Redis` в логах деплоя.

---

## 5. Prod-ограничения 512 MB dyno (зафиксировано)

Из CHANGELOG 1.15.1 (deploy notes): prod — Heroku **Standard-1X (512 MB)** web+worker. `BAAI/bge-base-en-v1.5` (768-dim) и cross-encoder reranker требуют `sentence-transformers`+`torch`, что не помещается в 512 MB (OOM на загрузке). Поэтому:

- **Эмбеддинги:** ChromaDB built-in ONNX `all-MiniLM-L6-v2` (384-dim) вместо сконфигурированного bge (`vector_store._get_embedding_function` деградирует с одиночным WARNING). Индекс и запрос самосогласованы (одна модель), но **потолок качества dense-retrieval ниже** задуманного (MiniLM 384-dim vs bge 768-dim).
- **Reranker:** `reranker_enabled=true` (дефолт с 1.15.0), но в prod — **no-op** (graceful, `reranker.py`). Вторая стадия переранжирования гибридного retrieval фактически не работает → precision@k ниже эталона retrieval-eval (который гонялся с reranker).
- **Совокупно:** hybrid retrieval (BM25 + dense MiniLM + RRF) функционален, но два из трёх качественных усилителей 1.15.0 (bge, rerank) в проде выключены инфраструктурно.
- **Путь включения (3 шага из CHANGELOG):** (1) web+worker → ≥1 GB (Standard-2X/Performance-M), (2) `sentence-transformers` в `Dockerfile.backend`/`Dockerfile.worker`, (3) полный reindex (`queue_embedding_reindex`) + продвижение embedding-fingerprint, чтобы 768-dim векторы заменили 384-dim.
- Побочно: 512 MB же ограничивает и 4.3 — code_graph indexing (CPU-heavy, рекомендация CHANGELOG ≥2 cores на worker) на Standard-1X выполняется медленнее и с риском memory pressure.

---

## Сводная таблица находок

| ID | Severity | Локация | Суть | Рекомендация | Оценка эффекта |
|----|----------|---------|------|--------------|----------------|
| F-1 | High | `(marketing)/layout.tsx:4`, `lib/motion/gsap.ts` | gsap+lenis+motion дублируются; gsap/lenis на всех marketing-страницах и (через manifest) в `/app` | консолидация на motion; SmoothScroll → useScroll | −90 KB gzip на `/`, −49 KB на текстовых marketing, ~−60 KB на `/app` |
| F-2 | Medium | `ChatMessage.tsx:6`, `SQLExplainer.tsx:5` | remark-gfm static → 28 KB gzip eager в `/app` | импорт плагина внутри lazy-обёртки | −28 KB gzip First Load `/app` |
| F-3 | Low | `next.config.ts:66` | Sentry в shared chunk для всех | принять или lazy-init Sentry | ~15–25 KB gzip (дорого в исполнении) |
| F-4 | Low | `next.config.ts` | нет optimizePackageImports; двойной lockfile путает tracing root | добавить `optimizePackageImports`, `outputFileTracingRoot` | точность standalone-образа |
| F-5 | Low | `package.json:49` | msw не используется | удалить devDependency | гигиена |
| P-1 | Medium | `knowledge_catalog_service.py:595-637` | COUNT через полную материализацию 4 store'ов | `select(func.count())` | O(rows)→O(1) память на health-запрос |
| P-2 | Medium | `db_index_service.py:55-65` + `knowledge_catalog_service.py:290` | LIMIT в Python | limit push-down в SQL | критично на схемах 500+ таблиц |
| P-3 | Medium | `agent_learning_service.py:631-653,896` | limit/filter/sort learnings в Python | SQL LIMIT + ilike | горячий путь prompt-compile |
| P-4 | Low-Medium | `agent_learning_service.py:1239-1271` | decay: full-scan, поштучные апдейты, N+1 инвалидация | bulk UPDATE + IN-подзапрос | фоновая джоба, PG-масштаб |
| P-5 | Low-Medium | `knowledge_catalog_service.py:539`, `context_loader.py:377` | sync Chroma+ONNX вызов на event loop (hybrid off) | `asyncio.to_thread` | десятки мс блокировки на запрос |
| P-6 | Low | `logs_service.py:77` | select всех колонок в списке трейсов | select нужных колонок | трафик/память на страницу логов |
| I-1..I-6 | Low-Medium | см. раздел 3 | недостающие композитные индексы | alembic-миграция с `Index(...)` | предотвращает sort/seq-scan на PG |
| C-1 | High (prod-риск) | `task_queue.py:26`, `connections.py:117` | тихий in-process fallback очереди без Redis | алерт при prod без REDIS_URL; runbook-проверка | API-латентность и RAM web-dyno под индексацией |
| C-2 | Info | `config.py:69-72` | пул 5+10=15 — потолок ~10–15 одновременных agent-run на dyno | мониторинг pool checkout; масштабировать dyno раньше, чем пул | capacity planning |
| R-1 | Info (принято) | CHANGELOG 1.15.1 | MiniLM вместо bge, reranker no-op на 512 MB | апгрейд dyno ≥1 GB + reindex (3 шага) | качество retrieval в prod |

## Что не проверялось

- Реальные browser-метрики (LCP/INP) — нет RUM-данных; выводы по bundle основаны на размерах чанков и script-тегах.
- Профилирование CPU/памяти backend под нагрузкой (только статический анализ + тайминги из 04-e2e-live).
- Наличие `REDIS_URL` в фактическом prod-окружении Heroku — из репозитория не видно; пункт для ручной проверки (см. C-1).
