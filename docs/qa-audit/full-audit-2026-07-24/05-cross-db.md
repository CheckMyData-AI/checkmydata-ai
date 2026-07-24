# 05 — Кросс-БД тестирование коннекторов: MySQL / MongoDB / ClickHouse (Фаза 3.3)

Дата: 2026-07-24
Исполнитель: автоматизированный агент (прямые вызовы классов коннекторов, `PYTHONPATH=backend`, `backend/.venv/bin/python`)
Окружение: macOS, Docker; throwaway-контейнеры на нестандартных портах с throwaway-паролями:
- `e2e-mysql-audit` — mysql:8.0, порт 13306, БД `e2e` (users 10 строк / orders 10 строк / view `paid_orders`)
- `e2e-mongo-audit` — mongo:7, порт 27018, БД `e2e` (users 10 док. / orders 10 док., пользователь `e2e_rw` с readWrite на `e2e`)
- `e2e-ch-audit` — clickhouse/clickhouse-server:24.8, порты 18123(HTTP)/19000(native), БД `e2e` (users MergeTree 10 строк, `ORDER BY id`)

Тестовые данные включали краевые случаи: кириллицу, CJK (`王小明`, `日本 太郎`), emoji (🚀), апострофы, умлауты, NULL-значения, отрицательный decimal, даты/даты-время, вложенные документы (Mongo). LLM не использовался. Рабочая dev-БД `backend/data/agent.db` не затрагивалась. Файлы репозитория не изменялись (кроме этого отчёта); обход найденного Mongo-бага выполнен monkeypatch'ем в тестовом процессе (детали — раздел «Баги», B1).

## Сводная матрица «проверка × СУБД»

