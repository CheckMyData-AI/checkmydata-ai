# Handoff — hosted product switched off, site is a waitlist (2026-10-11)

## Objective

Operator instruction, 2026-10-11: stop every running cost except the website. Switch off
auto-deploy, the API, the worker and every database; replace the product entry points on
checkmydata.ai with a waitlist whose sign-ups reach `contact@checkmydata.ai`; make sure that
address has its own mailbox.

## What was done

| Area | State after | How it was checked |
|---|---|---|
| Backups | `pg_dump -Fc` of the Supabase production database and of the Heroku Postgres rollback copy, taken before deletion; kept privately by the operator, **outside Git** (they hold customer data) | `pg_restore --list` read both: 104 and 65 table-data entries |
| Secrets the dumps need | `MASTER_ENCRYPTION_KEY` (decrypts stored connection credentials), `JWT_SECRET`, `RESEND_API_KEY`, `GOOGLE_CLIENT_SECRET`, `SENTRY_DSN`, `GIT_WEBHOOK_SECRET` copied into the operator's secret store by name | store listing shows each slot |
| `checkmydata-api` (Heroku) | `web=0`, `worker=0` (were 2× Standard-2X), maintenance mode on; app shell and its config vars kept, so a relaunch needs no secret re-entry | `heroku ps` → "No dynos" |
| Heroku add-ons | `heroku-postgresql` (essential-1) and `heroku-redis` (mini) destroyed | `heroku addons` → none |
| Supabase | project `CheckMyData` deleted; its organization is on the free plan, so nothing is billed | Management API: `plan: free`, `projects: []` |
| Auto-deploy | `deploy.yml` is `workflow_dispatch` only and deploys the site alone | `gh workflow list` |
| Site (`checkmydata-web`, Heroku Basic) | waitlist form at `/#waitlist`; product routes redirect there; `RESEND_API_KEY` and `WAITLIST_TO` set on the dyno | `frontend/src/__tests__/waitlist.test.ts`; post-deploy check in `deploy.yml` |
| `contact@checkmydata.ai` | its own mailbox now (before: no mailbox, mail fell into the domain's catch-all); a dedicated Cloudflare Email Routing rule sends it to the inbox | routing check answers `verified, via rule` |

Not touched, because they cost nothing idle: the Cloudflare zone and DNS, Resend (sending
domain verified), Sentry, GA4, the OpenRouter key (no traffic now that the API is off).
`api.checkmydata.ai` still points at the stopped app and answers with Heroku's maintenance page.

## Decisions

- **Product code stays in the repository.** The routes are redirected in
  `frontend/next.config.ts`, not deleted: deleting them buys no saving and cascades through
  ~10 tests, and a relaunch would have to restore them. Self-hosting is unchanged.
- **No waitlist database.** The email is the record. A sign-up that could not be mailed is
  reported to the visitor as a failure (502/503), never acknowledged and dropped.
- **Redirects are temporary (307), not permanent**, so browsers do not cache them past a relaunch.
- **The API app is scaled to zero, not destroyed** — zero dynos cost nothing, and its config
  vars are the cheapest relaunch path.

## Relaunch (if ever)

1. Create a Postgres (pgvector) database, restore the dump with `pg_restore --no-owner`,
   point `DATABASE_URL` at it; add Redis and set `REDIS_URL`.
2. `heroku maintenance:off`, `heroku ps:scale web=1 worker=1 -a checkmydata-api`.
3. Restore the backend half of `deploy.yml` from the commit before this change, and remove
   the redirects in `frontend/next.config.ts`.

## Open work

- Nothing blocking. Optional: the site still runs on a Basic dyno (~$7/month); a static host
  would make it free but needs the waitlist endpoint moved to a serverless function.

## Next task

None owed. Watch `contact@checkmydata.ai` for sign-ups.
