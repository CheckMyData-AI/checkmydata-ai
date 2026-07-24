# 08 — Устойчивость и chaos-аудит (Фаза 3.5)

Дата: 2026-07-24. Область: миграции (round-trip), reaper/heartbeat, деградация
внешних зависимостей (ChromaDB / Redis / LLM / БД), startup-resilience,
silent-failure в worker, runbook-риски. Метод: живой round-trip миграций на
scratch-БД в `/tmp`, статический ревью кода, прогон существующих юнит-тестов.
LLM-токены не тратились. `backend/data/agent.db` не трогали.

## Сводная таблица проверок

| # | Проверка | Результат | Evidence |
|---|----------|-----------|----------|
| 1.1 | `alembic upgrade head` с нуля (SQLite) | PASS | 75 миграций, head=`e7f8a9b0c1d2`, scratch `/tmp/mig_test.db` |
| 1.2 | `downgrade -1` → `upgrade head` | PASS | `e7f8a9b0c1d2`→`d5e6f7a8b9c0`→обратно, без ошибок |
| 1.3 | `downgrade -3` → `upgrade head` | PASS | до `0e5084fdfb86` и обратно, без ошибок |
| 1.4 | Полный `downgrade base` → `upgrade head` (сверх плана) | PASS | вся цепочка из 75 downgrade работает; batch mode для SQLite используется корректно, unsupported ALTER не встретился |
| 1.5 | Scratch-БД удалена после прогона | PASS | `/tmp/mig_test.db` удалён |
| 2.1 | Heartbeat покрывает долгие участки summary-таблиц | PASS | писатели каждые 30с: `db_index_pipeline.py:327`, `code_db_sync_pipeline.py:74`, `repos.py:559`, `daily_knowledge_sync_service.py:140` |
| 2.2 | Heartbeat IndexingRun на долгих шагах pipeline | RISK | тики только на границах шагов/emit'ах (`run_coordinator.py:422,427`); шаги >300с без emit'ов → live-reap |
| 2.3 | Восстановление run после ложного reap | FAIL | `_on_event` отбрасывает события терминальных run (`run_coordinator.py:371`) → фантомный `failed` навсегда |
| 2.4 | Гонка reaper ↔ живой worker (duplicate dispatch) | RISK | guard'ы читают статус из БД (`connections.py:207,253`); после flip → второй параллельный запуск возможен |
| 2.5 | Reaper unit-тесты | PASS | `tests/unit/test_stale_run_reaper.py` — 6 passed |
| 3.1 | ChromaDB недоступна/пуста — деградация retrieval | RISK | retrieval обёрнут и возвращает `[]`, но `has_knowledge_base` молча `False` без лога (`context_loader.py:167-172`); freshness-warning пользователю нет |
| 3.2 | Redis отсутствует — fallback лимитеров | PASS (с оговорками multi-dyno) | `rate_limit.py:28`, `agent_limiter.py:132-136`, `ws_tickets.py:95-99`, `redis_client.py:37-38` |
| 3.3 | LLM: все провайдеры упали | PASS | подтверждено живьём в Фазе 3 (fail-fast 0.49s, user-friendly ответ, трейс сохранён) |
| 3.4 | LLM: streaming-путь `_finalize_on_error` | PASS | `chat.py:977-999` — финализация трейса best-effort, SSE-ошибка уходит клиенту в любом случае |
| 3.5 | БД недоступна при старте | PASS (fail-fast) | миграции: 3 попытки → `raise` (`main.py:93-102`); приложение не стартует с битой схемой |
| 4.1 | Startup log-only блоки — последствия | RISK | см. таблицу секции 4: `_backfill_default_rules`, `reconcile_embeddings`, LLM health checks и др. |
| 5.1 | Worker silent-failure (7+ блоков) | RISK | post-index шаги и final status логируются на DEBUG (`worker.py:103-131,176-190`) |
| 6.1 | Runbook `source .env` ломает CORS_ORIGINS | RISK (внешний) | в доках репозитория паттерн НЕ рекомендуется; риск — привычка операторов/агентов; `.env.example:83` |

---

## 1. Миграции — round-trip (живой прогон)

