"""PostgreSQL trigger that rejects UPDATE and DELETE on audit_log (AGENTS.md rule 6).

TRUNCATE is not blocked so the test runner can reset tables; no application code truncates.
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
]

DROP = [
    "DROP TRIGGER IF EXISTS audit_log_no_update_delete ON audit_log",
    "DROP FUNCTION IF EXISTS audit_log_append_only()",
]


def _run(statements: list[str]):
    def apply(apps, schema_editor):
        if schema_editor.connection.vendor == "postgresql":
            for sql in statements:
                schema_editor.execute(sql, params=None)

    return apply


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunPython(_run(CREATE), _run(DROP))]
