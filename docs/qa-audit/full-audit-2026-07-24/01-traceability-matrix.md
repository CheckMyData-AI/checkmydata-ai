# 01 — Матрица трассировки бизнес-логики

**Дата:** 2026-07-24 · **Фаза аудита:** 1 (traceability) · **Метод:** только статический анализ (Read/Grep/Glob); тесты и серверы не запускались.

**Источники истины:**
- `docs/ux/scenarios.md` — 112 сценариев (SCN-001..112) в 25 UX-доменах, все `implemented`, аудит 2026-07-19 PASS.
- `API.md` — REST-контракты (документирует ~110 эндпоинтов из 202).
- `backend/app/api/routes/` — 39 файлов с `@router`-декораторами (+`__init__.py`), **202 эндпоинта** (201 HTTP + 1 WebSocket); ещё 2 health-эндпоинта объявлены в `backend/app/main.py:1208,1225`. Итого 204 HTTP + 1 WS.
- `backend/tests/` — 419 файлов, **5343** функции `def test_` (статический подсчёт; CLAUDE.md заявляет 4865 unit + 543 integration — см. находку F-08).
- Префиксы роутеров — `backend/app/main.py:419-465`.

Количество тестов — приблизительное (сумма `def test_` по файлам, отнесённым к домену; часть файлов обслуживает несколько доменов). Оценка покрытия: **full** — сценарии + эндпоинты + сервисы + тесты на обоих уровнях; **partial** — есть значимые дыры (нет HTTP-тестов роутов, нет сценариев на часть поверхности); **thin** — только unit на движках, роуты не покрыты; **none** — покрытия нет.

## Сводка

| Оценка | Доменов | Список |
|---|---|---|
| full | 19 | auth, projects, members/invites, connections, ssh-keys, repos+индексация, chat+оркестратор, sql-agent+гейты, viz, knowledge/RAG, notes, learnings, rules, dashboards, batch, schedules+notifications, data-validation+investigations, mcp, tasks/runs, logs/traces |
| partial | 6 | onboarding, insights+feed+reconciliation, billing/entitlements, usage+metrics, demo, ops (health/backup/models) |
| thin | 1 | temporal/exploration/semantic-layer/data-graph |
| none | 0 | — |
| n/a (frontend-only) | 2 | settings, marketing |

## Матрица по доменам

### 1. auth — SCN-005..013
| | |
|---|---|
| Эндпоинты (13, `routes/auth.py`, prefix `/api/auth`) | POST `/register`, `/verify-email`, `/resend-verification`, `/forgot-password`, `/reset-password`, `/login`, `/google`, `/change-password`, `/refresh`, `/logout`; GET `/me`; POST `/complete-onboarding`; DELETE `/account` |
| Сервисы | `services/auth_service.py`, `services/email_service.py`, `services/encryption.py`, `api/deps.py`, `core/audit` |
| Тесты (~190) | unit: `test_auth_service.py` (34), `test_auth_cookies.py` (4), `test_password_reset.py` (10), `test_deps.py` (15), `test_audit.py` (5), `test_rate_limit.py` (5), `test_redis_backed_limits.py` (11); integration: `test_auth.py` (38), `test_auth_extended.py` (20), `test_auth_email_verification.py` (7), `test_password_reset.py` (9), `test_auth_cascade.py` (1), `test_security_rbac.py` (31) |
| Покрытие | **full** — все 9 сценариев имеют и эндпоинты, и тесты обоих уровней |

### 2. onboarding — SCN-001..004
| | |
|---|---|
| Эндпоинты | собственных нет; композиция: POST `/api/auth/complete-onboarding`, POST `/api/projects/access-requests` (projects.py:191), POST `/api/connections` + `/test` + `/index-db`, POST `/api/repos/check-access` + `/{pid}/index`, POST `/api/demo/setup` |
| Сервисы | `services/project_service.py` (readiness), `services/connection_service.py`, `routes/demo.py` |
| Тесты | выделенных нет; косвенно: `integration/test_demo_routes.py` (2), `test_connections.py`, unit `test_project_overview_service.py` (38) |
| Покрытие | **partial** — визард живёт во фронтенде; backend-шаги покрыты тестами соседних доменов, но сквозного onboarding-теста (register → connect → index → first question) нет |

### 3. projects — SCN-016..020
| | |
|---|---|
| Эндпоинты (14, `routes/projects.py`, `/api/projects`) | POST ``, POST `/access-requests`, GET ``, GET `/{id}`, PATCH `/{id}`, DELETE `/{id}`, GET `/{id}/readiness`, GET `/{id}/knowledge-health`, GET `/{id}/sync-history`, GET `/{id}/sync-schedule`, PUT `/{id}/sync-schedule`, POST `/{id}/sync-now`, GET `/{id}/runs`, GET `/{id}/pipeline-status` |
| Сервисы | `services/project_service.py`, `project_overview_service.py`, `project_cache_service.py`, `membership_service.py`, `pipeline_status_service.py`, `sync_history_service.py`, `sync_schedule_service.py`, `daily_knowledge_sync_service.py` |
| Тесты (~100) | integration: `test_projects.py` (17), `test_project_cache_failed_docs.py` (3), `test_sync_now_and_schedule.py` (4); unit: `test_project_service.py` (18), `test_project_overview_service.py` (38), `test_project_cache_service.py` (10), `test_pipeline_status_service.py` (3), `services/test_pipeline_status_runs.py` (3), `test_sync_history.py` (2), `api/test_sync_schedule.py` (3) |
| Покрытие | **full** — замечание: GET/PUT `/sync-schedule` и POST `/sync-now` не вызываются из UI (см. осиротевшие) |

