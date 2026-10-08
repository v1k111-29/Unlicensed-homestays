"""Audit writer. Every state-changing action calls `audit.log(...)` (AGENTS.md §8)."""

from typing import Any


def log(actor: Any, action: str, entity: str, entity_id: Any = "", meta: dict | None = None):
    """Append one audit entry. `actor` is a user (its username is stored) or a string such as
    "system:load_synthetic". Returns the created AuditLog row."""
    from audit.models import AuditLog  # lazy: keeps `import audit` safe before apps load

    name = actor if isinstance(actor, str) else actor.get_username()
    return AuditLog.objects.create(
        actor=name,
        action=action,
        entity=entity,
        entity_id="" if entity_id is None else str(entity_id),
        meta=meta or {},
    )
