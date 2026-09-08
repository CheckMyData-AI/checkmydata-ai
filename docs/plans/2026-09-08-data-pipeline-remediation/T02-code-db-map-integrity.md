# T02 · P1 — Карта code↔DB: фантомные строки становятся невозможными

**Цель:** каждая строка `code_db_sync` либо ссылается на таблицу, существующую в
`db_index` (статусы `db_only`/`matched`/`mismatch`), либо честно `code_only` с
declared-подтверждением; строки, не наблюдённые свежим прогоном, удаляются.
Оценка: 1–2 дня. Ветка `fix/T02-map-integrity`.

## Измеренное состояние (прод, 2026-09-08)

- 256 строк карты; **43 называют таблицы, которых нет в db_index (213 таблиц)** — и у
  всех 43 `updated_at = 2026-09-06`: их пишет заново каждый свежий прогон, это не мусор
  прошлых версий.
- **20 из 43 носят статус `db_only`** («есть в БД, нет в коде») — самопротиворечие.
  Примеры: `axios`, `vue`, `const`, `export`, `import`, `change`, `library`,
  `sessions`, `workspaces`. Первые семь — токены JavaScript.
- 23 — `code_only` с именами вида `clientlogses`, `twiliocallses`, `mobile_identifierses`
  (двойная плюрализация — след `_model_name_to_table`).
- Достоверная часть: 135 `matched` (все с required_filters), 98 честных `db_only`.

SQL-репродукция (веркиция «до» и гейт «после»):
```sql
SELECT sync_status, count(*) FROM code_db_sync
 WHERE table_name NOT IN (SELECT table_name FROM db_index) GROUP BY 1;
-- сейчас: db_only=20, code_only=23. Цель: 0 строк, либо только code_only с declared-источником.
```

## Карта кода (receipts)

| Что | Где |
|---|---|
| Резолвер статуса (правило «нет DB-стороны → code_only») | `app/knowledge/code_db_sync_pipeline.py:985-1027` (`resolve_sync_status`) |
| Матчинг и суффиксное ключевание (SYNC-L7, подозреваемый №1 для `sessions`) | `code_db_sync_pipeline.py:528-559` (`_match_tables`, `db_by_key`, `_display_name`) |
| DB-сторона грузится ТОЛЬКО из db_index | `code_db_sync_pipeline.py:165-188` (`load_db_index` → `DbIndexService.get_index`) |
| Извлечение имён из кода (подозреваемый №2 для `axios`/`vue`) | `app/knowledge/repo_analyzer.py:693-694` (declared), `:748`, `:765` (`_extract_model_names`) |
| Фильтр правдоподобия | `repo_analyzer.py:57-79` (`tables_declared_in_migration` + `is_plausible_table_name`) |
| Модель строки | `app/models/code_db_sync.py:22-48` |

## Подзадачи (в этом порядке)

### T02.0 — Диагностика: найти писателя фантомных `db_only` (½ дня)
Механизм НЕ установлен аудитом — не чинить вслепую. DB-сторона приходит только из
db_index (receipt выше), значит `db_only` для отсутствующей таблицы рождается либо
(а) суффиксным ключеванием/`_display_name`, превращающим `atom_sessions` → `sessions`
при записи, либо (б) путём записи, минующим `resolve_sync_status`. Действия:
```bash
grep -n "sync_status" app/knowledge/code_db_sync_pipeline.py   # все места присвоения
grep -rn "CodeDbSync(" app/                                     # все конструкторы строк
```
Написать **падающий** unit-тест-репродукцию: фикстура db_entries=[atom_sessions],
code-имена=["axios","sessions"] → прогнать матчинг → assert в результатах нет строки
`table_name='sessions'` со статусом `db_only` и нет строки `axios` вовсе. Тест падает —
механизм пойман; зафиксировать его в докстринге теста.

### T02.1 — Инвариант в записи (½ дня)
В точке персиста карты: строка со статусом `db_only|matched|mismatch`, чей `table_name`
отсутствует в загруженном db_index, **не пишется**, логируется
`WARNING "code_db_sync: refusing phantom row %s status=%s"` и считается в новом счётчике
`code_db_sync_phantom_rows_refused_total`. Это страховка нижнего уровня — она обязана
остаться даже после фикса источника (T02.0), потому что ловит следующий такой баг.

### T02.2 — Языковой гейт экстрактора (½ дня)
`_extract_model_names` работает только для файлов ORM-языков проекта (php/py/rb по
`ORM_PATTERNS`); `.js/.ts/.vue/.jsx/.tsx` не порождают inferred-имён никогда (declared —
можно). Двойная плюрализация (`clientlogses`) — добавить в `is_plausible_table_name`
правило «не плюрализовать уже-множественное» ИЛИ отклонять `*ses` от `*s+es` — решить по
фикстурам из 23 реальных имён (все перечислены в сайдкаре аудита).

### T02.3 — Prune ненаблюдённых строк (½ дня)
Прогон завершает транзакцию удалением строк `connection_id`, не вошедших в свежий
набор: `DELETE … WHERE connection_id=:c AND table_name NOT IN (:fresh)`. Лог
`INFO "code_db_sync: pruned %d stale rows"`. Осторожно: удаление НЕ должно трогать
строки при частичном/упавшем прогоне — только после успешного полного построения набора
(смотреть, где сейчас commit; prune в том же коммите с записью).

### T02.4 — Тесты и прод-верификация
- unit: репродукция из T02.0 (теперь зелёная), инвариант T02.1 (фантом → refused +
  counter), гейт T02.2 (js-файл не рождает имён), prune T02.3 (строка исчезает; при
  исключении до commit — не исчезает).
- Прод-гейт: после ближайшего ночного sync SQL-репродукция возвращает 0; вывод — в PR.

## Наблюдаемость
`code_db_sync_phantom_rows_refused_total` (counter, ожидание 0 после T02.0);
prune-лог с числом; существующий summary-лог прогона дополнить `phantoms_refused=N`.

## Rollback
Чистый revert PR; данные чинятся следующим прогоном (карта переписывается).

## DoD
- [ ] T02.0 механизм назван в докстринге теста-репродукции
- [ ] SQL-репродукция на проде = 0 строк (вывод в PR)
- [ ] CLAUDE.md § «Code↔DB table names» дополнен новым правилом + датой
- [ ] Ловушки: ratchet `except Exception` не вырос без обоснования (CONVENTIONS §2)
- [ ] Леджер PLAN.md обновлён