### 4. members/invites — SCN-014..015, 021..024
| | |
|---|---|
| Эндпоинты (10, `routes/invites.py`, `/api/invites`) | POST `/{pid}/invites`, GET `/{pid}/invites`, DELETE `/{pid}/invites/{iid}`, POST `/{pid}/invites/{iid}/resend`, POST `/accept/{iid}`, POST `/decline/{iid}`, GET `/pending`, GET `/{pid}/members`, PATCH `/{pid}/members/{uid}`, DELETE `/{pid}/members/{uid}` |
| Сервисы | `services/invite_service.py`, `services/membership_service.py`, `services/email_service.py` |
| Тесты (~54) | integration: `test_invites.py` (19); unit: `test_invite_service.py` (21), `test_membership_service.py` (14) |
| Покрытие | **full** — замечание: `POST /decline/{iid}` и `PATCH /members/{uid}` (смена роли, SCN-022) отсутствуют в API.md |

### 5. connections — SCN-025..037
| | |
|---|---|
| Эндпоинты (19) | `routes/connections.py` (16, `/api/connections`): POST ``, GET `/project/{pid}`, GET `/{id}`, PATCH `/{id}`, DELETE `/{id}`, POST `/{id}/test`, POST `/{id}/test-ssh`, POST `/{id}/refresh-schema`, POST `/{id}/index-db`, GET `/{id}/index-db/status`, GET `/{id}/index-db`, DELETE `/{id}/index-db`, POST `/{id}/sync`, GET `/{id}/sync/status`, GET `/{id}/sync`, DELETE `/{id}/sync`. `routes/health_monitor.py` (3, смонтирован на `/api/connections`, main.py:426): GET `/{id}/health`, GET `/health`, POST `/{id}/reconnect` |
| Сервисы | `services/connection_service.py`, `db_index_service.py`, `code_db_sync_service.py`, `probe_service.py`, `core/health_monitor.py`, `connectors/` (pg/mysql/clickhouse/mongo, ssh_tunnel), `services/run_coordinator.py` |
| Тесты (~600) | unit: `test_connection_service.py` (46), `test_connection_lifecycle.py` (30), `test_db_index_service.py` (54), `services/test_db_index_service.py` (3), `test_code_db_sync_service.py` (46), `test_probe_service.py` (17), `test_schema_cache_registry.py` (8), `test_health_monitor.py` (14), `test_connectors.py` (40), `test_connectors_extended.py` (93), `test_mongodb_connector.py` (34), `test_db_index_pipeline.py` (59), `test_db_index_completeness.py` (17), `test_db_index_validator.py` (30), `test_schema_change_detector.py` (5) и др.; integration: `test_connections.py` (5), `test_connection_operations.py` (18), `test_ssh_exec_connections.py` (6), `test_sync_api.py` (7), run-lifecycle (2) |
| Покрытие | **full** — самый глубоко покрытый домен; см. находку F-06 о хрупком порядке монтирования health_monitor |

### 6. ssh-keys — SCN-038..040
| | |
|---|---|
| Эндпоинты (4, `routes/ssh_keys.py`, `/api/ssh-keys`) | POST ``, GET ``, GET `/{key_id}`, DELETE `/{key_id}` |
| Сервисы | `services/ssh_key_service.py`, `connectors/ssh_tunnel.py`, `connectors/ssh_pre_commands.py` |
| Тесты (~86) | unit: `test_ssh_key_routes.py` (9), `test_ssh_key_service.py` (20), `test_ssh_tunnel.py` (20), `test_ssh_pre_commands.py` (12), `test_ssh_known_hosts.py` (7), `test_ssh_exec_connector.py` (15); integration: `test_ssh_keys.py` (3) |
| Покрытие | **full** |

### 7. repos + индексация — SCN-061 (ч.), 062
| | |
|---|---|
| Эндпоинты (11, `routes/repos.py`, `/api/repos`) | POST `/check-access`, POST `/{pid}/index`, POST `/{pid}/webhook`, GET `/{pid}/status`, POST `/{pid}/check-updates`, GET `/{pid}/docs`, GET `/{pid}/docs/{doc_id}`, POST `/{pid}/repositories`, GET `/{pid}/repositories`, PATCH `/repositories/{id}`, DELETE `/repositories/{id}` |
| Сервисы/агенты | `services/repository_service.py`, `services/embedding_reindex.py`, `services/indexing_artifacts.py`, `services/run_coordinator.py`, `knowledge/pipeline_runner.py`, `indexing_pipeline.py`, `chunker.py`, `vector_store.py`, `git_tracker.py`, `doc_generator.py`, `repo_analyzer.py` |
| Тесты (~200) | unit: `test_repository_service.py` (10), `test_pipeline_runner.py` (20), `test_pipeline_graph_build.py` (4), `test_pipeline_runner_stale_gate.py` (3), `test_pipeline_chroma_failure_policy.py` (6), `test_indexing_pipeline.py` (11), `test_incremental_indexing.py` (10), `test_generate_docs_resilience.py` (8), `test_doc_generator.py` (16), `test_repo_analyzer.py` (23), `test_vector_store.py` (25), `test_git_tracker.py` (20+7), `knowledge/test_embedding_reindex.py` (9), `ops/test_embedding_reconcile.py` (6), `api/test_repo_index_run.py` (2); integration: `test_repo_operations.py` (12), `test_repo_check_access.py` (7), `test_indexing_e2e.py` (8), `test_embedding_reconcile_startup.py` (2) |
| Покрытие | **full** — дыра: `POST /{pid}/webhook` без сценария и UI (флаг `git_webhook_enabled` off) |

