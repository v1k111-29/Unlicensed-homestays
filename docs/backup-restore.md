# Backup and restore (M11)

> **Status: prepared, NOT running.** No R2 bucket, secret or backup exists yet, and **the
> restore test has not been done**. It must be done once by the human before submission
> (implementationsplan.md Stage 5, security-and-privacy.md §6). Nothing here is [V] until that
> run is recorded below.

## 1. What runs

`.github/workflows/backup.yml` (D87):

- **When:** nightly at 20:30 UTC (02:00 IST), and on demand (Actions > Backup > Run workflow).
- **What:** `pg_dump --format=custom --no-owner --no-privileges --exclude-table-data=django_cache`
  of the hosted Neon database (all tables: users with password hashes, synthetic registry and
  listings, runs, reviews, evidence, `audit_log`, `tourist_checks`). The rows of the
  `django_cache` table are left out (D88): they are short-lived login-throttle address HMACs
  and pending uploads, and must not be kept for 30 days in R2. The empty table is still in the
  dump, so a restore needs no `createcachetable`. The tourist rate limit is never in the
  database at all (per-process memory, D88). The archive is listed with `pg_restore --list` to
  prove it is readable, and a `.sha256` file is written next to it.
- **Where:** private Cloudflare R2 bucket, key `daily/verified-stays-<UTC timestamp>.dump`
  (+ `.sha256`).
- **Tools:** runner tools only: PostgreSQL 17 client from the PGDG apt repository, the
  runner's AWS CLI against R2's S3 API. No Python dependency.
- **Without secrets:** the job ends with a warning ("Backup not configured") and dumps
  nothing, so an unconfigured fork does not fail every night.

## 2. One-time setup (human)

1. **Cloudflare account** > R2. If enabling R2 asks for a payment method, stop and decide first
   (AGENTS.md §11: no paid service without agreement; Q43). The free allowance [A] is far above
   what a few small dumps use.
2. **Bucket:** create `verified-stays-backups` (any name), location hint Asia-Pacific [A].
   Leave public access **off**.
3. **Lifecycle rule:** delete objects under `daily/` after 30 days [A: R2 object lifecycle
   rules]. Thirty nightly dumps of a few MB stay well inside the free storage [E].
4. **API token:** R2 > Manage R2 API tokens > Create: permission **Object Read & Write**,
   restricted to this bucket only, no expiry or one after the challenge. Note the
   *Access Key ID*, *Secret Access Key* and your *Account ID* (shown on the R2 overview).
5. **GitHub secrets** (repository > Settings > Secrets and variables > Actions > Secrets):

   | Secret name | Value |
   |---|---|
   | `BACKUP_DATABASE_URL` | Neon **direct** connection string with `sslmode=require` (deploy-runbook §2) |
   | `R2_ACCOUNT_ID` | Cloudflare account id |
   | `R2_ACCESS_KEY_ID` | token access key id |
   | `R2_SECRET_ACCESS_KEY` | token secret access key |
   | `R2_BUCKET` | bucket name |

   Optional, better: create a separate read-only Neon role for backups and use its string
   (it needs `SELECT` on all tables and sequences) [A].
6. **First run:** Actions > Backup > Run workflow (leave `restore_test` unticked). Check the log
   for `uploaded daily/...` and the object in the R2 dashboard.

## 3. Restore test (must be done once by the human)

Goal: prove a dump restores into an empty PostgreSQL, with the audit triggers intact, and
record how long it took (security-and-privacy.md §6).

**Option A, on GitHub (no local tools):** Actions > Backup > Run workflow, tick
`restore_test`. The `restore-test` job downloads the dump that the run just uploaded **from
R2**, checks its SHA-256, restores it into a throwaway PostgreSQL 17 container on the runner
with `scripts/restore-test.sh`, and prints the restore time, row counts per table and the
number of `audit_log` triggers (expected 2). Nothing is written to Neon.

**Option B, on your PC:** needs a PostgreSQL 17 client (`psql`, `pg_restore`) and an **empty**
scratch database (a local PostgreSQL database, or a new Neon branch/database, never the live
one: the script refuses a database that already has tables).

```bash
# Git Bash, from the repository root
export AWS_ACCESS_KEY_ID=...  AWS_SECRET_ACCESS_KEY=...  AWS_DEFAULT_REGION=auto   # or download in the R2 dashboard
aws s3 cp s3://<bucket>/daily/<file>.dump . --endpoint-url https://<account-id>.r2.cloudflarestorage.com
aws s3 cp s3://<bucket>/daily/<file>.dump.sha256 . --endpoint-url https://<account-id>.r2.cloudflarestorage.com
export RESTORE_DATABASE_URL='postgres://<user>:<password>@localhost:5432/<empty_scratch_db>'
PG_BIN="/c/Program Files/PostgreSQL/17/bin" bash scripts/restore-test.sh <file>.dump
```

Type secrets only into your own terminal, never into a file in the repository.

**Compare** the printed row counts with the live database at the time of the dump (Neon SQL
editor), for example:

```sql
SELECT 'accounts_user', count(*) FROM accounts_user
UNION ALL SELECT 'registry_registryentry', count(*) FROM registry_registryentry
UNION ALL SELECT 'listings_listing', count(*) FROM listings_listing
UNION ALL SELECT 'reviews_review', count(*) FROM reviews_review
UNION ALL SELECT 'audit_log', count(*) FROM audit_log;
```

Counts may be higher on the live side if people used the site after the dump.

**Record the result** here and in `docs/progress.md`:

| When | Dump object | Option | Restore time | Counts match | audit_log triggers | By |
|---|---|---|---|---|---|---|
| not done yet | | | | | | |

## 4. Recovery procedure (real incident)

1. Do not restore over the live database. Create a **new** empty database (a new Neon branch or
   database in the same project).
2. Pick the newest good dump in R2 (`daily/`), download it with its `.sha256`.
3. Run `scripts/restore-test.sh` against the new database (section 3, Option B). It restores,
   checks the checksum, prints counts and checks the audit triggers.
4. Render > service > Environment: set `DATABASE_URL` to the new database; save; redeploy.
   Keep `DJANGO_SECRET_KEY` unchanged (audit and throttle HMACs depend on it).
5. Check `https://<host>/healthz` = ok, sign in, open the review queue; compare a few counts.
6. Point `BACKUP_DATABASE_URL` (GitHub secret) at the new database.
7. Write down what happened, the time taken and the data lost since the dump in
   `docs/progress.md`. Neon's own point-in-time history [A] may recover a more recent state
   than the nightly dump: check it first.

## 5. Privacy and limits

- Dumps hold argon2 password hashes, the audit username HMACs and the synthetic data set (no
  address HMACs: `django_cache` rows are excluded, D88); the bucket stays
  private and the token is scoped to it. Data is synthetic only (rule 3).
- Dumps are not encrypted beyond R2's storage encryption [A]. Before any real data: encrypt the
  dump in the workflow and define retention (Q6) - not needed for the synthetic demo.
- One nightly dump means up to a day of changes can be lost; acceptable for the demo.