Среда: `DATABASE_URL=sqlite+aiosqlite:////tmp/mig_test.db`, `PYTHONPATH=backend`,
`backend/.venv/bin/alembic`. Всего 75 ревизий, head = `e7f8a9b0c1d2`.

| Шаг | Команда | Результат |
|-----|---------|-----------|
| 1 | `upgrade head` (пустая БД) | OK, все 75 миграций применились |
| 2 | `downgrade -1` | OK (`e7f8a9b0c1d2` → `d5e6f7a8b9c0`) |
| 3 | `upgrade head` | OK |
| 4 | `downgrade -3` | OK (до `0e5084fdfb86`) |
| 5 | `upgrade head` | OK |
| 6 | `downgrade base` (сверх плана) | OK, вся цепочка откатилась |
| 7 | `upgrade head` (повторно, после base) | OK |

Вывод: сломанных или неполных downgrade в текущей истории нет — включая
SQLite-специфичные места (пересоздание таблиц, drop колонок/FK через batch
mode). Миграции с `drop_table`/`drop_column` (например `f2a3b4c5d6e7` drop
knowledge_sync_runs) отрабатывают в обе стороны. Round-trip зелёный.

Операционная пометка: `alembic.ini` указывает на `./data/agent.db`, но
`env.py` читает `settings.database_url` — переопределение через `DATABASE_URL`
работает и использовано в прогоне. При старте приложения `run_migrations()`
гоняет `alembic upgrade head` субпроцессом с `check=True` (`models/base.py:58-78`)
— падение миграции = осмысленный fail-fast с stderr в логе.

## 2. Reaper / heartbeat

### Конфигурация (подтверждена, `config.py:381-384`)

- `reaper_enabled=True`, `heartbeat_interval_seconds=30`,
  `reaper_interval_seconds=60`, `stale_running_heartbeat_timeout_seconds=300`.
- Reaper крутится и в web, и в worker-процессе (`main.py:157-159`,
  `worker.py:247-250`) — идемпотентен по построению (`stale_run_reaper.py:1-6`).

### Покрытие heartbeat по сущностям

| Сущность | Кто тикает | Оценка |
|----------|-----------|--------|
| `DbIndexSummary` | `heartbeat()` вокруг всего `DbIndexPipeline.run` (`db_index_pipeline.py:322-327`) | покрыто |
| `CodeDbSyncSummary` | `heartbeat()` вокруг pipeline (`code_db_sync_pipeline.py:69-74`) | покрыто |
| `IndexingCheckpoint` (repo index) | `heartbeat()` вокруг `_pipeline_runner.run` (`repos.py:554-561`) | покрыто |
| `IndexingRun` (daily sync) | `heartbeat()` с targeted UPDATE (`daily_knowledge_sync_service.py:128-140`) | покрыто |
| `IndexingRun` (repo/db index/sync) | только границы шагов и emit'ы manifest-шагов со статусом `started` (`run_coordinator.py:417-432`) | **частично** |

Детализация по `IndexingRun`: `generate_docs` эмитит событие на каждый документ
(`pipeline_runner.py:1008-1015, 1095-1101`), и это manifest-шаг со статусом
`started` → heartbeat тикает. Но шаги без intra-step emit'ов —
`code_symbol_embed` (`pipeline_runner.py:549`), `bm25_build` (:1233),
`ast_parse` (:518), `graph_build` (:527), `graph_clustering` (:766),
`clone_or_pull` большого репо (:200), `analyze_files` (:558) — при длительности
>300с дают stale heartbeat у живого run.

### Найденные гонки и сценарии

**R-1 (HIGH): ложный reap IndexingRun необратим.**
Сценарий: большой репозиторий, шаг `code_symbol_embed` идёт 6 минут (CPU-bound
ONNX). Reaper флипает `IndexingRun.status → failed` с `error="stale run reaped"`
(`stale_run_reaper.py:64-73`). Pipeline при этом жив. Когда шаг завершается,
`_on_event` видит терминальный статус и молча выбрасывает ВСЕ последующие
события, включая финальный `pipeline_end` (`run_coordinator.py:371`:
`run.status in _TERMINAL_STATUSES → return`). Итог: run навсегда остаётся
`failed` с ложной причиной, хотя индексация реально завершилась успешно.
`IndexingCheckpoint` при этом продолжает тикать и показывает `running` —
`/repos/{id}/status` и Runs UI противоречат друг другу.

