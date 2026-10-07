"""PostgreSQL triggers that make audit_log append-only (AGENTS.md rule 6, D42).

- Row trigger: rejects UPDATE and DELETE.
- Statement trigger: rejects TRUNCATE.
Irreversible on purpose: no migration path removes the protection.

Consequence: tests must not use `transactional_db` / `TransactionTestCase` on PostgreSQL,
because their teardown TRUNCATEs every table. Use the default transactional rollback (`db`).
On non-PostgreSQL backends this migration does nothing (the model-level guard still applies).
"""

from django.db import migrations

# One statement per execute; no "%" characters (DB-API placeholder syntax).
CREATE = [
    """
    CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
    BEGIN
        RAISE EXCEPTION USING
            MESSAGE = 'audit_log is append-only: ' || TG_OP || ' is not allowed',
            ERRCODE = 'insufficient_privilege';
    END;
    $$ LANGUAGE plpgsql
    """,
    """
    CREATE TRIGGER audit_log_no_update_delete
        BEFORE UPDATE OR DELETE ON audit_log
        FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()
    """,
    """
    CREATE TRIGGER audit_log_no_truncate
        BEFORE TRUNCATE ON audit_log
        FOR EACH STATEMENT EXECUTE FUNCTION audit_log_append_only()
    """,
]


def create(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        for sql in CREATE:
            schema_editor.execute(sql, params=None)


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunPython(create)]  # no reverse: irreversible by design