| Проверка | MySQL 8.0 | MongoDB 7 | ClickHouse 24.8 |
|----------|-----------|-----------|------------------|
| connect: валидные креды | PASS (8 мс) | PASS (1 мс) | PASS (6 мс) |
| connect: неверный пароль | PASS — `OperationalError (1045) Access denied`, 2 мс | PASS — `connect()` ленивый; `test_connection()`→False (5 мс); `execute`→`Authentication failed (code 18)` | PASS — `DatabaseError code 516 Authentication failed` на `connect()`, 1 мс |
| connect: закрытый порт | PASS — `OperationalError (2003)`, ~0 мс (RST) | PASS — False/ошибка через 10.1 с (serverSelectionTimeoutMS=10 с, ограничен) | PASS — `OperationalError` (connection refused) на `connect()`, 1 мс |
| hang/бесконечный таймаут | PASS — не выявлен (connect_timeout=30 в коде) | PASS — ограничен 10 с | PASS — не выявлен (fail-fast на eager connect) |
| schema introspection | PASS — таблицы, view (`object_kind=view`), PK, FK (`orders.user_id→users.id`), индексы, enum-тип, decimal, комментарий таблицы | PASS (с оговоркой B1) — union-типы (`Decimal128\|int`), вложенные пути (`nested.level1.level2`), `_id` как PK, индексы, row_count | PASS — типы `Nullable(...)`, комментарий, `is_sort_key=True` у `id` (ORDER BY id), `object_kind` по engine |
| execute: валидный SELECT/find | PASS — строки корректны | PASS (B1) — find/aggregate/count корректны; `$group+$sum` по Decimal128 → точные суммы | PASS — строки корректны |
| параметризованный запрос | PASS — `:name` → `%s` | n/a (JSON-фильтр) | PASS — `{c:String}` |
| READ-ONLY слой 1 (DB-сессия) | PASS — `SET SESSION TRANSACTION READ ONLY`: INSERT/UPDATE/DELETE/DROP/CREATE/TRUNCATE → `(1792) Cannot execute statement in a READ ONLY transaction` | PASS (app-слой, у Mongo нет session-RO): insert/update/delete/drop + `$out`/`$merge` + `$where`/`$function`/`$accumulator` отклонены; даже non-RO коннектор не реализует write-операции | PASS — `settings={"readonly":1}`: INSERT/DROP/ALTER/TRUNCATE/CREATE → `Code: 164 READONLY` |
| READ-ONLY слой 2 (SafetyGuard) | PASS — см. матрицу ниже | PARTIAL — `validate_mongo` не блокирует `$out`/`$merge`/JS-операторы (баг B4); закрывается коннекторным гардом | PASS — см. матрицу ниже |
| Данные после попыток записи | PASS — 10 строк, целы | PASS — 10 документов, целы | PASS — 10 строк, целы |
| EXPLAIN-валидация | PASS — valid=True без warnings (10 строк < порога 100k); невалидный SQL → `Column Not Found` | n/a (пропускается по db_type) | **FAIL** — warning о full scan возникает и при `WHERE id = 5` (баг B3); невалидный SQL корректно флагается |
| Пустой результат | PASS — rc=0, rows=[] | PASS — rc=0, rows=[] | PASS — rc=0, rows=[] |
| Кап строк (MAX_RESULT_ROWS=10000) | PASS — 12000 строк → rc=10000, `truncated=True` | PASS — 10500 док. → rc=10000, `truncated=True`; `limit:5` → rc=5 без truncation | PASS — `numbers(25000)` → rc=10000, `truncated=True` |
| Таймаут запроса (бюджет 1 с) | PASS — `SLEEP(5)` → «Query timed out after 1s», ровно 1.0 с | PASS — `$where:sleep(5000)` → «Query timed out after 1s», 1.0 с | PASS — `sleep(3)` → «Query timed out after 1s», 1.0 с |
| Здоровье коннектора ПОСЛЕ таймаута | PASS — последующие запросы работают | PASS — последующие запросы работают | **FAIL** — коннектор клинит: «Attempt to execute concurrent queries within the same session» до завершения исходного запроса на сервере (баг B2) |
| Unicode/кириллица/CJK/emoji | PASS — round-trip корректен | PASS — фильтр по `王小明`/🚀 работает | PASS — round-trip корректен |
| NULL / decimal / даты → типы | PASS — None / `Decimal` / `datetime`; JSON `default=str` сериализуется | PASS — None / `Decimal128→Decimal` / `datetime`; `ObjectId→hex-str` (вкл. вложенные) | PASS — None / `Decimal` / `datetime`; JSON `default=str` сериализуется |
| distinct_values (W4) | PASS — 7 стран, отсортировано | PASS — native `distinct`, 7 стран | PASS — 7 стран (SQL default из base.py) |
| approx_stats (W4) | PASS — distinct=9, null_rate=0.1, min=-50.25, max=123456.78 | PASS — native pipeline; distinct=10 (NULL считается отдельным значением — расхождение семантики, B6) | PASS — `uniqExact`: distinct=9, null_rate=0.1 |

Легенда: PASS — поведение соответствует ожиданию; PARTIAL — работает с оговорками; FAIL — дефект. «(B1)» — результат получен с тестовым monkeypatch'ем, обходящим баг B1 (репозиторий не изменялся).

## SafetyGuard — матрица app-слоя (read-only)

Проверялся `SafetyGuard(SafetyLevel.READ_ONLY).validate(query, db_type)` напрямую. SQL-матрица **идентична** для `mysql`, `clickhouse`, `postgresql` (диалект не влияет на решение — единый regex-движок).

| Запрос | Решение | Причина |
|--------|---------|---------|
| `SELECT ...` / `WITH ... SELECT` / `SHOW TABLES` / `EXPLAIN ...` / `DESCRIBE` / `DESC` / `TABLE t` / `VALUES (...)` / `EXISTS (...)` / `(SELECT 1)` | pass | statement-initial allowlist |
| `SELECT ...;` (хвостовая `;`) | pass | `rstrip(";")` |
| `UNION SELECT`, подзапросы в `IN (...)` | pass | вложенные чтения не запрещены |
| `INSERT INTO`, `INSERT INTO ... SELECT`, `UPDATE ... SET`, `DELETE FROM`, `MERGE INTO`, `REPLACE INTO`, `UPSERT INTO`, `CALL` | block | DML-denylist / allowlist |
| `DROP TABLE/DATABASE`, `ALTER TABLE`, `TRUNCATE`, `CREATE TABLE`, `CREATE OR REPLACE VIEW`, `GRANT`, `REVOKE`, `SET ...` | block | DDL-denylist / allowlist |
| `SELECT 1; DROP TABLE users`, `SELECT 1; SELECT 2` | block | «Multiple statements not allowed in read-only mode» |
| `DELETE/**/FROM users`, `DR/**/OP TABLE users`, `SELECT 1 -- c\n; DROP TABLE users` | block | комментарии вырезаются до проверки |
| `SELECT ... INTO OUTFILE`, `LOAD DATA INFILE` | block | denylist файловых операций |
| `SELECT * FROM users WHERE name = 'a;b'` | **block (ложное срабатывание)** | `;` внутри строкового литерала трактуется как multi-statement (B5, задокументированный tradeoff) |
| `UNRESTRICTED` уровень: `DROP TABLE users` | pass | by design |

