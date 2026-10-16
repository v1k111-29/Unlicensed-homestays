"""Upload pages (M7): listings (officer, admin) and registry (admin).

Flow: choose file → preview (row count, districts, first rows) → confirm or cancel. Business
rules live in `ingest.uploads`; this module only handles HTTP and templates.

The file field is read through `CappedUploadHandler`, so at most MAX_BYTES + 1 bytes of an
upload are ever held, in memory, and nothing is written to disk (D67).

Each upload kind has four URLs (page, confirm, cancel, done). ``KIND_CONFIG`` names them, so
the same code serves both kinds.
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

# How many rows the preview page shows. The full file is still checked and saved.
PREVIEW_ROWS = 20
# How many errors the error page lists. The count of the rest is shown as "and N more".
SHOW_ERRORS = 200


class CappedUploadHandler(FileUploadHandler):
    """Keeps at most `cap` bytes of each uploaded file in memory and only counts the rest, so
    an oversized file is reported by its real size without being stored anywhere."""

    # One byte more than the limit. A file of exactly MAX_BYTES stays valid, and a file one
    # byte over is detected by its size, which is checked by the form.
    cap = MAX_BYTES + 1

    def new_file(self, *args: Any, **kwargs: Any) -> None:
        """Start a new file: make an empty buffer and reset the byte counter."""
        super().new_file(*args, **kwargs)
        self.buffer = io.BytesIO()
        self.total = 0

    def receive_data_chunk(self, raw_data: bytes, start: int) -> None:
        """Keep the part of this chunk that fits under the cap. Count every byte anyway.

        Returning None stops Django from passing this chunk on to any later upload handler.
        """
        self.total += len(raw_data)
        room = self.cap - self.buffer.tell()
        if room > 0:
            self.buffer.write(raw_data[:room])
        return None

    def file_complete(self, file_size: int) -> InMemoryUploadedFile:
        """Wrap the kept bytes in an in-memory file.

        The ``size`` given to the file is the real total, not just the bytes that were kept.
        """
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
        """Install the capped handler, then run the view with CSRF protection."""
        request.upload_handlers = [CappedUploadHandler(request)]
        return protected(request, *args, **kwargs)

    return wrapped


# ----------------------------------------------------------------------- forms


def dataset_label(name: str) -> str:
    """The text shown for a data set. The empty name means an uploaded registry."""
    if not name:
        return _("Uploaded registry")
    return _("Synthetic data set: %(name)s") % {"name": name}


class UploadForm(forms.Form):
    """The upload form: one file, and (for listings) a data set to match against."""

    file = forms.FileField(
        label=gettext_lazy("CSV file"),
        error_messages={
            "required": gettext_lazy("Choose a CSV file to upload."),
            "empty": gettext_lazy("The file is empty."),
        },
    )

    def __init__(self, *args: Any, datasets: list[str] | None = None, **kwargs: Any) -> None:
        """Add the data-set choice only when the caller passes the list of data sets."""
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
        """Reject a file over the size limit. The message suggests splitting it."""
        upload = self.cleaned_data["file"]
        if upload.size > MAX_BYTES:
            raise forms.ValidationError(
                _("The file is larger than %(max)s. Split it into smaller files.")
                % {"max": filesizeformat(MAX_BYTES)}
            )
        return upload


# ---------------------------------------------------------------- shared flow


# The URL names and page titles for each upload kind. Only the names differ between kinds.
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
    """The data sets to offer. Only listings uploads have a choice; the registry has none."""
    return uploads.listing_datasets() if kind == uploads.LISTINGS else None


def _recent_batches(request: HttpRequest, kind: str) -> Any:
    """The ten newest batches of this kind that the user is allowed to see."""
    qs = scoped(UploadBatch.objects.filter(type=kind), request.user)
    return qs.select_related("district", "uploader").order_by("-created_at", "-id")[:10]


def _context(request: HttpRequest, kind: str, **extra: Any) -> dict[str, Any]:
    """Build the template context shared by every upload page. ``extra`` adds page-specific keys."""
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
        # True when a listings page has no registry to match against, so it can say so.
        "no_registry": kind == uploads.LISTINGS and not datasets,
        "own_district": None if is_admin(request.user) else request.user.district,
    }
    context.update(extra)
    return context


def _render_errors(
    request: HttpRequest, kind: str, form: UploadForm, check: uploads.UploadCheck, source: str
) -> HttpResponse:
    """Show the error page for a rejected file.

    A file refused for naming another district gets status 403 and an audit entry (D30).
    Every other rejection gets status 400.
    """
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
    """The file name without any folder part, cut to 255 characters.

    ``PurePath`` removes folders such as ``C:\\Users\\...`` that some browsers send, so the
    stored name does not reveal a local path.
    """
    return PurePath(str(upload.name or "")).name[:255]


def _upload_page(request: HttpRequest, kind: str) -> HttpResponse:
    """The shared upload page: show the form on GET, and check the file on POST."""
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
    # Keep the good file for the confirm step. Nothing is saved yet.
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
    """Save the file the user previewed, after checking it again."""
    config = KIND_CONFIG[kind]
    token = request.POST.get("token", "")
    item = uploads.pending(request.user, kind, token)
    if item is None:
        messages.error(request, _("This preview has expired or was already used. Upload again."))
        return redirect(config["page"])
    # Check again, because the rules or the database may have changed since the preview.
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
    # The token is used up once the file is saved, so a second confirm cannot save it again.
    uploads.discard(token)
    messages.success(
        request,
        _("Saved %(rows)d rows from %(name)s (batch %(id)d).")
        % {"rows": batch.row_count, "name": batch.source_name or _("the file"), "id": batch.pk},
    )
    return redirect(config["done"])


def _cancel(request: HttpRequest, kind: str) -> HttpResponse:
    """Throw away the previewed file. Nothing has been saved, so nothing needs undoing."""
    # Only the user's own pending upload of this kind may be discarded; another user's token
    # or a token of the other kind is left alone (the message is the same either way).
    item = uploads.pending(request.user, kind, request.POST.get("token", ""))
    if item is not None:
        uploads.discard(item.token)
    messages.info(request, _("Upload cancelled. Nothing was saved."))
    return redirect(KIND_CONFIG[kind]["page"])


# ----------------------------------------------------------------------- views


@csrf_exempt  # CSRF is enforced by capped_uploads after the upload handler is set
@require_capability(Capability.UPLOAD_LISTINGS)
@require_http_methods(["GET", "POST"])
@capped_uploads
def upload_listings(request: HttpRequest) -> HttpResponse:
    """The listings upload page (officers and admins)."""
    return _upload_page(request, uploads.LISTINGS)


@require_capability(Capability.UPLOAD_LISTINGS)
@require_POST
def upload_listings_confirm(request: HttpRequest) -> HttpResponse:
    """Save the previewed listings file."""
    return _confirm(request, uploads.LISTINGS)


@require_capability(Capability.UPLOAD_LISTINGS)
@require_POST
def upload_listings_cancel(request: HttpRequest) -> HttpResponse:
    """Discard the previewed listings file."""
    return _cancel(request, uploads.LISTINGS)


@csrf_exempt  # CSRF is enforced by capped_uploads after the upload handler is set
@require_capability(Capability.UPLOAD_REGISTRY)
@require_http_methods(["GET", "POST"])
@capped_uploads
def upload_registry(request: HttpRequest) -> HttpResponse:
    """The registry upload page (admins only)."""
    return _upload_page(request, uploads.REGISTRY)


@require_capability(Capability.UPLOAD_REGISTRY)
@require_POST
def upload_registry_confirm(request: HttpRequest) -> HttpResponse:
    """Save the previewed registry file."""
    return _confirm(request, uploads.REGISTRY)


@require_capability(Capability.UPLOAD_REGISTRY)
@require_POST
def upload_registry_cancel(request: HttpRequest) -> HttpResponse:
    """Discard the previewed registry file."""
    return _cancel(request, uploads.REGISTRY)
