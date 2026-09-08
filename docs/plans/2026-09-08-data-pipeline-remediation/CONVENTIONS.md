# Конвенции исполнения — читать до первого коммита

Всё ниже — не общие пожелания, а правила, о которые в этом репозитории УЖЕ спотыкались,
с датой и следом. Пакеты на них ссылаются.

## Гейты (перед каждым PR, локально)

```bash
cd backend
.venv/bin/ruff format --check app/ tests/ && .venv/bin/ruff check app/ tests/
.venv/bin/mypy app/ --ignore-missing-imports          # ожидание: 0 errors
PYTHONPATH=. .venv/bin/pytest tests/unit -q           # полный юнит-набор, не только свой
PYTHONPATH=. .venv/bin/pytest tests/integration -q
cd ../frontend && npx tsc --noEmit && npx eslint . --max-warnings=0 && npx vitest run  # если трогал фронт
make ux-status   # ТОЛЬКО ПОСЛЕ git add — см. Ловушки №4
```

CI-гейт покрытия: combined `coverage report --fail-under=80`. Не добавлять per-step floor.

## Ловушки (каждая уже случалась)

1. **Alembic autogenerate — мусор.** Против прод-схемы он предложил 252 операции
   (2026-09-08). Миграции писать руками, одну операцию, по образцу
   `alembic/versions/e5f6a7b8c9d0_*.py`; проверять `upgrade → downgrade → upgrade` на
   чистом SQLite. Автосгенерированные файлы ruff'ом не переформатировать (per-file ignore).
2. **Suppression-ратчеты.** Новый `except Exception` или `# type: ignore` роняет
   `tests/unit/docs/test_suppression_debt_ratchet.py`. Поднимать потолок в ТОМ ЖЕ коммите
   с обоснованием в комментарии рядом с числом — образцы в файле.
3. **Загрузчик промпта, деградирующий в "" — логирует WARNING.**
   `test_prompt_loaders_report_their_failures_at_warning` ловит `logger.debug` (поймал
   2026-09-08). Пустая секция для агента неотличима от «данных нет».
4. **`make ux-status` — только после `git add`.** Счётчик «Referenced from code or tests»
   читает `git grep` (только tracked). Сгенерированный до add блок разойдётся с таблицей,
   и `test_the_block_agrees_with_the_table_it_summarises` упадёт на невиновном дереве.
5. **Грепающий тест читает КОД, не прозу.** Срезать docstrings/комментарии до assert —
   иначе тест наказывает за документирование правила рядом с его применением (два случая
   2026-09-08). И он не заменяет исполнение: `NameError` в роуте грепом не ловится —
   парный integration-тест обязателен (образец: `tests/integration/test_sync_schedule_may_run.py`).
6. **Фронтовый `<select>` — только `className={selectBaseCls}`**, ширина обёрткой
   (`pack-bans.test.ts`). Иконки — только `PATHS` в `components/ui/Icon.tsx`.
7. **Производное поле ответа — `@computed_field`, не field+validator**: обычное поле
   читается из source-объекта ДО валидатора (поймано 2026-09-08 на `capability`).
   `# type: ignore[prop-decorator]` — документированный обход pydantic, см. образец там же.
8. **Сценарии — в том же PR.** Любое user-facing поведение обновляет
   `docs/ux/scenarios.md` (id с конца, `draft` без даты аудита в индексе — история в теле).
9. **Config-drift.** Новый env на Heroku, отличный от дефолта config.py, регистрируется
   в `DELIBERATE` map `scripts/config_drift.py` в том же изменении (`make config-drift`
   обязан остаться зелёным).
10. **Бюджеты текста в промпт** — в одном доме, у builder-функции; целые записи, never
    половина; опущенное — названо. Образец: `app/agents/source_purpose.py` (и его тест
    на «фикс. заголовок не ест бюджет вызывающего»).

## Наблюдаемость — правила именования

- Счётчики Prometheus: `<area>_<thing>_total`, лейблы с малой кардинальностью
  (образцы: `retrieval_degraded_total{leg,reason}`, `datagate_block_total`).
- Деградация — WARNING с именем пустеющей секции; успех проверки тоже логируется
  (образец: capability_report — «тишина не читается как пройденная проверка»).
- Порог/потолок: логировать не только превышение, но и приближение (доля в пакете задана).

## Прод-доступ для верификации

БД: `heroku config:get DATABASE_URL -a checkmydata-api` → asyncpg
(`statement_cache_size=0` — Supavisor session mode). Логи: `heroku logs -n … -a
checkmydata-api`. Релизы: `heroku releases`. Прод-мутирующие шаги — только те, что явно
названы в пакете, с фиксацией вывода в PR.

## Коммиты

Conventional commits; тело объясняет ПОЧЕМУ с числами из пакета; трейлер
`Co-Authored-By:` по текущей модели агента. Ветка `feat|fix/T0x-slug`. Squash-merge.