### 8. chat + оркестратор — SCN-041..051, 054..056
| | |
|---|---|
| Эндпоинты (17) | `routes/chat.py` (4, `/api/chat`): POST `/ask`, POST `/ask/stream`, POST `/ws-ticket`, WS `/ws/{pid}/{cid}`. `routes/chat_sessions.py` (7): POST `/sessions`, POST `/sessions/ensure-welcome`, GET `/sessions/{pid}`, PATCH `/sessions/{sid}`, POST `/sessions/{sid}/generate-title`, DELETE `/sessions/{sid}`, GET `/sessions/{sid}/messages`. `routes/chat_utility.py` (5): GET `/estimate`, GET `/search`, GET `/suggestions`, POST `/explain-sql`, POST `/summarize`. `routes/workflows.py` (1): GET `/events` (SSE, используется reasoning-панелью и live-логом, `frontend/src/lib/sse.ts:96,105`) |
| Агенты/сервисы | `agents/orchestrator.py`, `adaptive_planner.py`, `stage_executor.py`, `router.py`, `context_planner.py`, `context_loader.py`, `services/chat_service.py`, `chat_response_builder.py`, `session_summarizer.py`, `suggestion_engine.py`, `cost_estimation_service.py`, `checkpoint_service.py`, `core/workflow_tracker` |
| Тесты (~700) | unit: `test_orchestrator.py` (112), `test_agent.py` (41), `test_orchestrator_*.py` (50+), `test_router.py` (24), `test_stage_executor*.py` (58), `test_pipeline*.py` (60+), `test_checkpoint_service.py` (41), `test_session_rotation.py` (11), `test_history_trimmer.py` (18), `test_context_*.py` (66), `test_suggestion_engine.py` (22), `test_cost_estimation_service.py` (11), `test_chat_service.py` (41), `test_chat_response_builder.py` (17), `test_ws_chat_pipeline.py` (5), `test_ws_tickets.py` (9), `test_workflow_tracker.py` (29); integration: `test_chat.py` (13), `test_chat_extended.py` (21), `test_agent_chat.py` (18), `test_sse_flow.py` (6), `test_ws_auth.py` (4), `test_edge_cases.py` (12) |
| Покрытие | **full** — замечание: у SCN-043 (stop/abort) нет backend-cancel API чата, только клиентский abort (backend продолжает run — задокументировано в CLAUDE.md) |

### 9. sql-agent + гейты — ядро SCN-041, 046, 051, 052, 055
| | |
|---|---|
| Эндпоинты | собственных нет — работает внутри chat (оба пути: single-loop и pipeline) |
| Агенты | `agents/sql_agent.py`, `data_gate.py`, `result_validation.py`, `answer_validator.py`, `validation.py`, `query_planner.py`, `result_handler.py`, `sql_result_reconciliation.py`, `stage_validator.py`, `core/safety.py` |
| Тесты (~550) | unit: `test_sql_agent.py` (42), `agents/test_sql_agent_required_filters.py` (6), `agents/test_sql_agent_safety_net.py` (7), `test_sql_agent_result_gate.py` (4), `test_data_gate.py` (36+1), `test_result_validation.py` (19), `test_result_validation_both_paths.py` (8), `test_derive_result.py` (5), `test_answer_validator.py` (22+1), `test_pipeline_answer_gate.py` (9), `test_validation.py` (20), `test_validation_loop.py` (14), `test_query_planner.py` (18), `test_result_handler.py` (12), `test_sql_result_reconciliation.py` (13), `test_stage_validator*.py` (31), `test_required_filter_guard.py` (15), `test_safety*.py` (70), `test_sql_parser.py` (19), `test_sql_prompt.py` (29) и др.; integration: `test_validation_loop.py` (6) |
| Покрытие | **full** — гейты (DataGate, ResultValidation, AnswerQualityGate, SafetyGuard) покрыты на обоих путях исполнения |

### 10. viz — SCN-057..060
| | |
|---|---|
| Эндпоинты (2, `routes/visualizations.py`, `/api/visualizations`) | POST `/render`, POST `/export` |
| Агенты/сервисы | `agents/viz_agent.py`, `services/data_processor.py` |
| Тесты (~184) | unit: `test_viz.py` (69), `test_viz_agent.py` (20), `test_chart.py` (4), `test_chart_rules.py` (8), `test_data_processor.py` (75); integration: `test_visualizations.py` (8) |
| Покрытие | **full** |

### 11. knowledge/RAG — SCN-061, 063, 064
| | |
|---|---|
| Эндпоинты | собственных роутов нет; поверхность: GET `/api/projects/{id}/knowledge-health`, `/sync-history`, `/pipeline-status`, `/sync-now` (projects.py) + GET `/api/repos/{pid}/docs(/{doc_id})` |
| Сервисы/knowledge | `services/knowledge_freshness_service.py`, `knowledge_catalog_service.py`, `daily_knowledge_sync_service.py`, `sync_schedule_service.py`, `knowledge/hybrid_retriever.py`, `bm25_index.py`, `reranker.py`, `schema_retriever.py`, `context_pack*.py`, `retrieval_degradation.py`, `cross_source.py`, `vector_store.py` |
| Тесты (~200) | unit: `test_hybrid_retriever.py` (9), `knowledge/test_hybrid_retriever_degraded.py` (6), `test_bm25_index.py` (9), `test_reranker.py` (7), `test_retrieval_eval.py` (11), `test_retrieval_floor.py` (4), `test_retrieval_degradation.py` (1), `test_schema_retriever.py` (13), `knowledge/test_schema_retriever_fk.py` (14), `test_knowledge_freshness_service.py` (21+5), `test_knowledge_catalog_service.py` (9), `test_knowledge_catalog_rag.py` (10), `test_daily_knowledge_sync.py` (15), `test_daily_sync_single_flight.py` (2), `test_cross_source.py` (10), `knowledge/test_context_pack_renderer.py` (26), `agents/test_orchestrator_context_pack.py` (7), `test_context_budget.py` (23); integration: `test_schema_retriever_integration.py` (2), `test_daily_sync_run.py` (1), `test_daily_sync_child_runs.py` (1) |
| Покрытие | **full** |

