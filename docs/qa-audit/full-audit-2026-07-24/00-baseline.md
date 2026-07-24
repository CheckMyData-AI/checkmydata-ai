# 00 — Baseline: фактическое состояние тестов и статического анализа

Дата прогона: 2026-07-24. Ветка `main`, коммит `e695caa` (2026-07-19). Окружение: Python 3.12.11 (venv), Node 26.4.0.

## Результаты прогонов

| Проверка | Результат | Детали |
|---|---|---|
| Backend unit + integration (pytest) | **PASS** | **5439 passed, 4 skipped, 2 xfailed**, 0 failed, 251 s |
| Backend coverage (combined) | **77.74%** | gate 72% — пройден; XML: `backend/build/coverage-2026-07-24.xml` |
| Frontend Vitest | **PASS** | 75 файлов, **526 passed**, 0 failed, ~5 s |
| Ruff check | PASS | 0 нарушений |
| Ruff format --check | PASS | 775 файлов |
| Mypy (`app/ --ignore-missing-imports`) | PASS | 0 ошибок; 4 `annotation-unchecked` notes (`connectors/clickhouse.py:284`, `knowledge/vector_store.py:124`, `api/routes/chat.py:923,947`) |

Расхождение с документацией: фактические цифры (5439 backend при полном прогоне / 526 frontend) выше всех заявленных (README «5,107 total», CLAUDE.md «~5,880», MASTER_TEST_PLAN «2,897 + 346»).

## Модули с наименьшим покрытием (кандидаты на усиление тестов)

| Модуль | Покрытие |
|---|---|
| `app/services/default_rule_template.py` | 29% |
| `app/services/session_summarizer.py` | 34% |
| `app/services/billing_service.py` | 49% |
| `app/services/trace_persistence_service.py` | 52% |
| `app/worker.py` | 56% |
| `app/models/base.py` | 48% |
| `app/services/rag_feedback_service.py` | 60% |
| `app/services/daily_knowledge_sync_service.py` | 70% |
| `app/services/knowledge_catalog_service.py` | 70% |
| `app/services/suggestion_engine.py` | 72% |
| `app/services/indexing_artifacts.py` | 72% |

Billing/trace-persistence/worker — низкое покрытие в критичных контурах (деньги, наблюдаемость, фоновые задачи). Это коррелирует с находкой Фазы 1: у billing нет HTTP-тестов роутов checkout/portal/webhook.

## Skip/xfail-маркеры

7 штук, все обоснованные: 2 xfail в `test_data_gate.py`, skipif по внешним зависимостям (git binary и пр.), 2 skip «out of W2 scope» в `test_w2_low_batch.py`.

## Вывод

Заявления о «зелёном CI» подтверждаются полным локальным прогоном: 0 падений, lint/format/mypy чисто, coverage выше gate. Тестовая база здоровая; дыры — не в количестве тестов, а в их распределении (billing, worker, trace persistence) и в отсутствии E2E-уровня.