**R-2 (HIGH): окно duplicate-dispatch после flip summary-статуса.**
Сценарий (ARQ-режим): worker завершил `pipeline.run` и выполняет post-index
шаги `_regenerate_overview` (LLM-вызов) + `_run_data_probes` ВНЕ heartbeat-контекста
(`worker.py:109-122`; in-process аналог — `connections.py:960-965`). Статус
всё ещё `running`, heartbeat не тикает. Если overview+probes заняли >300с,
reaper флипает `DbIndexSummary → failed`. Guard'ы запуска читают именно этот
статус: `maybe_autostart_db_index` (`connections.py:207`) и ручной триггер
(:716) видят `failed` и честно запускают ВТОРОЙ индекс параллельно с ещё
живым первым (in-memory `_db_index_tasks` на web-dyno в ARQ-режиме пуст —
`_dispatch_db_index` возвращается сразу, `connections.py:113-115`). Итог:
двойной расход LLM/CPU, гонки upsert'ов в ChromaDB и checkpoint'ов.
Self-heal есть (finally живого worker перезапишет статус), но окно гонки реально.

**R-3 (MEDIUM): молчаливый heartbeat-writer.**
Ошибки писателя глотаются на DEBUG (`heartbeat.py:22-28`). Если сессия БД для
heartbeat сломана дольше 300с (network partition до БД при живом LLM-вызове),
reaper убьёт живой run. Окно в 300с делает сценарий маловероятным, но при нём
причина в Runs UI — «stale run reaped», а не «БД была недоступна».

**R-4 (LOW): статус после flip — пользователь видит «failed» без причины.**
Reaper выставляет текст ошибки только у `IndexingRun` («stale run reaped»);
`DbIndexSummary`/`CodeDbSyncSummary` получают голый `failed` без поля причины
(`stale_run_reaper.py:46-58`). Фронтенд рендерит generic error
(`OnboardingWizard.tsx:200-201`). Рекомендация: поле `indexing_error` или
отдельный статус `interrupted` (как у checkpoint — `stale_run_reaper.py:62`).

**Нейтрализация отмен (by design, не находка):** `except Exception` не ловит
`CancelledError` (BaseException); при shutdown in-process задач
(`task_queue.py:53-62`) и при ARQ `job_timeout=1800` (`worker.py:299`)
finally с финальным статусом может не успеть — статус повисает `running`, и
именно reaper подчищает через ≤300с. Контракт согласованный.

## 3. Деградация внешних зависимостей

### 3.а ChromaDB

- **Конструктор ленив к сети, но не к диску.** `HttpClient` не коннектится в
  `__init__`, а `PersistentClient` создаёт/открывает каталог сразу
  (`vector_store.py:111-121`). При битой локальной БД/прав доступа падение
  происходит при импорте `repos.py` — там module-level singleton
  `_vector_store = VectorStore()` (`repos.py:46`) БЕЗ try/except → **приложение
  не стартует вообще**. RISK.
- **Query-time деградация — корректная, но невидимая.** Все точки retrieval
  обёрнуты: `knowledge_catalog_service.py:479-483,540-542` (debug + `[]`),
  `context_loader.py:377` (try), `knowledge_agent.py:347` (to_thread + try).
  500-ка пользователю не грозит. НО: `has_knowledge_base` при любой ошибке
  Chroma молча возвращает `False` без единой записи в лог
  (`context_loader.py:167-172`). Аутедж Chroma **неотличим от «проект не
  проиндексирован»**: роутер просто не предлагает KB-инструменты, пользователь
  получает ответ без RAG-контекста, freshness-warning не показывается
  (в отличие от MCP/schema-map, где emit'ятся `orchestrator:warning` —
  `context_loader.py:155-164,196-205`). Что теряет пользователь: doc-RAG по
  репозиторию, свежесть provenance (`indexed_at`/`commit_sha` из chunk metadata
  перестаёт попадать в контекст).
- **`vector_store.py:43` «skip silently»** — это `_check_window_mismatch`:
  если сама проверка окна токенов упала, предупреждение о stale/truncated
  векторах НЕ появляется; усечённые эмбеддинги обслуживаются молча.
  Сам mismatch при рабочей проверке логируется WARNING'ом с явной инструкцией
  (`vector_store.py:32-40`) — это хорошо; плохо, что отказ проверки беззвучен.

