# T04 · P1 — db_index `trigger=auto`: диагностика и потолок fetch_samples

**Цель:** прогон db_index никогда не семплирует живую клиентскую БД часами; политика
auto-триггера названа в документации; потолок закреплён тестом.
Оценка: 1 день (из них полдня — диагностика). Ветка `fix/T04-db-index-sampling-cap`.

## Измеренное состояние

- `trigger='auto'` прогоны (все completed, все со step `fetch_samples`):
  **30 279 с (8,4 ч)** 08-13, **23 198 с** 08-19, 8 793 с 08-06, 8 593 с 08-03.
- `trigger='schedule'` те же 213 таблиц: avg **1 544 с** (26 мин).
- После 2026-08-19 аномалия не повторялась — но `DB_INDEX_INCREMENTAL_ENABLED=true` и
  D-серия легли в те же недели: **причинность не доказана**, поэтому сначала диагностика.

## Карта кода (receipts)

| Что | Где |
|---|---|
| auto-триггер: `RunCoordinator.start(kind="db_index", trigger="auto")` | `app/api/routes/connections.py:78-93` — найти вызывающих этот helper (grep по имени функции-обёртки) — кто и когда дергает: refresh-schema? readiness? chat-path? |
| Шаг семплинга | `app/knowledge/db_index_pipeline.py` (grep `fetch_samples`) |
| Кнопки | `config.py`: `db_index_stats_enabled` (on), `db_index_stats_max_columns` (20), `db_index_stats_sample_cap` (100 000), `db_index_max_tables_analyzed` (500), `db_index_ttl_hours` (24) |

## Подзадачи

### T04.0 — Диагностика (без изменений поведения)
1. Назвать всех вызывающих auto-триггер и условие срабатывания (TTL? отсутствие
   индекса? chat readiness?). Ответ — в докстринг триггер-хелпера и в CLAUDE.md.
2. Пер-таблично залогировать тайминг семплинга: `INFO "fetch_samples: %s took %.1fs
   rows=%d"` только для таблиц > 5 с + сводка шага
   `INFO "fetch_samples: %d tables, %.0fs total, slowest=%s(%.0fs)"`. Это и есть
   инструмент, которого не хватило августу: 8,4 часа без единого имени таблицы в логе.
3. Если код позволяет — восстановить по логике, ЧТО могло занять 8,4 ч (полный скан без
   cap? MySQL через SSH-туннель с реконнектами — см. отказ `Can't connect to MySQL` от
   09-05?). Гипотезы записать в PR; не чинить недоказанное.

### T04.1 — Потолок шага
Wall-clock бюджет шага: новый конфиг `db_index_fetch_samples_budget_seconds: int = 1800`
(валидация «непозитив → raise at boot», по образцу `sql_timeout_breaker_threshold`).
По исчерпании: шаг завершает обработанные таблицы, остальные помечает
`stats: skipped(budget)` (частичная статистика — честно её показать в `column_stats_json`
отсутствием + WARNING с перечнем пропущенных), прогон НЕ фейлится. Деградация открытая
и названная — таблица без stats лучше прогона в 8 часов по живой БД клиента.

### T04.2 — Тесты
- unit: бюджет исчерпан на N-й таблице → N обработано, остальные skipped, WARNING
  содержит имена, прогон completed;
- unit: непозитивный бюджет → boot raise;
- unit: сводка-лог печатается и на полном успехе (тишина ≠ пройдено, CONVENTIONS §Наблюдаемость).

## Наблюдаемость
Counter `db_index_sample_budget_exhausted_total`; сводка шага (см. T04.0.2); в
`pipeline_end` db_index — `sampled=N skipped_budget=M`.

## Прод-верификация
Следующий `trigger=auto` (спровоцировать: refresh-schema или дождаться TTL): длительность
< 1 800 с ЛИБО в логе сводка с именами медленных таблиц, объясняющая время. Вывод — в PR.

## Rollback
Конфиг-бюджет ↑ или revert; данные не мутируются иначе, чем раньше.

## DoD
- [ ] Ответ «кто зовёт auto и когда» — в докстринге + CLAUDE.md (дата)
- [ ] Тесты зелёные; ratchet-потолки не выросли молча
- [ ] `.env.example` + config-докстринг для нового бюджета
- [ ] Леджер PLAN.md обновлён
