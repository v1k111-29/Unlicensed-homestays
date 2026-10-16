"""Audit writer. Every state-changing action calls `audit.log(...)` (AGENTS.md §8).

This package is the only way code should write to the audit log. It is called from the
services in every app and from the permission checks, so a change always leaves one row.
The model itself lives in `audit.models`, and that model refuses updates and deletes.
"""

from typing import Any


def log(actor: Any, action: str, entity: str, entity_id: Any = "", meta: dict | None = None) -> Any:
    """Append one audit entry. `actor` is a user (its username is stored) or a string such as
    "system:load_synthetic". Returns the created AuditLog row."""
    # The model import sits inside the function so that importing `audit` never fails before
    # Django has finished loading its apps.
    from audit.models import AuditLog  # lazy: keeps `import audit` safe before apps load

    # Store the username as text, not a foreign key, so deleting a user cannot touch the log.
    name = actor if isinstance(actor, str) else actor.get_username()
    return AuditLog.objects.create(
        actor=name,
        action=action,
        entity=entity,
        entity_id="" if entity_id is None else str(entity_id),
        meta=meta or {},
    )
