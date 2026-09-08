# T05–T09 — малые пакеты

Пять задач меньшего объёма; каждая самодостаточна. Общие правила — `CONVENTIONS.md`.

---

## T05 · P2 · конфиг+замер — EMBEDDING_UPSERT_BATCH_SIZE под Standard-2X

**Контекст.** Дефолт 8 выбран 2026-08-19 под квоту 512 МиБ (измерено: батч 200 =
967 МиБ/9,3 с; батч 8 = 415 МиБ/10,9 с на 960 чанков — CLAUDE.md § Deploy notes, п. 0).
Worker теперь **Standard-2X = 1 ГиБ** (`heroku ps`, 2026-09-08). Прод сейчас
не переопределяет переменную. Прогноз: батч 32–64 вернёт большую часть скорости
`code_symbol_embed` (~2 300 с в force_full) с запасом памяти.

**Шаги.**
1. Дождаться мержа T03 (замер чище на стабильном пайплайне; файлы не пересекаются).
2. `heroku config:set EMBEDDING_UPSERT_BATCH_SIZE=32 -a checkmydata-api`.
3. **В том же изменении** добавить ключ в `DELIBERATE` map `scripts/config_drift.py`
   с причиной («worker Standard-2X; измерение T05») — иначе `make config-drift` красный.
4. Спровоцировать force_full (ручной re-index) и замерить: длительность
   `code_symbol_embed` из workflow-лога; память — отсутствие R14/R15 в
   `heroku logs | grep -E "R14|R15"` за окно прогона.
5. Если R14/R15 или прирост < 15% — вернуть 8 (unset + убрать из DELIBERATE) и записать
   результат; если хорошо — опционально шаг до 64 тем же протоколом.

**DoD:** таблица «батч → секунды шага, пик-инциденты» в PR/леджере; config-drift зелёный.

---

## T06 · P2 — Алерт приближения к потолку daily_sync

**Контекст.** Потолок `daily_knowledge_sync_job_timeout_seconds = 7200`
(`config.py:550`, обёртка `app/worker.py:369,412`). Измерено: completed max =
**7 214,9 с** — прошли впритык; failed max 7 497 с. Тяжёлая ночь упрётся молча.

**Реализация.** В завершении `DailyKnowledgeSyncService.run_for_project` (у места, где
пишется итог run): если `duration > 0.85 * timeout` →
`WARNING "daily_sync: %.0fs of %.0fs budget (%.0f%%) — the next heavy night will hit
the ceiling"` + counter `daily_sync_budget_near_ceiling_total`. Таймаут читать из
settings в момент проверки (не кэшировать).

**Тесты** (`tests/unit/services/test_daily_sync_budget_alert.py`): 0,84 → тишина;
0,86 → WARNING+counter; сообщение содержит оба числа. Существующий
`test_repo_index_ceiling.py` — не трогать (другой потолок, см. CLAUDE.md про 21600/7200).

**DoD:** тесты зелёные; строка в CLAUDE.md § Crash recovery о новом алерте; леджер.

---

## T07 · P2 — Кросс-процессная эксклюзивность repo-index: доказать и понизить

**Контекст.** CLAUDE.md называет «Still open: mutual exclusion per-process only»
(`repos.py:53` — in-memory `_indexing_locks`). НО: `RunCoordinator.start`
(`run_coordinator.py:256-305`) уже держит **DB-дедуп** `_find_active` + отлов TOCTOU
через partial unique index — это кросс-процессно. Инцидент 2026-09-01 случился не из-за
отсутствия DB-механизма, а из-за реапера, фальсифицировавшего строку (закрыто `_is_live`).
Задача — не строить Redis-лок (его TTL пришлось бы продлевать тем же битом сердца,
который тогда отказал — задокументированная причина отсрочки), а **доказать** дедуп и
привести документацию/код в соответствие.

**Шаги.**
1. Прочитать `run_coordinator.py:256-305` и НАЗВАТЬ незакрытые окна, если есть
   (например: путь, создающий прогон мимо `RunCoordinator.start` — grep всех
   создателей `IndexingRun(`).
2. Тест-доказательство (`tests/unit/services/test_run_exclusion_cross_process.py`):
   два конкурентных `start(kind="index_repo", project)` на РАЗНЫХ сессиях → ровно один
   успех, второй `RunAlreadyActiveError`. Честно про SQLite: если partial unique index
   не срабатывает на SQLite — тест через две последовательные сессии + прямую проверку
   ограничения, с докстрингом по образцу `_lock_owner` («guard real where the race is
   real»).
3. Понизить `_indexing_locks` до фаст-пас-комментария («перф-оптимизация, НЕ механизм
   корректности — корректность в RunCoordinator») либо удалить, если тест покрывает.
4. Обновить CLAUDE.md: абзац «Still open…» заменить на доказанное состояние с датой.

**DoD:** тест зелёный на CI (Postgres? — CI гоняет SQLite: зафиксировать ограничение
честно); CLAUDE.md обновлён; леджер.

---

## T08 · P2 · **blocked(D5)** — Enforcement max_index_bytes

**Контекст.** `plans.max_index_bytes` продаётся (base=1 ГБ), счётчик
`estimate_index_bytes(docs_bytes, symbols, edges, embeddings)` существует
(`plan_catalogue.py:40-46`) и вызывается только из теста. Измерено: esim-php ≈ 460 МБ
(doc_embeddings 331 + edges 76 + symbols 44 + прочее). Enforcement-метода в
`Entitlements`-протоколе нет.

**Блокер D5 (оператору):** что делает превышение? (а) warning + строка Needs-you;
(б) блок force_full; (в) блок и инкрементального. Рекомендация исполнителя: (а) на
первом шаге — деградация открытая, как весь биллинг-шов.

**Дизайн после решения.**
- Пятый метод протокола ИЛИ (дешевле) чтение `get_entitlements()`-объекта без расширения
  протокола — внимание: `test_entitlements_seam.py::test_it_has_four_methods_and_no_more`
  требует «пятый метод — с письменным обоснованием»; следовать его докстрингу.
- Точка замера: старт repo-index (`_spawn_repo_index`) — счёт по count-запросам
  (быстро), НЕ pg_total_relation_size (лжёт на SQLite).
- Превышение → см. D5; в любом варианте: counter `index_over_quota_total`,
  AttentionItem kind `index_over_quota` (route `panel=settings`), строка сценария
  (новый SCN — id с конца, draft).
- Degrade open: не смогли посчитать → пропустить с WARNING.

**DoD:** решение D5 записано в PLAN.md § Открытые решения с датой; далее по пакету.

---

## T09 · P3 · расследование — token_usage: cost>0 при tokens=0

**Контекст (receipt).** 2026-09-04: `usd=0.99, tokens=0, calls=2`, модель
`anthropic/claude-opus-4.8` (SQL в сайдкаре аудита). Плюс известный gap:
«Streaming responses are not yet sinked» (CLAUDE.md § LLM routing).

**Шаги.** Найти писателя `estimated_cost_usd` (grep по `usage_sink.py`,
`UsageService.record_usage`); установить, какой вызов пишет cost без токенов (упавший
вызов? стрим? ретрай?); решить: (а) баг учёта — фикс + тест «cost>0 ⇒ tokens>0 или
причина в колонке»; (б) легитимно (например, минимальная тарификация) — задокументировать
в докстринге sink и закрыть. Не чинить до установления механизма.

**DoD:** механизм назван (докстринг/тест); леджер.