MongoDB (`validate_mongo`):

| Спецификация | Решение |
|--------------|---------|
| `find` / `aggregate` (читающий pipeline) / `count` | pass |
| `insert` / `update` / `delete` / `drop` / `rename` / `create_index` / `drop_index` | block — «Write operation '…' not allowed in read-only mode» |
| невалидный JSON | block — «Invalid JSON query» |
| `aggregate` с `$out` / `$merge`; `find` с `$where` / `$function` | **pass (пробел)** — SafetyGuard этих конструкций не видит (B4); блокируются только коннекторным гардом `_assert_mongo_read_safe` (проверено живьём — блокируются) |

Дополнительно проверен byte-кап `cap_rows_by_bytes` (юнит-уровень, бюджет 1000 B на 20×100 B): вернул 10 строк, `truncated=True` — PASS.

## Детали по СУБД

### MySQL 8.0 (коннектор `backend/app/connectors/mysql.py`)

- Пул создаётся eager: `connect_timeout=30`, `init_command="SET SESSION TRANSACTION READ ONLY"` при `is_read_only` (mysql.py:64). Read-only подтверждён серверной ошибкой 1792 на все шесть типов записи; после серии попыток `COUNT(*)=10`.
- Интроспекция: `information_schema` тремя bulk-запросами; извлечены `enum('new','paid','cancelled')` (с default `new`), `decimal(10,2)`, `datetime`, `date`, PK (`id`), FK (`orders.user_id → users.id`), вторичные индексы (`idx_country`, `fk_orders_user`), view `paid_orders` с `object_kind="view"`, комментарий таблицы (`Пользователи e2e`).
- Стриминг через `SSDictCursor` + sentinel `MAX_RESULT_ROWS+1`: cross-join 12000 строк → 10000 + `truncated=True`, память не материализуется целиком.
- Таймаут: `asyncio.wait_for` вокруг fetch; после сработавшего таймаута пул остаётся здоровым (последующие `distinct_values`/`approx_stats` отработали корректно).
- Замечено при сидировании (не дефект продукта): `docker exec -i … mysql` без `--default-character-set=utf8mb4` в POSIX-локали поднимает сессию в latin1 и double-encod'ит UTF-8 на входе. Коннектор сам ходит в utf8mb4 (`aiomysql DEFAULT_CHARSET`) и с корректно записанными данными возвращает честный Unicode. Тестовые данные были пересидированы корректно.

### MongoDB 7 (коннектор `backend/app/connectors/mongodb.py`)

