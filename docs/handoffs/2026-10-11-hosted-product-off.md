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
| Site | **since 2026-10-12** a static export on Cloudflare Workers (`checkmydata-site`, route `checkmydata.ai/*`, free plan); waitlist at `/#waitlist` served by the Worker; product routes redirect there; `RESEND_API_KEY` is a Worker secret. `checkmydata-web` (Heroku) at 0 dynos | `frontend/src/__tests__/waitlist.test.ts`, `static-site-config.test.ts`; a test sign-up sent from production reached `contact@checkmydata.ai` |
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
3. Restore the Heroku `deploy.yml` from git history (before 2026-10-11), detach the
   `checkmydata.ai/*` Worker route, and build the site with plain `npm run build`
   (standalone, no redirects).

## Open work

- Nothing blocking. Hosting is $0: both Heroku apps are at 0 dynos and the site is on the
  Cloudflare free plan. The apex DNS record still points at Heroku's DNS target; it is
  proxied, so the Worker route answers first and the origin is never reached. Delete it, and
  the two empty Heroku apps, only if the relaunch path below is abandoned.
- Deploying the site needs `CLOUDFLARE_WORKERS_TOKEN` and `CLOUDFLARE_ROUTES_TOKEN` (repo
  secrets, each narrow: account Workers scripts, and one zone's Worker routes) and the
  `CLOUDFLARE_ACCOUNT_ID` variable — all set.

## Next task

None owed. Watch `contact@checkmydata.ai` for sign-ups.