### 12. insights + feed + reconciliation — SCN-065..067
| | |
|---|---|
| Эндпоинты (15) | `routes/insights.py` (7, `/api/insights`): GET `/{pid}`, GET `/{pid}/summary`, POST `/{pid}`, PATCH `/{pid}/{iid}/confirm`, `/dismiss`, `/resolve`, GET `/{pid}/actions`. `routes/feed.py` (4, `/api/feed`): POST `/{pid}/scan/{cid}`, `/{pid}/scan`, `/{pid}/opportunities/{cid}`, `/{pid}/losses/{cid}`. `routes/reconciliation.py` (4, `/api/reconciliation`): POST `/{pid}/row-counts`, `/values`, `/schemas`, `/full` |
| Агенты/движки | `agents/insight_feed_agent.py`, `core/insight_generator`, `core/reconciliation_engine`, `core/opportunity_detector`, `core/loss_detector`, `core/action_engine` |
| Тесты (~164) | unit: `test_insight_feed_agent.py` (62), `test_insight_generator.py` (13), `test_insight_feed_confidence.py` (3), `test_insight_reconcile_tz.py` (2), `test_reconciliation_engine.py` (19), `test_opportunity_detector.py` (11), `test_loss_detector.py` (11), `test_action_engine.py` (20), `test_periodic_insight_maintenance.py` (4); integration: `test_insights_api.py` (19) |
| Покрытие | **partial** — insights API покрыт полностью (SCN-065/066 + 19 integration); feed/reconciliation роуты не имеют ни HTTP-тестов, ни сценариев, ни UI-потребителей (см. находку F-02); «Investigate» drill-down из карточки не подключён (примечание в SCN-066 подтверждено: `startInvestigation` зовётся только из `WrongDataModal.tsx:109`) |

### 13. notes — SCN-053, 068..072
| | |
|---|---|
| Эндпоинты (6, `routes/notes.py`, `/api/notes`) | POST ``, GET ``, GET `/{id}`, PATCH `/{id}`, DELETE `/{id}`, POST `/{id}/execute` |
| Сервисы | `services/note_service.py`, `session_notes_service.py` |
| Тесты (~89) | unit: `test_note_service.py` (18), `test_session_notes_service.py` (32); integration: `test_notes.py` (17), `test_schedule_notes_routes.py` (22, ч.) |
| Покрытие | **full** |

### 14. learnings — SCN-073..076
| | |
|---|---|
| Эндпоинты (10, `routes/connection_learnings.py`, `/api/connections`) | GET `/{cid}/learnings`, GET `/{cid}/learnings/status`, GET `/{cid}/learnings/summary`, PATCH `/{cid}/learnings/{lid}`, DELETE `/{cid}/learnings/{lid}`, DELETE `/{cid}/learnings`, POST `/{cid}/learnings/recompile`, POST `/{cid}/learnings/validate-schema`, POST `/{cid}/learnings/{lid}/confirm`, POST `/{cid}/learnings/{lid}/contradict` |
| Сервисы | `services/agent_learning_service.py`, `services/rag_feedback_service.py`, `knowledge/learning_analyzer.py`, `agents/pipeline_learning.py` |
| Тесты (~201) | unit: `test_agent_learning_service.py` (104), `test_agent_learning_service_crud.py` (21), `test_learning_analyzer.py` (15), `test_learning_analyzer_extended.py` (18), `test_negative_feedback_contradiction.py` (6), `test_positive_feedback_application.py` (5), `test_rag_feedback_service.py` (7), `test_validation_learning_credit.py` (10); integration: `test_learnings_api.py` (11), `test_learnings_tenant_isolation.py` (4) |
| Покрытие | **full** — замечание: домен целиком отсутствует в API.md (находка F-03) |

### 15. rules — SCN-077..080
| | |
|---|---|
| Эндпоинты (5, `routes/rules.py`, `/api/rules`) | POST ``, GET ``, GET `/{id}`, PATCH `/{id}`, DELETE `/{id}` |
| Сервисы | `services/rule_service.py`, `default_rule_template.py`, `knowledge/custom_rules.py` |
| Тесты (~59) | unit: `test_rule_service.py` (17), `test_custom_rules.py` (16), `test_rule_validation.py` (7), `test_tool_dispatcher_manage_rules.py` (5); integration: `test_rules.py` (14) |
| Покрытие | **full** |

### 16. dashboards — SCN-081..086
| | |
|---|---|
| Эндпоинты (5, `routes/dashboards.py`, `/api/dashboards`) | POST ``, GET ``, GET `/{id}`, PATCH `/{id}`, DELETE `/{id}` |
| Сервисы | `services/dashboard_service.py` |
| Тесты (~31) | unit: `test_dashboard_service.py` (10); integration: `test_dashboard_routes.py` (21) |
| Покрытие | **full** — известный GAP зафиксирован в самом SCN-085 (invalid/expired/forbidden схлопываются в один экран) — это UX-долг, не backend-дыра |

### 17. batch — SCN-087..089
| | |
|---|---|
| Эндпоинты (5, `routes/batch.py`, `/api/batch`) | POST `/execute`, GET `/{id}`, GET ``, DELETE `/{id}`, POST `/{id}/export` |
| Сервисы | `services/batch_service.py` (+ `core/safety.py` на execute) |
| Тесты (~47) | unit: `test_batch_service.py` (21), `test_batch_routes.py` (7); integration: `test_batch_service.py` (10), `test_batch_routes.py` (9) |
| Покрытие | **full** — замечание: API.md противоречит коду (`POST /api/batch`, `GET /export` — на деле `/execute` и `POST /export`, см. F-03) |

