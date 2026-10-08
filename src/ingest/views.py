"""Upload pages (M7): listings (officer, admin) and registry (admin).

Flow: choose file → preview (row count, districts, first rows) → confirm or cancel. Business
rules live in `ingest.uploads`; this module only handles HTTP and templates.

The file field is read through `CappedUploadHandler`, so at most MAX_BYTES + 1 bytes of an
upload are ever held, in memory, and nothing is written to disk (D67).
"""

from __future__ import annotations

import io
from collections.abc import Callable
from functools import wraps
from pathlib import PurePath
from typing import Any

from django import forms
from django.contrib import messages
from django.core.files.uploadedfile import InMemoryUploadedFile
from django.core.files.uploadhandler import FileUploadHandler
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.template.defaultfilters import filesizeformat
from django.urls import reverse
from django.utils.translation import gettext as _
from django.utils.translation import gettext_lazy
from django.views.decorators.csrf import csrf_exempt, csrf_protect
from django.views.decorators.http import require_http_methods, require_POST

from accounts.permissions import Capability, is_admin, require_capability
from accounts.scoping import scoped
from ingest import uploads
from ingest.csvtools import MAX_BYTES, MAX_ROWS, LineError
from registry.models import UploadBatch

PREVIEW_ROWS = 20
SHOW_ERRORS = 200


class CappedUploadHandler(FileUploadHandler):
    """Keeps at most `cap` bytes of each uploaded file in memory and only counts the rest, so
    an oversized file is reported by its real size without being stored anywhere."""

    cap = MAX_BYTES + 1

    def new_file(self, *args: Any, **kwargs: Any) -> None:
        super().new_file(*args, **kwargs)
        self.buffer = io.BytesIO()
        self.total = 0

    def receive_data_chunk(self, raw_data: bytes, start: int) -> None:
        self.total += len(raw_data)
        room = self.cap - self.buffer.tell()
        if room > 0:
            self.buffer.write(raw_data[:room])
        return None

    def file_complete(self, file_size: int) -> InMemoryUploadedFile:
        self.buffer.seek(0)
        return InMemoryUploadedFile(
            file=self.buffer,
            field_name=self.field_name,
            name=self.file_name,
            content_type=self.content_type,
            size=self.total,
            charset=self.charset,
            content_type_extra=self.content_type_extra,
        )