### 3.б Redis отсутствует / упал

| Компонент | Fallback | Корректность |
|-----------|----------|--------------|
| Task queue | ARQ → in-process asyncio (`task_queue.py:29-40,108-113`) | OK; при частичном enqueue-сбое (job поставлен, ответ потерян) теоретический дубль in-process+ARQ |
| Rate limiter (slowapi) | `memory://` per-process (`rate_limit.py:20-28`) | single-dyno OK; **multi-dyno: лимит ×N** |
| AgentLimiter | Redis Lua → in-memory на лету (`agent_limiter.py:126-137`) | OK; рассинхрон acquire/release между бэкендами self-heal за ≤1ч (EXPIRE 3600) |
| WS tickets | Redis GETDEL → in-memory (`ws_tickets.py:79-110,122-156`) | single-dyno OK; **multi-dyno без Redis: тикет с dyno A не redeem'ится на dyno B** → WS-handshake отказ, спасает retry/sticky |
| `redis_lock` (cron single-flight) | без Redis → **yield True** (`distributed_lock.py:23-25`) | **multi-dyno без Redis: КАЖДЫЙ dyno запускает git-poll/daily-sync волну**; daily sync защищён day-scoped `task_id` (`main.py:772`), scheduler — `claim_due`, git-poll — только per-process debounce |
| Workflow events subscriber | no-op без Redis (`workflow_events.py:81-82`) | OK; cross-process прогресс пропадает, но в ARQ-режиме без Redis его нет по определению |

При падении Redis ПОСЛЕ успешного connect `redis_lock` fail-closed
(`acquired=False`, `distributed_lock.py:32-34`) — cron-тик пропускается, что
безопаснее дублей, но daily-sync волна того часа теряется молча (INFO-лог).

### 3.в LLM — все провайдеры упали

Подтверждено живьём в Фазе 3 (04-e2e-live.md): fail-fast 0.49s, user-friendly
ответ, трейс сохранён. Дополнительно проверен streaming-путь статически:
`_finalize_on_error` (`chat.py:977-999`) финализирует трейс best-effort —
ошибка финализации логируется WARNING'ом и не роняет SSE; клиент получает
структурированный `error_payload` (`chat.py:1086-1121`), статус сессии
возвращается в `idle`. Замечание низкой severity: при wf_id=None трейс пишется
под синтетическим `stream-error-{session_id}` — поиск такого трейса по
workflow_id невозможен, только по session.

### 3.г БД приложения недоступна при старте

- Миграции: 3 попытки с паузой 2с, затем `raise` (`main.py:93-102`) →
  **fail-fast, приложение не стартует** — правильно.
- `init_db()` — только импорты моделей, БД не трогает (`models/base.py:136-169`).
- Все последующие startup-шаги, работающие с БД, — log-only WARNING
  (`_cleanup_stale_checkpoints` main.py:513, `_backfill_default_rules` :556,
  `_periodic_*` :581,599,614, `_cleanup_pipeline_runs` :857, reaper sweep
  `reaper_loop.py:28-29`). Если БД отвалилась МЕЖДУ миграциями и этими шагами —
  приложение стартует, запросы начнут 500-ить; оператор увидит только WARNING'и.
- `reconcile_embeddings` — log-only (`main.py:135-136`): при смене
  embedding-модели и сбое reconcile устаревшие векторы продолжают
  обслуживаться; никакого сигнала, кроме лога. `_check_window_mismatch` —
  второй (молчаливый при своём отказе) предохранитель, см. 3.а.
- `_check_alembic_head` — log-only DEBUG (`main.py:500-501`); в dev делает
  auto-migrate, в prod только предупреждает о рассинхроне схемы.

## 4. Startup-resilience: карта lifespan (`main.py:88-186`)