- **Все результаты ниже — с тестовым monkeypatch'ем** `AsyncIOMotorDatabase.__bool__ = lambda self: True` в тестовом процессе (симулирует фикс `self._db is None`), т.к. без него любой вызов падает (баг B1).
- `connect()` ленивый: неверный пароль не даёт ошибки на `connect()`, но `test_connection()` → False за 5 мс, а `execute_query` возвращает чистый `Authentication failed (code 18)` в `QueryResult.error` (не crash).
- Закрытый порт: ошибка через 10.1 с — ограничено `serverSelectionTimeoutMS=10_000` (mongodb.py:175). Бесконечного hang нет.
- Интроспекция: сэмпл 100 документов, union-типы (`balance: "Decimal128|int"`), вложенные пути до глубины 2 (`nested.level1.level2`), `_id` → PK, список индексов (`_id_`, `country_1`, `status_1`), `estimated_document_count`.
- Read-only app-гард (`_assert_mongo_read_safe`, mongodb.py:48-71): `insert/update/delete/drop` → «Write operation … not allowed»; `$out`/`$merge` → «Aggregation write stage … not allowed»; `$where`/`$function`/`$accumulator` → «Server-side JS operator … not allowed». Дополнительно: даже при `is_read_only=False` операция `insert` не реализована («Unsupported operation: insert») — write-пути через `execute_query` отсутствуют в принципе.
- Типы: `ObjectId` → hex-строка (включая reference-поле `ref_id`), `Decimal128` → `Decimal`, `datetime` и `list/dict` pass-through; вложенные документы рекурсивно коерсируются (`_to_jsonable`).
- Валидация спецификации: отсутствие `collection` → понятная ошибка; невалидное имя коллекции (`evil; DROP`) → отклонено regex'ом; невалидный JSON → чистая ошибка.
- Таймаут: `$where: sleep(5000)` (на non-RO коннекторе, сервер без `--noscripting`) с бюджетом 1 с → «Query timed out after 1s»; коннектор после таймаута полностью работоспособен.

### ClickHouse 24.8 (коннектор `backend/app/connectors/clickhouse.py`)

- `connect()` eager: `clickhouse_connect.get_client` выполняет `SELECT version(), timezone()` при создании клиента — невалидные креды/порт падают немедленно (1 мс), что удобно для fail-fast.
- `settings={"readonly":1}` (clickhouse.py:120): INSERT/DROP/ALTER/TRUNCATE/CREATE → `Code: 164. DB::Exception: Cannot execute query in readonly mode`; `COUNT()=10` после попыток.
- Интроспекция: `system.tables/columns/data_skipping_indices`; типы `Nullable(String)`, `Nullable(Decimal(12, 2))`, `Nullable(DateTime)` корректны; `is_sort_key=True` только у `id` (движок `MergeTree ORDER BY id`); комментарий таблицы извлечён.
- Стриминг `query_row_block_stream` с покаповым чтением блоков: `numbers(25000)` → 10000 строк + `truncated=True`.
- Параметры `{c:String}` работают через нативный механизм сервера.
- `SET max_threads=8` через `execute_query` завершается синтаксической ошибкой (`FORMAT Native` конфликтует с SET) — ожидаемо: драйвер только для query-формы; SafetyGuard SET и так блокирует (не в allowlist).
- **После таймаута коннектор клинит** — см. баг B2.
- EXPLAIN-фича: см. баг B3.

## Баги

### B1 — CRITICAL: MongoDB-коннектор неработоспособен с реальным motor: `if not self._db` бросает `NotImplementedError`

- Файлы: `backend/app/connectors/mongodb.py:212` (`execute_query`), `:319` (`introspect_schema`), `:387` (`sample_data`), `:413` (`distinct_values`), `:436` (`approx_stats`).
- Суть: `motor.AsyncIOMotorDatabase` (как и `pymongo.Database`) не реализует truth-value testing: `not db` бросает `NotImplementedError("Database objects do not implement truth value testing or bool(). Please compare with None instead")`. Проверка `if not self._db:` выполнена во всех пяти публичных методах, причём в `execute_query` — **до** блока `try`, поэтому исключение не конвертируется в `QueryResult.error`, а улетает необработанным в вызывающий код (500 на API-уровне).
- Окружение: `motor 3.7.1` (venv проекта; pyproject: `motor>=3.6.0`), pymongo из того же venv. Воспроизведено напрямую: `bool(AsyncIOMotorClient(...)[db])` → `NotImplementedError`.
- Воспроизведение: поднять любой Mongo, `MongoDBConnector().connect(cfg)`, затем `execute_query('{"collection":"users","operation":"find"}')` → `NotImplementedError` до отправки запроса. Падают ВСЕ операции MongoDB: запросы, индексация схемы, sample_data, W4-статистика.
- Почему не поймано тестами: `backend/tests/unit/test_mongodb_connector.py` подставляет `conn._db = _FakeDB(...)` — обычный Python-объект (truthy), поэтому `not self._db` в тестах не бросает; единственный тест с `None` проверяет только happy-path «нет подключения».
- Фикс: заменить все пять `if not self._db:` на `if self._db is None:`.
- Обход для продолжения аудита: monkeypatch `AsyncIOMotorDatabase.__bool__` в тестовом процессе (репозиторий не изменялся). Все остальные Mongo-результаты в этом отчёте получены с этим обходом.