### 18. schedules + notifications — SCN-090..093
| | |
|---|---|
| Эндпоинты (11) | `routes/schedules.py` (7, `/api/schedules`): POST ``, GET ``, GET `/{id}`, PATCH `/{id}`, DELETE `/{id}`, POST `/{id}/run-now`, GET `/{id}/history`. `routes/notifications.py` (4, `/api/notifications`): GET ``, GET `/count`, PATCH `/{id}/read`, POST `/read-all` |
| Сервисы | `services/scheduler_service.py`, `core/alert_evaluator` |
| Тесты (~78) | unit: `test_scheduler_service.py` (29), `test_alert_evaluator.py` (19); integration: `test_schedule_notes_routes.py` (22), `test_notification_routes.py` (4), `test_sync_now_and_schedule.py` (4) |
| Покрытие | **full** — замечание: у notifications нет отдельного сценария (колокольчик/центр уведомлений в scenarios.md не описан — дыра UX-документации, алерты покрыты косвенно через SCN-091) |

### 19. data validation + investigations — SCN-052, 094
| | |
|---|---|
| Эндпоинты (12) | `routes/data_validation.py` (7, `/api/data-validation`): POST `/validate-data`, GET `/validation-stats/{cid}`, GET `/benchmarks/{cid}`, GET `/analytics/{pid}`, GET `/summary/{pid}`, POST `/anomaly-analysis`, POST `/anomaly-scan/{cid}`. `routes/data_investigations.py` (3, тот же prefix): POST `/investigate`, GET `/investigate/{iid}`, POST `/investigate/{iid}/confirm-fix`. `routes/chat_feedback.py` (2, `/api/chat`): POST `/feedback`, GET `/analytics/feedback/{pid}` |
| Сервисы/агенты | `services/data_validation_service.py`, `investigation_service.py`, `feedback_pipeline.py`, `benchmark_service.py`, `query_failure_service.py`, `agents/investigation_agent.py`, `core/anomaly_intelligence` |
| Тесты (~199) | unit: `test_data_validation_service.py` (10), `test_feedback_pipeline.py` (6), `test_feedback_pipeline_unit.py` (31), `test_investigation_service.py` (17), `test_investigation_agent.py` (41), `test_investigation_budget_and_verdict.py` (8), `test_benchmark_service.py` (23), `test_anomaly_intelligence.py` (10), `test_query_failure_*.py` (12), `test_logs_query_failures_api.py` (9); integration: `test_feedback_loop.py` (3), `test_investigate_tenant_isolation.py` (4), `api/test_data_investigations_enrich.py` (1), `test_benchmark_service.py` (12), `test_api_coverage.py` (12, ч.) |
| Покрытие | **full** — но: GET `/summary/{pid}` и GET `/api/chat/analytics/feedback/{pid}` не вызываются из UI (F-01, F-04); anomaly-scan/analysis без сценария |

### 20. billing/entitlements — SCN-098..101
| | |
|---|---|
| Эндпоинты (5, `routes/billing.py`, собственный prefix `/billing` внутри роутера, billing.py:24 → `/api/billing`) | GET `/plans`, GET `/subscription`, POST `/checkout`, POST `/portal`, POST `/webhook` |
| Сервисы | `services/billing_service.py`, `entitlement_service.py`, `usage_service.py` (402-гейт `check_budget` в chat/MCP) |
| Тесты (~59) | unit: `test_billing.py` (17), `test_usage_service.py` (16), `test_token_budget_gate.py` (3), `test_usage_budget_helper.py` (4), `test_usage_sink.py` (7), `test_llm_router_usage.py` (6); integration: `test_usage_service.py` (6) |
| Покрытие | **partial** — сервисы и 402-гейт покрыты, но у billing-роутов нет HTTP-тестов (checkout/portal/webhook не прогоняются через API-клиент ни в unit, ни в integration) |

### 21. usage + metrics — SCN-102
| | |
|---|---|
| Эндпоинты (3) | `routes/usage.py` (1): GET `/api/usage/stats`. `routes/metrics.py` (2, prefix `/api`): GET `/api/metrics`, GET `/api/metrics/prometheus` (admin-only) |
| Сервисы | `services/usage_service.py`, `core/metrics.py` (MetricsCollector) |
| Тесты (~44) | unit: `test_usage_service.py` (16), `test_metrics.py` (5), `test_metrics_collector.py` (7), `test_metrics_w0_counters.py` (3), `test_metrics_diagnostics.py` (2); integration: `test_metrics_routes.py` (5), `test_usage_service.py` (6) |
| Покрытие | **partial** — usage full (SCN-102 + тесты); `/api/metrics*` без сценария (admin-ops, by design, но UX-документация этого не оговаривает) |

### 22. mcp server/client + tokens — SCN-103..104
| | |
|---|---|
| Эндпоинты (3, `routes/mcp_tokens.py`, `/api/auth`) | POST `/mcp-tokens`, GET `/mcp-tokens`, DELETE `/mcp-tokens/{token_id}`. Плюс MCP-сервер: отдельный ASGI в `app/mcp_server/` (mount `/mcp`, off by default) — не входит в 202 REST-эндпоинта |
| Сервисы | `services/mcp_key_service.py`, `mcp_server/`, `agents/mcp_source_agent.py` (client-side) |
| Тесты (~185) | unit: `test_mcp_key_service.py` (17), `test_mcp_tokens_routes.py` (7), `test_mcp_token_edge_cases.py` (19), `test_mcp_server.py` (44), `test_mcp_client.py` (20), `test_mcp_runtime.py` (3), `test_mcp_pipeline.py` (8), `test_mcp_asgi_app.py` (5), `test_mcp_asgi_auth.py` (6), `test_mcp_with_principal.py` (6), `test_mcp_tools_budget.py` (4), `test_mcp_structured_output.py` (10), `test_mcp_b3_cleanups.py` (11), `test_mcp_mount_wiring.py` (2), `test_mcp_server_startup.py` (3), `test_mcp_source_agent.py` (13); integration: `test_mcp_tools_usage.py` (6) |
| Покрытие | **full** — сценарии покрывают только токены; MCP tool surface (checkmydata_*) тестами покрыт, сценариев нет (api-consumer «работает вне UI» — оговорено в персоне) |

