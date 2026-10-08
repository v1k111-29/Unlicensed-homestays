#!/usr/bin/env bash
# Restore test (M11, docs/backup-restore.md): restore one pg_dump archive into an EMPTY scratch
# PostgreSQL database, then print the time taken, row counts of the main tables and the
# audit_log append-only triggers. Read-only towards everything except the scratch database.
#
#   RESTORE_DATABASE_URL=postgres://user:pass@host:5432/scratch scripts/restore-test.sh FILE.dump
#
# Optional: PG_BIN = folder holding psql/pg_restore (e.g. "/c/Program Files/PostgreSQL/17/bin"
# in Git Bash). The client must be the same major version as pg_dump (17) or newer.
# Never point RESTORE_DATABASE_URL at the live database: the script refuses a non-empty target.
set -euo pipefail

dump="${1:?usage: scripts/restore-test.sh FILE.dump}"
: "${RESTORE_DATABASE_URL:?set RESTORE_DATABASE_URL to an EMPTY scratch database}"
bin="${PG_BIN:-}"
psql_bin="${bin:+$bin/}psql"
restore_bin="${bin:+$bin/}pg_restore"

if [ -f "$dump.sha256" ]; then
    (cd "$(dirname "$dump")" && sha256sum --check "$(basename "$dump").sha256")
else
    echo "note: no $dump.sha256 next to the dump; checksum not verified"
fi

q() { "$psql_bin" "$RESTORE_DATABASE_URL" -v ON_ERROR_STOP=1 -X -q -t -A -c "$1"; }

existing=$(q "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
if [ "$existing" != "0" ]; then
    echo "refusing: the target database already has $existing tables (use an empty database)" >&2
    exit 2
fi

echo "restoring $dump ..."
start=$(date +%s)
"$restore_bin" --no-owner --no-privileges --dbname "$RESTORE_DATABASE_URL" "$dump"
elapsed=$(( $(date +%s) - start ))
echo "restore finished in ${elapsed}s"

echo "row counts:"
for table in django_migrations accounts_district accounts_user registry_uploadbatch \
    registry_registryentry listings_listing matching_matchrun matching_matchresult \
    matching_matchcandidate reviews_review reviews_confirmedpair reviews_evidencepack \
    tourist_checks audit_log; do
    printf '  %-26s %s\n' "$table" "$(q "SELECT count(*) FROM $table")"
done

triggers=$(q "SELECT count(*) FROM pg_trigger WHERE tgrelid = 'audit_log'::regclass AND NOT tgisinternal")
echo "audit_log append-only triggers: $triggers (expected 2)"
if [ "$triggers" != "2" ]; then
    echo "restore test FAILED: audit_log triggers missing" >&2
    exit 1
fi
echo "restore test passed: compare the counts above with the live database (docs/backup-restore.md)"