def capped_uploads(view: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
    """Swap in CappedUploadHandler before the body is parsed. Django parses the body during
    the CSRF check, so CSRF is exempted at the middleware and re-applied here afterwards."""
    protected = csrf_protect(view)

    @wraps(view)
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        request.upload_handlers = [CappedUploadHandler(request)]
        return protected(request, *args, **kwargs)

    return wrapped


# ----------------------------------------------------------------------- forms


def dataset_label(name: str) -> str:
    if not name:
        return _("Uploaded registry")
    return _("Synthetic data set: %(name)s") % {"name": name}


class UploadForm(forms.Form):
    file = forms.FileField(
        label=gettext_lazy("CSV file"),
        error_messages={
            "required": gettext_lazy("Choose a CSV file to upload."),
            "empty": gettext_lazy("The file is empty."),
        },
    )

    def __init__(self, *args: Any, datasets: list[str] | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if datasets is not None:
            choices = [(d, dataset_label(d)) for d in datasets] or [("", dataset_label(""))]
            self.fields["dataset"] = forms.ChoiceField(
                label=gettext_lazy("Match against"),
                choices=choices,
                initial=choices[0][0],
                required=False,  # "" (uploaded registry) is a valid choice
            )

    def clean_file(self) -> Any:
        upload = self.cleaned_data["file"]
        if upload.size > MAX_BYTES:
            raise forms.ValidationError(
                _("The file is larger than %(max)s. Split it into smaller files.")
                % {"max": filesizeformat(MAX_BYTES)}
            )
        return upload


# ---------------------------------------------------------------- shared flow


KIND_CONFIG = {
    uploads.LISTINGS: {
        "title": gettext_lazy("Upload listings"),
        "page": "upload_listings",
        "confirm": "upload_listings_confirm",
        "cancel": "upload_listings_cancel",
        "done": "runs",
    },
    uploads.REGISTRY: {
        "title": gettext_lazy("Upload registry"),
        "page": "upload_registry",
        "confirm": "upload_registry_confirm",
        "cancel": "upload_registry_cancel",
        "done": "upload_registry",
    },
}


def _datasets(kind: str) -> list[str] | None:
    return uploads.listing_datasets() if kind == uploads.LISTINGS else None


def _recent_batches(request: HttpRequest, kind: str) -> Any:
    qs = scoped(UploadBatch.objects.filter(type=kind), request.user)
    return qs.select_related("district", "uploader").order_by("-created_at", "-id")[:10]


def _context(request: HttpRequest, kind: str, **extra: Any) -> dict[str, Any]:
    config = KIND_CONFIG[kind]
    datasets = _datasets(kind)
    context = {
        "kind": kind,
        "title": config["title"],
        "page_url": reverse(config["page"]),
        "confirm_url": reverse(config["confirm"]),
        "cancel_url": reverse(config["cancel"]),
        "is_admin": is_admin(request.user),
        "max_bytes": MAX_BYTES,
        "max_rows": MAX_ROWS,
        "recent": _recent_batches(request, kind),
        "no_registry": kind == uploads.LISTINGS and not datasets,
        "own_district": None if is_admin(request.user) else request.user.district,
    }
    context.update(extra)
    return context


def _render_errors(
    request: HttpRequest, kind: str, form: UploadForm, check: uploads.UploadCheck, source: str
) -> HttpResponse:
    status = 400
    if check.out_of_district:
        uploads.audit_out_of_district(request.user, check, request.path, source)
        status = 403
    errors: list[LineError] = check.errors
    return render(
        request,
        "ingest/upload.html",
        _context(
            request,
            kind,
            form=form,
            errors=errors[:SHOW_ERRORS],
            more_errors=max(0, len(errors) - SHOW_ERRORS),
            error_count=len(errors),
            source_name=source,
            out_of_district=check.out_of_district,
        ),
        status=status,
    )


def _source_name(upload: Any) -> str:
    return PurePath(str(upload.name or "")).name[:255]


def _upload_page(request: HttpRequest, kind: str) -> HttpResponse:
    datasets = _datasets(kind)
    if request.method != "POST":
        form = UploadForm(datasets=datasets)
        return render(request, "ingest/upload.html", _context(request, kind, form=form))
    form = UploadForm(request.POST, request.FILES, datasets=datasets)
    if not form.is_valid():
        return render(request, "ingest/upload.html", _context(request, kind, form=form), status=400)
    upload = form.cleaned_data["file"]
    dataset = form.cleaned_data.get("dataset", "")
    data = upload.read()
    source = _source_name(upload)
    check = uploads.check_upload(kind, data, request.user, dataset)
    if not check.ok:
        return _render_errors(request, kind, form, check, source)
    token = uploads.stash(request.user, kind, data, source, dataset)
    return render(
        request,
        "ingest/preview.html",
        _context(
            request,
            kind,
            token=token,
            check=check,
            source_name=source,
            dataset=dataset,
            dataset_label=dataset_label(dataset),
            sample=[
                {"row": r, "district": check.row_districts.get(r.line)}
                for r in check.rows[:PREVIEW_ROWS]
            ],
            row_count=len(check.rows),
            district_counts=check.district_counts(),
        ),
    )


def _confirm(request: HttpRequest, kind: str) -> HttpResponse:
    config = KIND_CONFIG[kind]
    token = request.POST.get("token", "")
    item = uploads.pending(request.user, kind, token)
    if item is None:
        messages.error(request, _("This preview has expired or was already used. Upload again."))
        return redirect(config["page"])
    check = uploads.check_upload(kind, item.data, request.user, item.dataset)
    if not check.ok:
        uploads.discard(token)
        return _render_errors(
            request, kind, UploadForm(datasets=_datasets(kind)), check, item.source_name
        )
    try:
        batch = uploads.save_upload(check, request.user, item.source_name)
    except uploads.UploadRejected as exc:
        uploads.discard(token)
        check.errors = exc.errors
        return _render_errors(
            request, kind, UploadForm(datasets=_datasets(kind)), check, item.source_name
        )
    uploads.discard(token)
    messages.success(
        request,
        _("Saved %(rows)d rows from %(name)s (batch %(id)d).")
        % {"rows": batch.row_count, "name": batch.source_name or _("the file"), "id": batch.pk},
    )
    return redirect(config["done"])


def _cancel(request: HttpRequest, kind: str) -> HttpResponse:
    uploads.discard(request.POST.get("token", ""))
    messages.info(request, _("Upload cancelled. Nothing was saved."))
    return redirect(KIND_CONFIG[kind]["page"])


# ----------------------------------------------------------------------- views


@csrf_exempt  # CSRF is enforced by capped_uploads after the upload handler is set
@require_capability(Capability.UPLOAD_LISTINGS)
@require_http_methods(["GET", "POST"])
@capped_uploads
def upload_listings(request: HttpRequest) -> HttpResponse:
    return _upload_page(request, uploads.LISTINGS)


@require_capability(Capability.UPLOAD_LISTINGS)
@require_POST
def upload_listings_confirm(request: HttpRequest) -> HttpResponse:
    return _confirm(request, uploads.LISTINGS)


@require_capability(Capability.UPLOAD_LISTINGS)
@require_POST
def upload_listings_cancel(request: HttpRequest) -> HttpResponse:
    return _cancel(request, uploads.LISTINGS)


@csrf_exempt  # CSRF is enforced by capped_uploads after the upload handler is set
@require_capability(Capability.UPLOAD_REGISTRY)
@require_http_methods(["GET", "POST"])
@capped_uploads
def upload_registry(request: HttpRequest) -> HttpResponse:
    return _upload_page(request, uploads.REGISTRY)


@require_capability(Capability.UPLOAD_REGISTRY)
@require_POST
def upload_registry_confirm(request: HttpRequest) -> HttpResponse:
    return _confirm(request, uploads.REGISTRY)


@require_capability(Capability.UPLOAD_REGISTRY)
@require_POST
def upload_registry_cancel(request: HttpRequest) -> HttpResponse:
    return _cancel(request, uploads.REGISTRY)