| # | Шаг | Обработка сбоя | Что увидит пользователь/оператор при silent failure |
|---|-----|----------------|-----------------------------------------------------|
| 1 | `run_migrations` ×3 | **raise → boot abort** | fail-fast, stderr alembic в логе — OK |
| 2 | `init_db` | нет try (безопасно — импорты) | — |
| 3 | `_check_alembic_head` | log-only DEBUG | рассинхрон схемы незаметен до первых 500 |
| 4 | `_cleanup_stale_checkpoints` | log-only WARNING | сироты «running» подчистит reaper |
| 5 | `run_reaper_sweep` | log-only WARNING | то же — следующий тик через 60с |
| 6 | `_backfill_default_rules` | log-only WARNING | у старых проектов нет default rule; фича rules молча деградирует |
| 7 | `_periodic_learning_decay` | log-only WARNING | confidence learnings/notes не decay'ится |
| 8 | `_periodic_insight_maintenance` | log-only WARNING | просроченные insights не expire'ятся (TTL-семантика Vision §5 #4 не исполняется) |
| 9 | `_cleanup_pipeline_runs` | log-only WARNING | таблица pipeline_runs растёт |
| 10 | `init_task_queue` | fallback asyncio + WARNING | OK; multi-dyno без Redis — задачи локальные |
| 11 | `shared_cache` / `redis_client` | fallback memory + WARNING | OK, см. 3.б |
| 12 | `reconcile_embeddings` | log-only WARNING | stale embeddings после смены модели — молчаливая деградация retrieval |
| 13 | `start_workflow_event_subscriber` | no-op без Redis | OK |
| 14 | `RunCoordinator().attach()` | регистрация хука | — |
| 15 | 7 фоновых циклов (backup/scheduler/health/maintenance/git-poll/daily-sync/reaper) | create_task; внутренние try/except в циклах | OK; крах итерации логируется, цикл живёт |
| 16 | `TracePersistenceService.start` | только хук+task (`trace_persistence_service.py:145-148`) | — |
| 17 | LLM health checks | log-only **DEBUG** (`main.py:176-177`) | роутер не знает о мёртвых провайдерах заранее; спасает per-call fail-fast (0.49s, Фаза 3) — но сигнал оператору на DEBUG |
| 18 | MCP session manager | по флагу `mcp_enabled` (default off) | при включённом MCP падение уронит boot — не проверялось живьём |

## 5. Worker silent-failure карта (`worker.py:28-269`)

| Строки | Блок | Что маскируется | Как обнаружить |
|--------|------|-----------------|----------------|
| :42-43 | connection not found → `logger.error` + return | IndexingRun, созданный в роуте, повисает `running` до reap (300с), причина искажается на «stale run reaped» | статус в БД через 5 мин; лог ERROR сразу |
| :103-108 | schema cache invalidation | до 300с устаревший schema cache (DBIDX-D12) | только DEBUG-лог; self-heal по TTL |
| :117-122 | post-index overview+probes | в ARQ-режиме проект остаётся без overview и probe-evidence; статус `completed` вводит в заблуждение | только DEBUG-лог; UI — пустой overview. **Уровень ниже, чем в in-process пути** (`repos.py:483-484`, `connections.py:988+` — там WARNING) |
| :123-124 | outer except pipeline | — | `logger.exception` — видим, НЕ silent |
| :130-131 | финальный `set_indexing_status` | статус застрянет `running` → reap через 300с; маскирует сбой БД | DEBUG-лог + reaper INFO |
| :176-181 | sync post-overview | то же для sync: нет overview | только DEBUG-лог |
| :189-190 | финальный `set_sync_status` | застрявший `running` → reap | DEBUG-лог + reaper INFO |
| `repos.py:326-330` | project missing в `run_repo_index_task` | run повисает `running` до reap | ERROR-лог сразу; статус — через 300с |

Общий паттерн: финальные записи статуса и post-шаги — DEBUG. В проде с
`LOG_LEVEL=INFO` эти сбои **невидимы ни в логах, ни в метриках, ни в статусах**
(кроме отложенного эффекта reaper). Рекомендация: поднять post-index и
final-status блоки до WARNING; добавить счётчик в `/api/metrics`.

## 6. Runbook-риск: `source .env` vs CORS_ORIGINS

- Подтверждённая механика (Фаза 3, 04-e2e-live.md:265): `CORS_ORIGINS` —
  JSON-массив (`.env.example:83`:
  `CORS_ORIGINS=["http://localhost:3000","http://localhost:3100",...]`);
  `set -a; source backend/.env` → bash съедает кавычки → pydantic
  `SettingsError` → backend не стартует.
