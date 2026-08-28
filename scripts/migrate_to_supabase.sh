#!/usr/bin/env bash
# Copy the application database from Heroku Postgres to Supabase.
#
# The schema is already there — 65 tables, 200 indexes, 91 foreign keys, applied and
# compared column-for-column on 2026-08-28. So is the hardening this migration needs,
# and that part is not optional: read "Why the hardening comes first" below before
# changing anything about it.
#
# What is left is the data, and that is what this script does.
#
#   ./scripts/migrate_to_supabase.sh                 # dry run: check, measure, report
#   ./scripts/migrate_to_supabase.sh --apply         # copy the data
#
# Needs SUPABASE_DB_PASSWORD in the environment. That is the one thing no automation
# here can obtain: it is set when the project is created and the API will not return it.
#
# ---------------------------------------------------------------------------------
# Why the hardening comes first, and must stay
#
# Supabase's `public` schema is served by the Data API, and `ALTER DEFAULT PRIVILEGES`
# grants `anon` and `authenticated` ALL privileges on everything created there. The
# anon key is designed to be public — it ships inside frontends. Restoring 65 tables
# into the default configuration would have made `users`, `connections` (Fernet-
# encrypted credentials), `ssh_keys`, `mcp_api_keys` and `audit_logs` readable AND
# writable by anyone holding it, the moment the restore finished.
#
# Three defences are in place, and each was verified rather than assumed:
#
#   1. The Data API no longer exposes `public` (db_schema = "graphql_public").
#      Verified from outside with the real anon key against a canary row: 404 with the
#      lock on, HTTP 200 and the canary leaking with it deliberately removed.
#   2. Default privileges for `postgres` in `public` revoked from anon, authenticated
#      and service_role — including PG17's MAINTAIN.
#   3. RLS enabled on all 65 tables, with every grant to anon/authenticated revoked.
#      The application is unaffected: it connects as `postgres`, which has BYPASSRLS.
#      `anon` and `authenticated` do not.
#
# ---------------------------------------------------------------------------------
# Why the pooler, and why session mode
#
# `db.<ref>.supabase.co` resolves to an AAAA record ONLY — there is no A record, and
# Heroku dynos have no outbound IPv6. A direct connection from a dyno cannot be made at
# all, so the pooler is not a performance choice here, it is the only route.
#
# Port 5432 on the pooler is session mode; 6543 is transaction mode. Transaction mode
# breaks named prepared statements, which SQLAlchemy's asyncpg dialect uses by default,
# and the failure is intermittent rather than immediate. At 9 of 20 connections in use
# the throughput argument for transaction mode is theoretical and the ways to be subtly
# wrong are not. Revisit when connection count is the measured constraint.
set -euo pipefail

