"""Append-only audit log (AGENTS.md rule 6).

Two layers: (1) this model refuses updates and deletes in Python (instance, queryset, base
manager and Django's internal `_update` / `_raw_delete`); (2) PostgreSQL triggers (migration
0002) reject UPDATE, DELETE and TRUNCATE at the database level.
`actor` is plain text (username or "system:<tool>") so no foreign-key cascade can ever touch
an audit row.
"""

from django.db import models


class AppendOnlyError(Exception):
    """Raised on any attempt to change or remove an audit entry."""


class AuditQuerySet(models.QuerySet):
    """A queryset that blocks every write except creating rows. Each method below closes one
    route by which an existing row could be changed or removed."""

    def update(self, **kwargs):
        """Refuse bulk updates."""
        raise AppendOnlyError("audit_log is append-only: update is not allowed")

    def delete(self):
        """Refuse bulk deletes."""
        raise AppendOnlyError("audit_log is append-only: delete is not allowed")

    def bulk_update(self, *args, **kwargs):
        """Refuse bulk updates done through Django's bulk_update helper."""
        raise AppendOnlyError("audit_log is append-only: bulk_update is not allowed")

    # Internal paths used by Django itself (deletion collector, related updates, save()).
    # They are blocked too, because Django can reach them without going through update().
    def _update(self, values):
        """Refuse the internal update path Django uses for related objects."""
        raise AppendOnlyError("audit_log is append-only: update is not allowed")

    def _raw_delete(self, using):
        """Refuse the internal delete path used by Django's deletion collector."""
        raise AppendOnlyError("audit_log is append-only: delete is not allowed")


class AuditLog(models.Model):
    """One row of the audit trail: who did what, to which record, and a small set of details.
    Rows are written by `audit.log` and never changed afterwards."""

    actor = models.CharField(max_length=150)
    action = models.CharField(max_length=64)
    entity = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64, blank=True)
    meta = models.JSONField(default=dict)
    ts = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        db_table = "audit_log"
        # Django uses the base manager internally (related access, deletion collector); make it
        # the guarded manager too, so no internal path gets a plain QuerySet.
        base_manager_name = "objects"
        ordering = ["-ts", "-id"]

    def save(self, *args, **kwargs) -> None:
        """Allow only the first save of a new row. Re-saving an existing row would change it."""
        # _state.adding is True until the row is first written, so this guard stops any later save.
        if not self._state.adding:
            raise AppendOnlyError("audit_log is append-only: existing rows cannot be saved")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Refuse to delete this row."""
        raise AppendOnlyError("audit_log is append-only: delete is not allowed")

    def __str__(self) -> str:
        """A one-line summary used in the Django admin and in debug output."""
        return f"{self.ts} {self.actor} {self.action} {self.entity}:{self.entity_id}"
