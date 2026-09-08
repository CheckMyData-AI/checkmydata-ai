# T03 · P1 — generate_docs: кэш по content_hash + модель per doc_type

**Цель:** force_full-пересборка перестаёт платить LLM за документы, чей исходник не
изменился; миграции (535 из 759 доков) описываются дешёвой моделью.
Ожидаемый эффект: force_full 12 039–12 329 с → ~3 500 с; −70–90% токенов пересборки
(сейчас 1,7–2,0M токенов ≈ $2–3 за прогон). Оценка: 1,5–2 дня. Ветка `feat/T03-doc-cache`.

## Почему сейчас дорого (receipts)

- Шаг: `app/knowledge/pipeline_runner.py:969` (`--- Step 9: generate_docs ---`).
- Skip-условия в цикле (`:1063+`): только `edoc.file_path in processed_paths`
  (чекпойнт ЭТОГО прогона) и binary-контент. **Хэша исходника нет** — на force_full
  каждый док идёт в `_generate_one_doc` → LLM (`:1034-1050`).
- force_full запускается честно и регулярно: смена `GRAPH_EXTRACTION_SCHEMA` /
  `SYMBOL_UID_SCHEMA` / embedding-конфига (см. CLAUDE.md, embedding_reconcile) — то есть
  каждый структурный фикс экстрактора заново оплачивает 9 375 с LLM-доков, хотя
  содержимое миграций не менялось месяцами.
- Модель: одна на всё — `project.indexing_llm_provider/model` (`:1045-1046`).
- Инкрементальный путь уже дёшев (schedule avg 996 с) — цель именно force_full.

## Дизайн

### Ключ кэша
`sha256(edoc.content + "\x00" + edoc.doc_type + "\x00" + enrichment_context + "\x00" + DOC_GEN_SCHEMA)`.
`DOC_GEN_SCHEMA: int` — новая константа рядом с генератором доков: бампается при смене
промпта/формата документа и инвалидирует кэш. **Намеренно НЕ входит в
`embedding_fingerprint()`** — проверить грепом, что не вошла: смена промпта доков не
должна вызывать пере-эмбеддинг всего проекта (и наоборот — бамп UID-схем не должен
инвалидировать доки, поэтому хэш не содержит commit_sha).

### Хранение
Колонка `content_hash: String(80) | NULL` на `knowledge_docs`
(модель `app/models/knowledge_doc.py:11-26`). Миграция — РУКАМИ, одна операция,
по образцу `alembic/versions/f6a7b8c9d0e1_*` (autogenerate выдал 252 операции —
CONVENTIONS §1). NULL у старых строк = «хэш неизвестен» → первый прогон после деплоя
регенерирует и заполняет; второй force_full уже дешёвый. Backfill не нужен.

### Skip-путь (в цикле Phase 1, до постановки LLM-задачи)
```
existing = existing_docs_map_full.get(edoc.file_path)   # прогретая map: path -> (content, content_hash)
if existing and existing.content_hash == computed_hash:
    reuse: обновить commit_sha/updated_at строки (touch), skipped_cached += 1; continue
```
Важно: сейчас `existing_docs_map` грузится только при `is_incremental`
(`pipeline_runner.py:980-983`) — грузить всегда (обе ветки), это один SELECT.
Embedding не трогаем: reuse не меняет content → embedding_id остаётся валиден.

### Модель per doc_type
Новый конфиг `indexing_llm_model_by_doc_type: dict[str,str] = {}` (env JSON,
`backend/.env.example` + docstring). В `_generate_one_doc`: если для `edoc.doc_type`
есть переопределение — оно передаётся вместо `project.indexing_llm_model`. Дефолт пустой
= поведение не меняется; включение на проде — отдельный конфиг-шаг с записью в
`DELIBERATE` (CONVENTIONS §9). Рекомендация к включению: `{"migration": "<дешёвая>"}`.

## Подзадачи
1. **Тесты first** (`tests/unit/knowledge/test_doc_generation_cache.py`):
   - хэш совпал → LLM НЕ вызван (mock generator, assert 0 calls), строка touched,
     counter reused растёт;
   - контент изменился → вызван; DOC_GEN_SCHEMA бампнут → вызван;
   - enrichment_context изменился → вызван;
   - старая строка с NULL-хэшем → вызван и хэш записан;
   - doc_type-модель: migration получает переопределение, orm_model — нет.
2. Константа + хэш-функция (чистая, отдельный модуль `app/knowledge/doc_cache.py` —
   тестируется без пайплайна).
3. Миграция + модель.
4. Врезка в цикл + always-загрузка map + touch-путь (batch, не по одной строке).
5. Конфиг модели + wiring.
6. Прогон гейтов; прод-верификация ниже.

## Наблюдаемость
- Счётчики: `docs_generated_total`, `docs_reused_total` (лейбл `doc_type`).
- В summary шага (`tracker.step` message) и `pipeline_end`: `generated=N reused=M`.
- Лог WARNING остаётся как был для fail-ratio (`generate_docs_max_failure_ratio`).

## Прод-верификация
Следующий force_full (можно спровоцировать НЕ бампая схем: ручной re-index с
`force_full=true` через UI): `pipeline_end` с `reused ≥ 700`, длительность < 4 500 с,
`token_usage` за день индекса < 400k токенов. Вывод — в PR.

## Rollback
Revert PR; колонка безвредна (NULL). Ловушка: НЕ удалять колонку downgrade'ом на проде
c данными — downgrade только для чистых сред.

## DoD
- [ ] Тесты 1 зелёные, полный набор зелёный, mypy/ruff чистые
- [ ] Миграция up→down→up на чистом SQLite, колонка проверена
- [ ] `embedding_fingerprint` НЕ содержит DOC_GEN_SCHEMA (grep в PR)
- [ ] CLAUDE.md: раздел deploy-notes про generate_docs дополнен кэшем; `.env.example`
- [ ] Прод-верификация приложена; леджер PLAN.md обновлён