### 23. tasks/runs — SCN-105
| | |
|---|---|
| Эндпоинты (5) | `routes/tasks.py` (1): GET `/api/tasks/active`. `routes/runs.py` (4, `/api/runs`): POST `/{run_id}/cancel`, POST `/{run_id}/retry`, GET `/{run_id}`, GET `/{run_id}/events` (SSE прогресса RunCard/виджета) |
| Сервисы | `services/run_coordinator.py`, `stale_run_reaper.py`, `core/task_queue.py`, heartbeat/reaper |
| Тесты (~70) | unit: `test_task_queue.py` (10), `services/test_run_coordinator.py` (12), `test_run_coordinator_flag_snapshot.py` (4), `services/test_run_coordinator_hook.py` (2), `api/test_runs_cancel_retry.py` (3), `test_background_task_cancel.py` (2), `test_reaper_loop.py` (5), `test_stale_run_reaper.py` (6), `services/test_reaper_indexing_runs.py` (2), `test_heartbeat*.py` (10), `test_unique_job_ids.py` (3), `test_distributed_lock.py` (3); integration: `test_tasks_routes.py` (3), `test_task_routes.py` (2) |
| Покрытие | **full** |

### 24. logs/traces — SCN-106..108
| | |
|---|---|
| Эндпоинты (9, `routes/logs.py`, `/api/logs`) | GET `/{pid}/users`, GET `/{pid}/requests`, GET `/{pid}/requests/{trace_id}`, GET `/{pid}/summary`, GET `/{pid}/errors`, PATCH `/{pid}/errors/{error_id}`, GET `/{pid}/query-failures`, GET `/{pid}/query-failures/{failure_id}`, GET `/{pid}/runs`. Live-стрим SCN-108 — GET `/api/workflows/events` (sse.ts:105) |
| Сервисы | `services/logs_service.py`, `trace_persistence_service.py`, `error_log_service.py`, `telemetry_retention.py`, `core/workflow_tracker`, event ingestion |
| Тесты (~147) | unit: `test_logs_service.py` (10), `test_logs_routes.py` (5), `test_trace_persistence_service.py` (66), `services/test_logs_errors_runs.py` (3), `services/test_error_log_*.py` (2), `models/test_error_log_model.py` (1), `services/test_telemetry_retention.py` (2), `test_event_ingestion.py` (11), `test_workflow_tracker*.py` (33), `services/test_span_type_coverage.py` (1), `test_logs_query_failures_api.py` (9), `test_request_trace_routing_cols.py` (2) |
| Покрытие | **full** — замечание: query-failures пара эндпоинтов не имеет UI-потребителя (F-04) |

### 25. demo — SCN-003
| | |
|---|---|
| Эндпоинты (1, `routes/demo.py`, `/api/demo`) | POST `/setup` |
| Сервисы | `routes/demo.py` (in-memory sample DB через connection/project services) |
| Тесты (2) | integration: `test_demo_routes.py` (2); unit нет |
| Покрытие | **partial** — поверхность крошечная и покрыта пропорционально, но happy-path demo-визарда зависит от последующего indexing, что integration-тестом не проверяется |

### 26. temporal / exploration / semantic-layer / data-graph — SCN-067 (ч.)
| | |
|---|---|
| Эндпоинты (13) | `routes/temporal.py` (2, `/api/temporal`): POST `/{pid}/analyze`, `/{pid}/lag`. `routes/exploration.py` (1): POST `/api/explore/{pid}`. `routes/semantic_layer.py` (3, `/api/semantic-layer`): POST `/{pid}/build/{cid}`, POST `/{pid}/normalize`, GET `/{pid}/catalog`. `routes/data_graph.py` (7, `/api/data-graph`): GET `/{pid}/summary`, GET/POST `/{pid}/metrics`, GET/POST `/{pid}/relationships`, POST `/{pid}/discover/{cid}`, DELETE `/{pid}/metrics/{mid}` |
| Движки | `core/temporal_intelligence`, `core/exploration_engine`, `core/semantic_layer`, `core/data_graph` |
| Тесты (~64) | unit: `test_temporal_intelligence.py` (23), `test_exploration_engine.py` (21), `test_semantic_layer.py` (17), `core/test_data_graph_tenant_isolation.py` (3); integration: **нет** |
| Покрытие | **thin** — движки покрыты unit-тестами, роуты не имеют HTTP-тестов; UI зовёт только GET `/semantic-layer/{pid}/catalog` (SCN-067, KnowledgeHub.tsx:50); остальные 12 эндпоинтов без потребителей (F-02). data-graph и semantic-layer — параллельные реализации «каталога метрик» (F-05) |

### 27. ops: health / backup / models — сценариев нет
| | |
|---|---|
| Эндпоинты (6) | GET `/api/health`, GET `/api/health/modules` (main.py:1208,1225); `routes/backup.py` (3, `/api/backup`): POST `/trigger`, GET `/list`, GET `/history`; `routes/models.py` (1): GET `/api/models` |
| Сервисы | `core/backup_manager`, `llm/router.py` (каталог моделей) |
| Тесты (~64) | unit: `test_health_monitor.py` (14), `test_backup_manager.py` (5), `test_backup_manager_extended.py` (20), `test_models_routes.py` (11); integration: `test_health.py` (2), `test_backup_routes.py` (7), `test_models.py` (5) |
| Покрытие | **partial** — тесты хорошие, сценариев нет; `/api/models` при этом имеет UI-потребителя (`LlmModelSelector.tsx:49`) — выбор LLM-модели вообще не описан в scenarios.md (дыра UX-документации) |

