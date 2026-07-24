# Фаза 3.7 — Security-аудит

Дата: 2026-07-24. Версия проекта: 1.15.1. Backend: FastAPI, Python 3.12.11 (`backend/.venv`). Frontend: Next.js 15.5.12.

Метод: статический анализ кода + `pip-audit 2.10.1` (venv) + `npm audit`. Серверы не запускались, файлы репозитория не изменялись (кроме этого отчёта). Значения секретов нигде не печатались.

> **Зафиксированное изменение окружения:** в `backend/.venv` отсутствовал `pip` — для прогона аудита он был установлен через `ensurepip` (pip 25.0.1), затем `pip install pip-audit` (2.10.1), как было разрешено рамками фазы. Найденные уязвимости пакета `pip` (см. ниже) — артефакт этой установки, а не зависимость проекта.

## Сводка по severity

| Severity | Кол-во |
|----------|--------|
| Critical | 0 |
| High | 3 |
| Medium | 5 |
| Low | 5 |
| Info | 4 |

## Таблица находок

| # | Severity | Область | Описание | Evidence | Рекомендация |
|---|----------|---------|----------|----------|--------------|
| S-01 | High | SSRF / git | `validate_repo_url` ограничивает транспорт (https/http/ssh/scp-like), блокирует `ext::`/`fd::`/`file://` и option-injection, но **не блокирует loopback/внутренние хосты** (`127.0.0.1`, `localhost`, `169.254.169.254`, RFC1918, IPv6 link-local). Аутентифицированный пользователь может заставить сервер выполнять `git ls-remote`/`git clone` к внутренним адресам (сканирование портов по различиям ошибок/timing, доступ к metadata-endpoint при развёртывании в облаке). Подтверждает находку более раннего аудита. | `backend/app/knowledge/repo_url.py:47-66` | После разбора URL резолвить хост и отклонять loopback/private/link-local/metadata адреса (с учётом DNS-rebinding — резолвить и пинить IP на время операции); заодно рассмотреть запрет `http://` (только https/ssh). |
| S-02 | High | Frontend deps | `next@15.5.12` в уязвимом диапазоне `9.3.4-canary.0 – 16.3.0-preview.7`: **HTTP request smuggling in rewrites** (GHSA-ggv3-7p47-pfv8). Пакет в prod-зависимостях. | `frontend/node_modules/next/package.json`; `npm audit --omit=dev` | `npm audit fix` / обновить Next.js до ≥ 16.3.0 (или patched-релиз 15.x согласно advisory). |
| S-03 | High | Конфигурация секретов | On-disk `.env.local` (корень, используется docker-compose) содержит `JWT_SECRET=change-me-in-production` (дефолт) и `DEBUG=true`, а `ENVIRONMENT` не задан. Production-валидатор при этом **не сработает** (см. S-04): если этот файл уедет в реальное развёртывание, получим дефолтный JWT-секрет + debug. Файл в git не трекается (`.gitignore:23`). `backend/.env` — JWT_SECRET переопределён (недефолтный), DEBUG=true. | `.env.local` (grep-совпадение дефолта), `backend/app/config.py:100` | Задать сильный `JWT_SECRET` в `.env.local`; явно проставить `ENVIRONMENT` в каждом env-файле; для docker-compose добавить обязательную проверку `ENVIRONMENT`/`JWT_SECRET` при старте (fail fast). |
| S-04 | Medium | Auth/JWT конфигурация | Расхождение дизайна и поведения production-guard'а: комментарий декларирует fail-closed («unset/empty ENVIRONMENT = production»), но pydantic-дефолт `environment: str = "development"` входит в `_SAFE_ENVIRONMENTS` — **неустановленный ENVIRONMENT молча трактуется как development**, и проверки секретов (JWT, MASTER_ENCRYPTION_KEY, DEBUG, CORS `*`) пропускаются. | `backend/app/config.py:51-55` (комментарий) vs `config.py:62` (дефолт), `config.py:773-808` (валидатор) | Сделать `environment` обязательным без дефолта (или дефолт `"production"` с явным opt-in в dev), чтобы unset действительно fail-closed. |
| S-05 | Medium | Backend deps | Уязвимые зависимости backend (pip-audit, 9 уникальных ID в 5 пакетах проекта): `gitpython 3.1.50` — GHSA-2f96-g7mh-g2hx, GHSA-v396-v7q4-x2qj, GHSA-956x-8gvw-wg5v (fix **3.1.51**); `mcp 1.27.2` — PYSEC-2026-3483 / CVE-2026-59950 (fix **1.28.1**); `pyasn1 0.6.3` — CVE-2026-59884/59885/59886 (fix **0.6.4**); `chromadb 1.5.9` — PYSEC-2026-311 / CVE-2026-45829 (**fix-версии нет**); `ecdsa 0.19.2` — CVE-2024-23342 (Minerva timing, **fix-версии нет**, транзитивно через python-jose). | вывод `pip-audit --skip-editable --aliases` | Обновить gitpython → 3.1.51, mcp → 1.28.1, pyasn1 → 0.6.4. Для chromadb — мониторить advisory GHSA-f4j7-r4q5-qw2c. ecdsa: риск низкий (при HS256 не используется), уйдёт при миграции jose→PyJWT (S-09). |
| S-06 | Medium | Frontend deps | Прочие prod-уязвимости frontend (все с fix): `sharp <0.35.0` — libvips CVE-2026-33327/33328/35590/35591 (GHSA-f88m-g3jw-g9cj); `postcss ≤8.5.11` — XSS через `</style>` в CSS-stringify (GHSA-qx2v-qp2m-jg93); `fast-uri 3.0.0–3.1.3` — host confusion через backslash (GHSA-v2hh-gcrm-f6hx); `brace-expansion 3.0.0–5.0.6` — DoS (GHSA-3jxr-9vmj-r5cp, GHSA-f886-m6hf-6m8v); `@opentelemetry/*` — moderate DoS в Baggage propagation (GHSA-8988-4f7v-96qf). Полный `npm audit` (с dev): 13 — добавляются flatted, js-yaml, picomatch, undici, vite (dev-контур). | `npm audit --omit=dev` (8: 5 high / 3 moderate), `npm audit` (13: 10 high / 3 moderate) | `npm audit fix` (для всех найденных fixAvailable=true); sharp обновить до ≥0.35.0. |
| S-07 | Medium | Rate limiting | Лимиты slowapi при пустом `REDIS_URL` считаются **per-process in-memory** (`memory://`): в многопроцессном/мulti-dyno развёртывании эффективный лимит на логин умножается на число воркеров, а при рестарте счётчики сбрасываются. | `backend/app/core/rate_limit.py:20-28,39-44` | В production обеспечить `REDIS_URL` (и пакет `redis`); добавить startup-warning, если лимиты работают на memory:// вне dev-окружения. |
| S-08 | Medium | Секреты в репо | notes.md: известная проблема «credentials still on disk» **на текущий момент не воспроизводится — файла нет на диске** (find по всему дереву репо). Однако креды, ранее бывшие в файле, формально остаются скомпрометированными. Закоммиченных секретов в git нет: `git ls-files` даёт только `backend/.env.example` и `frontend/.env.example`. | `git ls-files \| grep -iE ...`; `find . -name notes.md` (пусто); `.gitignore:74` | Пользователю — всё же ротировать креды, бывшие в notes.md; обновить запись в `docs/agent-status.md:42` (файл удалён, осталась ротация). |
| S-09 | Low | Backend deps / JWT | `python-jose 3.5.0` — пакет заброшен. Известные CVE-2024-33663/33664 (algorithm confusion, JWE DoS) версию 3.5.0 **не затрагивают** (OSV-запрос по 3.5.0 → 0 уязвимостей; pip-audit согласен). Использование безопасное: алгоритм берётся из настроек (`HS256`), при decode — явный whitelist `algorithms=[settings.jwt_algorithm]`, токены JWE/ECDSA не используются. Риск — отсутствие будущих патчей. | `backend/app/services/auth_service.py:8,64,68`; `backend/app/config.py:101`; OSV API | Запланировать миграцию на PyJWT (поддерживается); заодно уйдёт транзитивный `ecdsa` (S-05). |
| S-10 | Low | Auth — email verification | Email-verification токен — одноразовый, в БД хранится SHA-256 хэш, но **срока действия нет** (в отличие от password-reset, у которого expiry 1ч). Утёкшая ссылка верификации живёт бесконечно. | `backend/app/services/auth_service.py:131-156` vs `:181-183` | Добавить `email_verify_expires_at` (например, 24–72ч). |
| S-11 | Low | MCP | `mcp_allowed_hosts: list[str] = []` — DNS-rebinding protection смонтированного MCP HTTP endpoint'а по умолчанию выключена (permissive). Смягчается тем, что `mcp_enabled`/`mcp_mount_enabled` по умолчанию `False` и каждый запрос требует bearer-auth (401 без токена). | `backend/app/config.py:636-639`; `backend/app/mcp_server/asgi.py:56-77` | При включении mount в production — обязательно задавать `MCP_ALLOWED_HOSTS`; рассмотреть fail-closed дефолт для mount. |
| S-12 | Low | Auth/JWT | `jwt_expire_minutes = 1440` (24ч) — длинное окно жизни access-токена. Компенсируется: `token_version` revocation при смене/сбросе пароля, refresh-endpoint (30/min), httpOnly-cookie. | `backend/app/config.py:102` | Рассмотреть сокращение до 1–4ч при активном refresh; не блокер. |
| S-13 | Low | CORS | `allow_methods=["*"]`, `allow_headers=["*"]` при `allow_credentials=True`. Origins при этом строго перечислены (дефолт: localhost:3000/3100, checkmydata.ai; в .env — те же хосты, без wildcard; `*` в origins запрещён production-валидатором). Риск минимален, но поверхность шире необходимого. | `backend/app/main.py:411-417`; `backend/app/config.py:283-287,804-807` | Сузить до фактически используемых методов/заголовков. |
| S-14 | Info | Логирование | Прямого логирования значений секретов **не найдено**: логируются email, user_id, префикс токена (12 символов = публичный display-prefix `cmd_mcp_xxxx`), префикс SHA-256 хэша. Google nonce в warning-логе (не секрет). Email в логах login/register — PII, учитывать в политике retention логов. | `backend/app/mcp_server/auth.py:46-55`; `backend/app/services/mcp_key_service.py:153`; `backend/app/services/auth_service.py:115-120` | Без действий по секретам; при желании — сократить PII (хэшировать email в info-логах). |
| S-15 | Info | Web-заголовки | Заголовки в порядке: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, `Permissions-Policy`, CSP **enforce** (не report-only) с разумной политикой, HSTS max-age=1год + includeSubDomains — только поверх HTTPS/`X-Forwarded-Proto`. Лимит тела запроса 10 MB. | `backend/app/main.py:318-372`; `backend/app/config.py:587-607` | — |
| S-16 | Info | SSH/MCP контур | Подтверждены ранние пункты: SSH host-key policy `tofu` по умолчанию с валидацией значений; pre-command allowlist (export/NAME=value/source/cd + запрет метасимволов) включён по умолчанию, применяется на API- и exec-слое; MCP auth fail-closed с `hmac.compare_digest`, per-user токены по SHA-256 хэшу, `mcp_enabled=False` по умолчанию. | `backend/app/config.py:712-725,868-869`; `backend/app/connectors/ssh_pre_commands.py:53-86`; `backend/app/mcp_server/auth.py:92-115,140-190` | — |
| S-17 | Info | Аудит-артефакт | 6 уязвимостей `pip 25.0.1` (PYSEC-2026-196/1795/1796/2875/2876) в выводе pip-audit — **не зависимости проекта**: pip отсутствовал в venv и был установлен для запуска аудита. При желании: `python -m pip install -U pip`. | вывод pip-audit | Обновить pip в venv до 26.1.2+ либо удалить после аудита. |