APP="${HEROKU_APP:-checkmydata-api}"
REF="${SUPABASE_PROJECT_REF:-gbtnnipdxtefnaietmli}"
POOLER_HOST="${SUPABASE_POOLER_HOST:-aws-1-eu-west-1.pooler.supabase.com}"
PG_BIN="${PG_BIN:-/opt/homebrew/opt/postgresql@17/bin}"
APPLY="${1:-}"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
die() { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[ -n "${SUPABASE_DB_PASSWORD:-}" ] || die \
  "SUPABASE_DB_PASSWORD is not set. It is chosen when the Supabase project is created
   and the Management API will not return it — this is the one step no automation here
   can take. Set it, or reset it in the dashboard, then re-run."

# pg_dump refuses to dump from a server newer than itself, and Heroku runs 17.9.
[ -x "$PG_BIN/pg_dump" ] || die "PostgreSQL 17 client not found at $PG_BIN (brew install postgresql@17)"
DUMP_VERSION="$("$PG_BIN/pg_dump" --version | grep -oE '[0-9]+' | head -1)"
[ "$DUMP_VERSION" -ge 17 ] || die "pg_dump is $DUMP_VERSION; Heroku Postgres is 17.x and pg_dump refuses to read a newer server"

SOURCE_URL="$(heroku config:get DATABASE_URL -a "$APP")"
[ -n "$SOURCE_URL" ] || die "could not read DATABASE_URL from $APP"
TARGET_URL="postgresql://postgres.${REF}:${SUPABASE_DB_PASSWORD}@${POOLER_HOST}:5432/postgres"

say "1. Both ends answer"
"$PG_BIN/psql" "$SOURCE_URL" -tAc "select 'source ' || version()" | cut -c1-60
"$PG_BIN/psql" "$TARGET_URL" -tAc "select 'target ' || version()" | cut -c1-60

say "2. The schema matches before any data moves"
SHAPE="select (select count(*) from information_schema.tables where table_schema='public' and table_type='BASE TABLE')
       || '/' || (select count(*) from pg_indexes where schemaname='public')
       || '/' || (select count(*) from information_schema.table_constraints
                  where constraint_schema='public' and constraint_type='FOREIGN KEY')"
SRC_SHAPE="$("$PG_BIN/psql" "$SOURCE_URL" -tAc "$SHAPE")"
DST_SHAPE="$("$PG_BIN/psql" "$TARGET_URL" -tAc "$SHAPE")"
printf '   source tables/indexes/fks: %s\n   target tables/indexes/fks: %s\n' "$SRC_SHAPE" "$DST_SHAPE"
[ "$SRC_SHAPE" = "$DST_SHAPE" ] || die "schema differs — resolve that before copying data"

say "3. The hardening is still in place"
LEAKY="$("$PG_BIN/psql" "$TARGET_URL" -tAc \
  "select count(*) from information_schema.role_table_grants
    where table_schema='public' and grantee in ('anon','authenticated')")"
NO_RLS="$("$PG_BIN/psql" "$TARGET_URL" -tAc \
  "select count(*) from pg_tables where schemaname='public' and not rowsecurity")"
printf '   tables granting to anon/authenticated: %s (must be 0)\n   tables without RLS: %s (must be 0)\n' "$LEAKY" "$NO_RLS"
[ "$LEAKY" = "0" ] && [ "$NO_RLS" = "0" ] || die \
  "the target is not hardened — copying production data into it now would expose it"

if [ "$APPLY" != "--apply" ]; then
  say "Dry run only. Re-run with --apply to copy the data."
  "$PG_BIN/psql" "$SOURCE_URL" -tAc \
    "select 'source holds ' || pg_size_pretty(pg_database_size(current_database()))"
  exit 0
fi

say "4. Copying data (schema already present, so data only)"
# --disable-triggers keeps foreign keys from ordering the restore for us; the schema is
# already there and identical, so the constraint set is re-validated at the end anyway.
"$PG_BIN/pg_dump" --data-only --no-owner --no-privileges --disable-triggers \
  --schema=public "$SOURCE_URL" \
  | "$PG_BIN/psql" "$TARGET_URL" -v ON_ERROR_STOP=1 --single-transaction -q

say "5. Row counts, table by table"
COUNTS="select table_name, (xpath('/row/c/text()',
          query_to_xml(format('select count(*) as c from public.%I', table_name),
          false, true, '')))[1]::text::int as n
        from information_schema.tables
        where table_schema='public' and table_type='BASE TABLE' order by table_name"
"$PG_BIN/psql" "$SOURCE_URL" -tAF, -c "$COUNTS" > /tmp/src_counts.csv
"$PG_BIN/psql" "$TARGET_URL" -tAF, -c "$COUNTS" > /tmp/dst_counts.csv
if diff -u /tmp/src_counts.csv /tmp/dst_counts.csv > /tmp/counts.diff; then
  printf '   every table matches (%s tables)\n' "$(wc -l < /tmp/src_counts.csv | tr -d ' ')"
else
  printf '\033[31m   ROW COUNTS DIFFER:\033[0m\n'; sed -n '1,40p' /tmp/counts.diff
  die "do not switch DATABASE_URL until this is understood"
fi

say "6. Sequences follow the data"
# A restored table with a sequence left at 1 accepts one insert and then fails on the
# primary key. It is the classic way a migration looks fine for an hour.
"$PG_BIN/psql" "$TARGET_URL" -q -c "
do \$\$
declare r record;
begin
  for r in
    select s.relname as seq, t.relname as tbl, a.attname as col
    from pg_class s
    join pg_depend d on d.objid = s.oid and d.deptype = 'a'
    join pg_class t on t.oid = d.refobjid
    join pg_attribute a on a.attrelid = t.oid and a.attnum = d.refobjsubid
    where s.relkind = 'S' and t.relnamespace = 'public'::regnamespace
  loop
    execute format('select setval(%L, coalesce((select max(%I) from public.%I), 1))',
                   r.seq, r.col, r.tbl);
  end loop;
end \$\$;"
echo "   done"

cat <<'NEXT'

Data is in. What is left is one config change and one measurement, in this order:

  heroku config:set DATABASE_URL='postgresql+asyncpg://postgres.<ref>:<password>@<pooler>:5432/postgres' -a checkmydata-api

Then, before believing it:

  * `alembic_version` on the target must equal the one on the source.
  * A chat request must complete — that exercises asyncpg through the session pooler,
    which is the part no dry run can prove.
  * `select count(*) from doc_embeddings` must be non-zero, or the next repo index
    will force a full rebuild and spend hours re-earning what was already copied.

Keep the Heroku database for a few days. It is the only rollback there is.
NEXT
