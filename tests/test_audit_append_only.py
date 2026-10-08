"""Audit log is append-only (AGENTS.md rule 6)."""

import pytest
from django.db import DatabaseError, connection, transaction

import audit
from audit.models import AppendOnlyError, AuditLog


def test_existing_row_cannot_be_saved_again() -> None:
    row = AuditLog(actor="a", action="x", entity="e")
    row._state.adding = False  # as if loaded from the database
    with pytest.raises(AppendOnlyError):
        row.save()


def test_instance_delete_blocked() -> None:
    with pytest.raises(AppendOnlyError):
        AuditLog(actor="a", action="x", entity="e").delete()


def test_queryset_update_blocked() -> None:
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.all().update(action="y")


def test_queryset_delete_blocked() -> None:
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.filter(action="x").delete()


def test_bulk_update_blocked() -> None:
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.bulk_update([], ["action"])


def test_base_manager_is_the_guarded_manager() -> None:
    """Django's internal paths (related access, deletion collector) use the base manager."""
    with pytest.raises(AppendOnlyError):
        AuditLog._base_manager.all().update(action="y")
    with pytest.raises(AppendOnlyError):
        AuditLog._base_manager.all().delete()


def test_internal_update_and_raw_delete_blocked() -> None:
    with pytest.raises(AppendOnlyError):
        AuditLog.objects.all()._update({"action": "y"})
    with pytest.raises(AppendOnlyError):
        AuditLog._base_manager.all()._raw_delete(using="default")


@pytest.mark.django_db
def test_stored_row_cannot_be_changed_through_base_manager() -> None:
    entry = audit.log("system:test", "x", "e", 1)
    with pytest.raises(AppendOnlyError):
        AuditLog._base_manager.filter(pk=entry.pk)._update({"action": "changed"})
    with pytest.raises(AppendOnlyError):
        AuditLog._base_manager.filter(pk=entry.pk)._raw_delete(using="default")
    assert AuditLog.objects.get(pk=entry.pk).action == "x"


@pytest.mark.django_db
def test_database_trigger_blocks_truncate() -> None:
    if connection.vendor != "postgresql":
        pytest.skip("the append-only trigger exists on PostgreSQL only")
    audit.log("system:test", "x", "e", 1)
    with pytest.raises(DatabaseError, match="append-only"):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute("TRUNCATE audit_log")
    assert AuditLog.objects.filter(action="x").count() == 1


@pytest.mark.django_db
def test_log_writes_entry() -> None:
    entry = audit.log("system:test", "registry_upload", "upload_batch", 7, {"k": "v"})
    stored = AuditLog.objects.get(pk=entry.pk)
    assert (stored.actor, stored.action, stored.entity, stored.entity_id) == (
        "system:test",
        "registry_upload",
        "upload_batch",
        "7",
    )
    assert stored.meta == {"k": "v"} and stored.ts is not None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "sql",
    ["UPDATE audit_log SET action = 'changed'", "DELETE FROM audit_log"],
)
def test_database_trigger_blocks_raw_sql(sql: str) -> None:
    if connection.vendor != "postgresql":
        pytest.skip("the append-only trigger exists on PostgreSQL only")
    audit.log("system:test", "x", "e", 1)
    with pytest.raises(DatabaseError, match="append-only"):
        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(sql)
    assert AuditLog.objects.filter(action="x").count() == 1