### B2 — HIGH: ClickHouse-коннектор клинит после client-side таймаута

- Файл: `backend/app/connectors/clickhouse.py:174-196` (`execute_query`).
- Суть: запрос выполняется как `await asyncio.wait_for(asyncio.to_thread(_run_streaming), timeout=…)`. При срабатывании таймаута корутина отменяется, но поток с HTTP-стримом продолжает работать; сессионный лок `clickhouse_connect` остаётся занятым. Все последующие запросы того же коннектора падают с `Attempt to execute concurrent queries within the same session. Please use a separate client instance per thread/process` — до тех пор, пока исходный запрос не завершится **на сервере** (для тяжёлого скана это могут быть минуты; таймаут на стороне клиента серверный запрос не останавливает). Очистки/пересоздания клиента в коде нет.
- Воспроизведение: `SELECT sleep(3)` с `timeout_seconds=1` → «Query timed out after 1s»; следующие 4 `SELECT count() FROM users` подряд (с паузами 0.5 с) → все с ошибкой «concurrent queries within the same session». Через ~3 с (когда серверный `sleep` закончился) коннектор «оттаял».
- Усилитель последствий: `distinct_values`/`approx_stats` глушат ошибки и возвращают пустые значения — в прогоне аудита сразу после таймаута `distinct_values` вернул `[]`, `approx_stats` — пустую `ColumnStats()`, т.е. качество индекса схемы молча деградирует.
- MySQL и MongoDB такого эффекта не показали: после таймаута оба коннектора сразу работоспособны (проверено).
- Рекомендация: на `TimeoutError` закрывать/пересоздавать клиент (как `_reconnect` в MySQL) либо прерывать серверный запрос (`KILL QUERY` / закрытие HTTP-ответа в потоке).

### B3 — MEDIUM: EXPLAIN-warnings для ClickHouse — ложноположительное «full MergeTree scan» при WHERE по ключу

- Файл: `backend/app/core/explain_validator.py:133-142` (`_analyze_clickhouse`; запрос строится на `:58-59` как plain `EXPLAIN <query>`).
- Суть: эвристика ищет токены `prewhere`/`where` в тексте плана. Но plain `EXPLAIN` на CH 24.8 **никогда** не содержит эти слова: узел фильтра отображается безымянным `Expression`, а условие по ключу вообще прячется внутрь `ReadFromMergeTree`. Фактический план для `SELECT * FROM users WHERE id = 5`:
  ```
  Expression ((Project names + Projection))
    Expression
      ReadFromMergeTree (e2e.users)
  ```
  В итоге warning «full MergeTree scan with no PREWHERE/WHERE» срабатывает и на `WHERE id = 5` (key lookup), и на `WHERE name = '…'` (неиндексированная колонка), и на агрегации — критерий «предупреждение не возникает с WHERE» не выполняется, фича генерирует шум на любых запросах к MergeTree.
- Контрпример, как надо: `EXPLAIN indexes=1 … WHERE id = 5` показывает `PrimaryKey → Keys: id, Condition: (id in [5, 5]), Granules: 1/1` — из этого формата можно извлечь и наличие фильтра, и долю читаемых гранул.
- Воспроизведение: `ExplainValidator().validate(ch_connector, "SELECT * FROM users WHERE id = 5", "clickhouse")` → `warnings` содержит «full MergeTree scan…» (ожидалось: пусто).
- Рекомендация: строить запрос как `EXPLAIN indexes = 1 <query>` и анализировать секцию `Indexes:`/`Condition`/`Granules` вместо поиска слова «where».

### B4 — LOW: `SafetyGuard.validate_mongo` не блокирует `$out`/`$merge`/server-side JS

