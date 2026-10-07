"""Append-only audit log (AGENTS.md rule 6).

Two layers: (1) this model refuses updates and deletes in Python (instance and queryset);
(2) a PostgreSQL trigger (migration 0002) rejects UPDATE and DELETE at the database level.
`actor` is plain text (username or "system:<tool>") so no foreign-key cascade can ever touch
an audit row.
"""

from django.db import models


class AppendOnlyError(Exception):
    """Raised on any attempt to change or remove an audit entry."""


class AuditQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise AppendOnlyError("audit_log is append-only: update is not allowed")

    def delete(self):
        raise AppendOnlyError("audit_log is append-only: delete is not allowed")

    def bulk_update(self, *args, **kwargs):
        raise AppendOnlyError("audit_log is append-only: bulk_update is not allowed")


class AuditLog(models.Model):
    actor = models.CharField(max_length=150)
    action = models.CharField(max_length=64)
    entity = models.CharField(max_length=64)
    entity_id = models.CharField(max_length=64, blank=True)
    meta = models.JSONField(default=dict)
    ts = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = AuditQuerySet.as_manager()

    class Meta:
        db_table = "audit_log"
        ordering = ["-ts", "-id"]

    def save(self, *args, **kwargs) -> None:
        if not self._state.adding:
            raise AppendOnlyError("audit_log is append-only: existing rows cannot be saved")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("audit_log is append-only: delete is not allowed")

    def __str__(self) -> str:
        return f"{self.ts} {self.actor} {self.action} {self.entity}:{self.entity_id}"
