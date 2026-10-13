"""Audit-log screen (essentialfeatures.md O6): admin only, read-only (D93).

GET only. No control on this page creates, changes or removes an audit row, and a plain read
writes no audit row itself (D93); a refused officer still gets the usual 403 + denial row.
Meta values are shown as a short, scrubbed summary: keys that look like secrets are hidden and
addresses, e-mails, phone numbers and credentials are replaced (config.logs.scrub).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, time, timedelta
from typing import Any

from django import forms
from django.core.paginator import Paginator
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.http import urlencode
from django.utils.translation import gettext_lazy as _
from django.views.decorators.http import require_GET

from accounts.permissions import Capability, require_capability
from audit.models import AuditLog
from config.logs import scrub

PAGE_SIZE = 50
META_MAX = 160  # characters of the meta summary shown per row
_SECRET_KEY = re.compile(
    r"pass|secret|token|api_?key|cookie|session|csrf|auth|(^|_)ip(_|$)|addr", re.IGNORECASE
)
# Entity ids that are HMACs, never usernames or addresses (D58, D65).
HASHED_ENTITIES = {"username_hmac"}


class AuditFilterForm(forms.Form):
    action = forms.ChoiceField(label=_("Action"), required=False)
    actor = forms.CharField(label=_("Actor contains"), required=False, max_length=150)
    entity = forms.ChoiceField(label=_("Entity"), required=False)
    date_from = forms.DateField(label=_("From date"), required=False, input_formats=["%Y-%m-%d"])
    date_to = forms.DateField(label=_("To date"), required=False, input_formats=["%Y-%m-%d"])

    def __init__(self, *args: Any, actions: list[str], entities: list[str], **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.fields["action"].choices = [("", _("All actions"))] + [(a, a) for a in actions]
        self.fields["entity"].choices = [("", _("All entities"))] + [(e, e) for e in entities]
        for name in ("date_from", "date_to"):
            self.fields[name].error_messages["invalid"] = _("Enter a date as YYYY-MM-DD.")

    def clean(self) -> dict[str, Any]:
        data = super().clean()
        start, end = data.get("date_from"), data.get("date_to")
        if start and end and start > end:
            self.add_error("date_to", _("The end date is before the start date."))
        return data


def _distinct(field: str) -> list[str]:
    return list(AuditLog.objects.order_by(field).values_list(field, flat=True).distinct())


def _day_start(day: Any) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


def meta_summary(meta: Any) -> str:
    """Short, safe text for a meta value: `key: value; ...`, secret-looking keys hidden,
    personal data scrubbed, cut to META_MAX characters. Autoescaped by the template."""
    if not isinstance(meta, dict):
        text = json.dumps(meta, ensure_ascii=False, default=str)
    else:
        parts = []
        for key in sorted(meta):
            if _SECRET_KEY.search(str(key)):
                value = "[hidden]"
            else:
                value = json.dumps(meta[key], ensure_ascii=False, default=str)
            parts.append(f"{key}: {value}")
        text = "; ".join(parts)
    text = scrub(text)
    return text if len(text) <= META_MAX else text[: META_MAX - 1] + "…"


@require_capability(Capability.VIEW_AUDIT)
@require_GET
def audit_log(request: HttpRequest) -> HttpResponse:
    form = AuditFilterForm(
        request.GET or None, actions=_distinct("action"), entities=_distinct("entity")
    )
    qs = AuditLog.objects.all()  # model ordering: newest first (-ts, -id)
    query: dict[str, str] = {}
    if form.is_bound and form.is_valid():
        data = form.cleaned_data
        if data["action"]:
            qs = qs.filter(action=data["action"])
        if data["actor"]:
            qs = qs.filter(actor__icontains=data["actor"].strip())
        if data["entity"]:
            qs = qs.filter(entity=data["entity"])
        if data["date_from"]:
            qs = qs.filter(ts__gte=_day_start(data["date_from"]))
        if data["date_to"]:
            qs = qs.filter(ts__lt=_day_start(data["date_to"] + timedelta(days=1)))
        query = {
            k: (v.isoformat() if hasattr(v, "isoformat") else str(v).strip())
            for k, v in data.items()
            if v
        }
    invalid = form.is_bound and not form.is_valid()
    if invalid:
        qs = qs.none()
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    rows = [
        {
            "entry": e,
            "hashed": e.entity in HASHED_ENTITIES,
            "meta": meta_summary(e.meta),
        }
        for e in page.object_list
    ]
    return render(
        request,
        "audit/log.html",
        {
            "form": form,
            "invalid": invalid,
            "filtered": bool(query),
            "page": page,
            "rows": rows,
            "page_query": urlencode(query),
        },
        status=400 if invalid else 200,
    )