- Файл: `backend/app/core/safety.py:127-145`.
- Суть: `validate_mongo` проверяет только верхнеуровневое поле `operation` против write-ops. Агрегации с `$out`/`$merge` и фильтры с `$where`/`$function`/`$accumulator` проходят SafetyGuard (`is_safe=True`). Коннекторный гард `_assert_mongo_read_safe` (mongodb.py:48-71) их перехватывает — проверено живьём, end-to-end защита на read-only подключении работает. Но слои асимметричны: любой путь, валидирующий только через SafetyGuard и исполняющий на non-RO подключении, остаётся открытым. CLAUDE.md декларирует «каждый raw-SQL entry point проходит через SafetyGuard + коннекторный гард» — фактически гарантию даёт только второй.
- Рекомендация: вынести проверку write-stage/JS-операторов в общий модуль и вызывать из обоих слоёв (или переиспользовать `_assert_mongo_read_safe` в `validate_mongo`).

### B5 — LOW (by design): `;` внутри строкового литерала → ложное «multiple statements»

- Файл: `backend/app/core/safety.py:93-99`.
- `SELECT * FROM users WHERE name = 'a;b'` блокируется как multi-statement: проверка `";" in stripped` не различает литералы. Задокументированный tradeoff regex-подхода; для LLM-генерируемых read-запросов с текстовыми фильтрами по `;` это возможный источник ложных отказов. Severity низкая, т.к. перезапрос с экранированием возможен, а пофиксить корректно можно только полноценным токенизатором.

### B6 — LOW: семантическое расхождение `distinct_count` в Mongo `approx_stats`

- Файл: `backend/app/connectors/mongodb.py:428-486`.
- Mongo-реализация считает explicit `null` отдельным distinct-значением (`$addToSet`): `balance` → distinct=10, тогда как MySQL `COUNT(DISTINCT)` и CH `uniqExact` дают 9 (NULL игнорируется). Поле, отсутствующее в документе (missing), наоборот не учитывается ни как distinct, ни как null (`country` → distinct=7, null_rate=0.0 при одном документе без поля). Мелкое расхождение кросс-БД семантики W4-статистики; для индекса схемы некритично, но при сравнении метрик между БД даст разные числа.

## Прочие наблюдения (не дефекты)

- **Семантика `connect()` различается по диалектам**: MySQL и ClickHouse — eager (ошибки кредов/порта на `connect()`), MongoDB — lazy (ошибка на первой операции). Вызывающему коду нельзя полагаться на `connect()` как на валидацию кредов для Mongo; `test_connection()` закрывает этот кейс (False за 5 мс).
- **Пустой результат не несёт имён колонок**: у всех трёх коннекторов при 0 строк `columns=[]` (MySQL — из-за вывода имён из `rows[0].keys()`, CH — `stream.source.column_names` пуст до первого блока). Контракт согласованный, но потребителям метаданных пустой выборки нужно учитывать.
- **Косметика MySQL-интроспекции**: для view `TABLE_COMMENT='VIEW'` попадает в `TableInfo.comment` (значение-артефакт MySQL); у колонок view default `0` — тоже артефакт `information_schema`.
- **Таймаут Mongo на несуществующий хост** — 10.1 с (`serverSelectionTimeoutMS=10000`, mongodb.py:175): ограничен, но ощутим; для UI-валидации подключения это worst-case ожидание.
- **`UNRESTRICTED` уровень SafetyGuard** пропускает `DROP TABLE` — by design, проверено.

## Очистка выполнена

- Контейнеры `e2e-mysql-audit`, `e2e-mongo-audit`, `e2e-ch-audit` остановлены и удалены (`docker rm -f`), порты 13306/27018/18123/19000 освобождены. Подтверждение: `docker ps -a` не содержит контейнеров аудита (вывод зафиксирован ниже в логе прогона агента).
- Все подключения коннекторов закрыты (`disconnect()` в каждом тесте).
- Тестовые скрипты и JSON-выводы — в `/tmp/e2e-seed/` (вне репозитория).
- Изменённые файлы репозитория: только этот отчёт `docs/qa-audit/full-audit-2026-07-24/05-cross-db.md`. `backend/data/agent.db` не открывалась.