### 28. settings — SCN-095..097 — n/a (frontend-only)
Тема и reduced-motion не трогают backend; композитная навигация (SCN-095) покрыта доменами auth/projects/invites/mcp-tokens.

### 29. marketing — SCN-109..112 — n/a (frontend-only)
Статические страницы + AuthRedirect; backend не требуется по дизайну.

---

## Осиротевшие эндпоинты

Эндпоинты, не привязанные ни к одному SCN из scenarios.md. Разбиты по тяжести.

### A. Нет ни сценария, ни UI-потребителя (кандидаты на «мёртвый REST» или явное документирование как public API) — 28 шт.

| Эндпоинт | Файл:строка | Комментарий |
|---|---|---|
| POST `/api/feed/{pid}/scan/{cid}` | feed.py:18 | Клиент `analytics.ts:304` определён, не вызывается |
| POST `/api/feed/{pid}/scan` | feed.py:46 | то же |
| POST `/api/feed/{pid}/opportunities/{cid}` | feed.py:94 | то же |
| POST `/api/feed/{pid}/losses/{cid}` | feed.py:209 | то же |
| POST `/api/reconciliation/{pid}/row-counts` | reconciliation.py:120 | Клиент есть, вызовов нет; `ReconciliationCard.tsx` нигде не рендерится |
| POST `/api/reconciliation/{pid}/values` | reconciliation.py:152 | то же |
| POST `/api/reconciliation/{pid}/schemas` | reconciliation.py:184 | то же |
| POST `/api/reconciliation/{pid}/full` | reconciliation.py:216 | то же |
| POST `/api/temporal/{pid}/analyze` | temporal.py:42 | `TemporalReport.tsx` нигде не рендерится |
| POST `/api/temporal/{pid}/lag` | temporal.py:59 | то же |
| POST `/api/explore/{pid}` | exploration.py:23 | `ExplorationReport.tsx` нигде не рендерится |
| GET `/api/data-graph/{pid}/summary` | data_graph.py:86 | namespace `dataGraph` не вызывается |
| GET `/api/data-graph/{pid}/metrics` | data_graph.py:97 | то же |
| POST `/api/data-graph/{pid}/metrics` | data_graph.py:129 | то же |
| GET `/api/data-graph/{pid}/relationships` | data_graph.py:161 | то же |
| POST `/api/data-graph/{pid}/relationships` | data_graph.py:186 | то же |
| POST `/api/data-graph/{pid}/discover/{cid}` | data_graph.py:213 | то же |
| DELETE `/api/data-graph/{pid}/metrics/{mid}` | data_graph.py:230 | то же |
| POST `/api/semantic-layer/{pid}/build/{cid}` | semantic_layer.py:23 | UI зовёт только `catalog` |
| POST `/api/semantic-layer/{pid}/normalize` | semantic_layer.py:46 | то же |
| GET `/api/data-validation/summary/{pid}` | data_validation.py:259 | клиент `getAnalyticsSummary` (analytics.ts:80) не вызывается |
| GET `/api/chat/analytics/feedback/{pid}` | chat_feedback.py:468 | дубль аналитики, UI использует data-validation вариант (F-01) |
| POST `/api/data-validation/anomaly-analysis` | data_validation.py:334 | клиент определён, не вызывается |
| POST `/api/data-validation/anomaly-scan/{cid}` | data_validation.py:360 | то же |
| GET `/api/logs/{pid}/query-failures` | logs.py:172 | 9 unit-тестов есть, UI-вызова нет (F-04) |
| GET `/api/logs/{pid}/query-failures/{fid}` | logs.py:202 | то же |
| POST `/api/repos/{pid}/webhook` | repos.py:361 | флаг `git_webhook_enabled` off by default |
| GET `/api/projects/{pid}/sync-schedule` + PUT | projects.py:501,525 | UI-вызова нет; тесты есть (`api/test_sync_schedule.py`) |

### B. Нет сценария, но есть UI-потребитель (дыра UX-документации) — 5 шт.

| Эндпоинт | Потребитель |
|---|---|
| GET `/api/models` | `LlmModelSelector.tsx:49` — выбор LLM-модели не описан ни одним SCN |
| POST `/api/repos/{pid}/check-updates` | `Sidebar.tsx:183` (бейдж обновлений репо; ближайший SCN-063 про freshness это не покрывает явно) |
| GET `/api/notifications` + `/count` + PATCH read + POST read-all | центр уведомлений/колокольчик — сценария нет (только косвенно SCN-091 про алерты) |

### C. Ops/admin по дизайну без сценариев — 5 шт.

GET `/api/metrics`, GET `/api/metrics/prometheus` (admin), POST `/api/backup/trigger`, GET `/api/backup/list`, GET `/api/backup/history`. Осмысленно оставить вне scenarios.md, но стоит явно пометить в документе как out-of-scope.

**Итого осиротевших: ~38 из 204 (~19%).**

## Осиротевшие сценарии

Сценарии без явного backend-покрытия:

| Сценарий | Статус backend |
|---|---|
| SCN-096 (тема) | backend не требуется — `theme-store`/`ThemeWatcher`, чистый фронтенд |
| SCN-097 (reduced-motion) | backend не требуется — CSS/MotionConfig |
| SCN-109..112 (marketing) | статические страницы; единственный backend-штрих — `/api/auth/me` при авто-редиректе |
| SCN-095 (settings-навигация) | композитный; backend через домены auth/projects/invites/mcp-tokens |
| SCN-043 (stop/abort) | реализован клиентским abort SSE; backend-cancel API для chat-run отсутствует — run продолжается на сервере (поведение задокументировано в CLAUDE.md «backend continues processing», но в scenarios.md это не отражено) |

Все остальные 105 сценариев имеют явный backend-след (эндпоинт + сервис + тесты).

## Находки бизнес-логики

**F-01. Дублирующиеся эндпоинты аналитики фидбека.** Два разных backend-агрегата под одним именем `getFeedbackAnalytics`: `backend/app/api/routes/chat_feedback.py:468` (GET `/api/chat/analytics/feedback/{project_id}`, агрегирует `ChatMessage.user_rating`) и `backend/app/api/routes/data_validation.py:145` (GET `/api/data-validation/analytics/{project_id}`, агрегирует verdict-ы валидаций + learnings + benchmarks). Во фронтенде оба названы `getFeedbackAnalytics` — `frontend/src/lib/api/chat.ts:75` и `frontend/src/lib/api/analytics.ts:88`. UI использует только data-validation вариант (`FeedbackAnalyticsPanel.tsx:41-42`); chat-вариант мёртв. Два источника «правды» о качестве ответов могут расходиться.

**F-02. Мёртвая «intelligence» REST-поверхность (~17 эндпоинтов + мёртвые UI-компоненты).** feed/temporal/explore/reconciliation/data-graph/semantic-layer-build: клиентские namespaces определены (`frontend/src/lib/api/analytics.ts:254-483`), но ни один компонент их не вызывает (проверено grep по `frontend/src`); компоненты `TemporalReport.tsx`, `ReconciliationCard.tsx`, `ExplorationReport.tsx` экспортируются, но нигде не рендерятся. Движки при этом живы — достигаются через chat-инструменты оркестратора. Либо это недовключённый UI (roadmap), либо мёртвый код на both ends; HTTP-тестов роутов нет.

**F-03. API.md существенно отстаёт от кода.** Документировано ~110 из 202 эндпоинтов. Целиком пропущены: learnings (10), runs (4), логовые errors/query-failures/runs (5 из 9), chat_utility search/summarize/explain-sql, chat_sessions create/PATCH/ensure-welcome/generate-title, projects access-requests/sync-schedule/sync-now/runs, connections test-ssh + GET/DELETE index-db + GET/DELETE sync, invites decline + PATCH member-role, notes GET/{id}/execute, rules GET/{id}, repos webhook/check-updates/status. Прямые противоречия: API.md `POST /api/batch` vs код `POST /api/batch/execute` (`batch.py:57`); API.md `GET /api/batch/{id}/export` vs код `POST /api/batch/{id}/export` (`batch.py:173`).

**F-04. query-failures API без потребителя.** `logs.py:172,202` + клиент (`analytics.ts:189-211`) + 9 unit-тестов (`test_logs_query_failures_api.py`) — но ни один компонент не вызывает методы; в LogsScreen три вкладки (Queries/Runs/Errors, SCN-106/107), failures-вкладки нет. Либо недоделанная фича, либо лишний код.

**F-05. Две параллельные реализации «каталога метрик».** `routes/semantic_layer.py` (catalog/build/normalize) и `routes/data_graph.py` (metrics/relationships/discover) моделируют одно и то же понятие; UI (SCN-067) читает только semantic-layer catalog (`KnowledgeHub.tsx:50`), data-graph полностью без потребителей. Рассинхрон определений метрик между двумя хранилищами — риск для insights/reconciliation, которые читают метрики.

**F-06. Хрупкий порядок монтирования health_monitor.** `health_monitor.router` (без собственного prefix, `health_monitor.py:17`) включён в `/api/connections` ДО основного connections-роутера (`main.py:426-427`). GET `/api/connections/health` (`health_monitor.py:45`) резолвится корректно только из-за порядка include; перестановка строк отдаст путь под `GET /api/connections/{connection_id}` (`connections.py:471`) с connection_id="health" → 404. Нет теста, фиксирующего этот порядок.

**F-07. MCP-токены живут под `/api/auth`, хотя выделены в отдельный роутер.** `mcp_tokens.router` монтируется с prefix `/api/auth` (`main.py:420`) — публичный контракт `/api/auth/mcp-tokens` смешивает auth-домен с MCP-доменом; в API.md это задокументировано в разделе Authentication, а в коде — отдельный файл. Не баг, но путаница при трассировке (SCN-103/104 относятся к mcp-tokens, а путь — auth).

**F-08. Дрейф заявленного числа тестов.** CLAUDE.md: «4,865 backend unit + 543 integration» (=5408). Статический подсчёт `def test_` по `backend/tests/`: 5343 (включая smoke). Расхождение ~65 — вероятно устаревшие числа в CLAUDE.md (либо параметризованные/динамические тесты). Стоит обновить CLAUDE.md по факту прогона.

**F-09. Центр уведомлений и выбор LLM-модели — user-facing фичи вне scenarios.md.** Notifications API (4 эндпоинта, колокольчик) и `LlmModelSelector` (GET `/api/models`) имеют UI, тесты и пользовательское поведение, но ни одного SCN — прямое нарушение hard-rule «scenarios.md is source of truth for all user-facing behavior» (CLAUDE.md §UX scenarios).

**F-10. Onboarding — единственный сквозной новопользовательский путь без сквозного backend-теста.** Шаги SCN-001 (register → create connection → test → index-db → optional repo → first ask) по отдельности покрыты, но связующего integration-теста нет; регрессия в стыке (например, auto-test → auto-advance → index trigger) будет поймана только фронтенд-тестами визарда.