## Проверенное и признанное безопасным (кратко)

- **JWT**: HS256 с явным whitelist алгоритма при verify; дефолтный секрет защищён production-валидатором + startup-warning; токен не возвращается в теле ответа при cookie-auth (F-AUTH-04). `auth_service.py:64,68`; `config.py:773-808,888-891`; `routes/auth.py:24-46`.
- **Cookies**: `HttpOnly` сессия + не-httpOnly CSRF (double-submit), `Secure` по умолчанию, `SameSite=lax`; `SameSite=None` требует `Secure` (fail-closed валидатор). `core/auth_cookies.py:42-74`; `config.py:876-880`.
- **Brute-force**: все `/api/auth/*` покрыты `@limiter` (login 10/min, register 5/min, forgot/reset 5/min, refresh 30/min и т.д.); timing-equalization логина через dummy-bcrypt. `routes/auth.py`; `auth_service.py:24-28,102-121`.
- **bcrypt**: дефолтный work factor (12), хэширование/verify вынесены в thread pool. `auth_service.py:32-52`.
- **Google OAuth**: `verify_oauth2_token` с audience=`google_client_id`, проверка `email_verified`, double-submit `g_csrf_token` по cookie, опциональный nonce. `auth_service.py:227-247`; `routes/auth.py:248-287`.
- **Password reset**: `secrets.token_urlsafe(32)`, в БД SHA-256 хэш, expiry 1ч, одноразовый, bump `token_version` (revoke всех сессий). `auth_service.py:162-221`; `config.py:122`.
- **Секреты в git**: закоммиченных секретов нет; `.gitignore` покрывает `.env`, `.env.*`, `notes.md`, `*.pem`, `*.key`, `credentials.json`, `backend/data/`.
- **pip CVE-артефакт**: см. S-17.

## Команды, использованные в аудите

```bash
backend/.venv/bin/python -m ensurepip && backend/.venv/bin/python -m pip install pip-audit
backend/.venv/bin/python -m pip_audit --skip-editable --aliases
cd frontend && npm audit --omit=dev && npm audit
git ls-files | grep -iE '\.env|secret|credential|notes\.md|\.pem|\.key$'
git check-ignore -v notes.md .env.local backend/.env frontend/.env.local
curl -s -X POST https://api.osv.dev/v1/query -d '{"package":{"name":"python-jose","ecosystem":"PyPI"},"version":"3.5.0"}'
```