- **Проверка доков репозитория**: `INSTALLATION.md` (cp `.env.example` +
  pydantic auto-load), `README.md`, `CLAUDE.md`, `USAGE.md`, `FAQ.md`,
  `Makefile` (`setup-env`: cp + sed по ключу), `scripts/dev-up.sh`
  (docker compose), `scripts/deploy-heroku.sh` — паттерн `source .env`
  **нигде не рекомендуется**. Риск внешний: привычка операторов и LLM-агентов
  «засорсить env» перед ручным запуском uvicorn/alembic/pytest.
- Рекомендация: одна строка-предостережение в `INSTALLATION.md` возле
  «Edit backend/.env» и/или парсер-фолбэк в `config.py`, принимающий
  незаквоченный JSON-массив. Сейчас приложение корректно читает `.env` само
  (pydantic-settings) — любой `source` только вреден.

## Реестр находок

| ID | Severity | Локация | Суть |
|----|----------|---------|------|
| RES-1 | HIGH | `run_coordinator.py:371` + `stale_run_reaper.py:64-73` | Ложный reap живого IndexingRun необратим: события терминального run отбрасываются, `pipeline_end` теряется → вечный фантомный `failed` |
| RES-2 | HIGH | `pipeline_runner.py:549,1233,518,200` (шаги без emit'ов) | Шаги >300с без heartbeat на IndexingRun: `code_symbol_embed`, `bm25_build`, `ast_parse`, `clone_or_pull` → триггер RES-1 |
| RES-3 | HIGH | `worker.py:115-116`, `connections.py:960-965` + guards `connections.py:207,716` | Post-index окно без heartbeat: reap живого run → guards пропускают duplicate dispatch (двойной LLM-расход, гонки записи) |
| RES-4 | MEDIUM | `repos.py:46` | Module-level `VectorStore()`: крах Chroma PersistentClient при импорте = приложение не стартует |
| RES-5 | MEDIUM | `context_loader.py:167-172` | Chroma outage ≡ «нет KB»: молча `False`, без лога и без freshness-warning пользователю |
| RES-6 | MEDIUM | `worker.py:117-122,130-131,176-190` | Post-index и final-status сбои на DEBUG: в проде невидимы; overview/probes молча отсутствуют |
| RES-7 | MEDIUM | `rate_limit.py:28`, `ws_tickets.py:101-110`, `distributed_lock.py:24-25` | Multi-dyno без Redis: лимиты ×N, WS-тикеты не cross-dyno, cron single-flight off (git-poll дубли) |
| RES-8 | MEDIUM | `main.py:135-136` + `vector_store.py:41-43` | Сбой embedding reconcile/проверки окна токенов — log-only/беззвучно: stale vectors обслуживаются молча |
| RES-9 | LOW | `stale_run_reaper.py:46-58` + `OnboardingWizard.tsx:200` | Summary-статусы после reap без причины: пользователь видит голый «failed» |
| RES-10 | LOW | `worker.py:42-43`, `repos.py:326-330` | Early return → run висит `running` 300с, причина перезаписывается на «stale run reaped» |
| RES-11 | LOW | `heartbeat.py:22-28` | Отказ heartbeat-writer беззвучен (DEBUG); при partition до БД >300с живой run будет reap'нут |
| RES-12 | LOW | `main.py:176-177` | LLM health-check startup failure на DEBUG |
| RES-13 | RISK (внешний) | `.env.example:83`, runbook-практики | `source .env` ломает CORS_ORIGINS → SettingsError; в доках не рекомендуется, но не запрещено явно |

## Что проверено и зелёное (без находок)

- Миграции: полный round-trip head⇄base на SQLite — 75/75 в обе стороны.
- Reaper: идемпотентность, NULL-heartbeat grace, rowcount-гарды; 6/6 тестов.
- LLM-полный-отказ: graceful (Фаза 3, live).
- Streaming error path: трейс/статус сессии/SSE-ошибка корректны.
- БД при старте: fail-fast с 3 ретраями; половинчатого состояния нет.
- Redis-отсутствие (single-dyno): все fallback корректны и покрыты логами WARNING.
- Фоновые циклы lifespan: крах итерации не убивает цикл; shutdown отменяет задачи.
