"""Web uploads (M7, essentialfeatures.md O2/O6): check a CSV for a user, keep it pending until
the user confirms, then save it in one transaction with one audit entry.

Three steps, in order:
1. Check: ``check_upload`` parses the file and tests every rule for this user. It writes nothing.
2. Stash: a valid file is kept in the cache under a random token until the user confirms.
3. Save: on confirm, the file is checked again and then written in one transaction.

Rules in this module:
- Nothing is written to the data tables or the audit log before confirm. A valid file waits in
  the cache (shared by all workers) for PENDING_SECONDS, bound to the user who previewed it.
  An invalid file is not kept at all.
- Listings: the batch district is the officer's district; rows may name it in a `district`
  column. A row naming another district rejects the whole file and is audit-logged (D30).
  Admin uploads must name a district on every row (D19).
- Registry (admin only): every row names its district. A new registry upload becomes the
  current registry for its data set (Q17 default); older batches stay for history.
- Re-checked at confirm, so a change in between (e.g. the same file confirmed twice) is caught.
"""

from __future__ import annotations

import re
import secrets
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils.translation import gettext as _

import audit
from accounts.models import District
from accounts.permissions import is_admin
from accounts.scoping import can_act_in_district
from ingest.csvtools import LineError
from ingest.load import already_loaded_message, batch_meta, listing_objects, registry_objects
from ingest.parsers import ListingRow, parse_listings, parse_registry
from listings.models import Listing
from registry.models import RESERVED_DATASETS, RegistryEntry, UploadBatch

# How long a checked file waits for the user to confirm. Same length as the idle session timeout.
PENDING_SECONDS = 30 * 60
# A pending-upload token is 20 to 64 characters of URL-safe text. Anything else is rejected
# before the cache is touched, so a forged token never reaches the cache lookup.
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
# Cache key template. The token fills in the {}.
_KEY = "upload-pending:{}"

LISTINGS = UploadBatch.Type.LISTINGS
REGISTRY = UploadBatch.Type.REGISTRY


class UploadRejected(Exception):
    """Raised when a file that passed the check is still refused at save time."""

    def __init__(self, errors: list[LineError]) -> None:
        super().__init__("; ".join(str(e) for e in errors))
        self.errors = errors


@dataclass
class UploadCheck:
    """The result of checking one file for one user. Read-only: holds no database changes.

    ``row_districts`` maps each good row's line number to its district. ``out_of_district_lines``
    lists lines that name a district the user may not upload to.
    """

    kind: str
    sha256: str
    dataset: str
    rows: list = field(default_factory=list)
    errors: list[LineError] = field(default_factory=list)
    batch_district: District | None = None
    row_districts: dict[int, District] = field(default_factory=dict)  # line -> district
    out_of_district_lines: list[int] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the file has no errors, so it can be previewed and saved."""
        return not self.errors

    @property
    def out_of_district(self) -> bool:
        """True when at least one row names a district the user may not upload to."""
        return bool(self.out_of_district_lines)

    def district_counts(self) -> list[tuple[District, int]]:
        """How many rows fall in each district, sorted by district name."""
        counts = Counter(d.pk for d in self.row_districts.values())
        by_pk = {d.pk: d for d in self.row_districts.values()}
        return sorted(((by_pk[pk], n) for pk, n in counts.items()), key=lambda x: x[0].name_en)


# ------------------------------------------------------------------ data sets


def registry_datasets() -> list[str]:
    """Data-set labels that have a registry batch, most recently uploaded first."""
    seen: list[str] = []
    for label in (
        UploadBatch.objects.filter(type=REGISTRY)
        .order_by("-created_at", "-id")
        .values_list("dataset", flat=True)
    ):
        # Keep only the first (newest) occurrence of each label, so the list is in upload order.
        if label not in seen:
            seen.append(label)
    return seen


def listing_datasets() -> list[str]:
    """Data sets a listings upload may be matched against (excludes RESERVED_DATASETS)."""
    return [d for d in registry_datasets() if d not in RESERVED_DATASETS]


# ---------------------------------------------------------------------- checks


def _districts_by_name() -> dict[str, District]:
    """Every district, keyed by its English name."""
    return {d.name_en: d for d in District.objects.all()}


def _duplicate(kind: str, dataset: str, sha256: str) -> LineError | None:
    """Return an error if this exact file was already saved for this type and dataset."""
    if UploadBatch.objects.filter(type=kind, dataset=dataset, file_sha256=sha256).exists():
        return LineError(0, "", already_loaded_message(dataset))
    return None


def check_listings(data: bytes, user: Any, dataset: str) -> UploadCheck:
    """Validate a listings file for `user` (officer or admin). No writes."""
    admin = is_admin(user)
    parsed = parse_listings(data, require_district=admin)
    check = UploadCheck(LISTINGS, parsed.sha256, dataset, parsed.rows, list(parsed.errors))
    # The data set must exist and must be one a listings file may be matched against.
    if dataset in RESERVED_DATASETS or (dataset and dataset not in registry_datasets()):
        check.errors.append(LineError(0, "", _("unknown data set '%(name)s'") % {"name": dataset}))
    by_name = _districts_by_name()
    # An officer's own district is their default. Admins have no default: they must name one.
    own = None if admin else user.district
    for r in parsed.rows:
        if not r.district:
            if own is not None:
                check.row_districts[r.line] = own
            continue
        district = by_name.get(r.district)
        if district is None:
            check.errors.append(
                LineError(
                    r.line, "district", _("unknown district '%(name)s'") % {"name": r.district}
                )
            )
        elif not can_act_in_district(user, district):
            # Recorded separately, so the caller can write an audit entry for the refusal (D30).
            check.out_of_district_lines.append(r.line)
            check.errors.append(
                LineError(
                    r.line,
                    "district",
                    _(
                        "district '%(name)s' is not your district (%(own)s); you can upload "
                        "listings for your own district only, so the whole file is rejected"
                    )
                    % {"name": r.district, "own": own.name_en if own else ""},
                )
            )
        else:
            check.row_districts[r.line] = district
    # The batch gets one district only when every row names the same one. Otherwise it has
    # none. An officer's batch always belongs to the officer's own district.
    if admin:
        names = {d.pk: d for d in check.row_districts.values()}
        check.batch_district = next(iter(names.values())) if len(names) == 1 else None
    else:
        check.batch_district = own
    # The duplicate check is a database query, so it runs only when the rest of the file is
    # valid.
    if parsed.ok and (dup := _duplicate(LISTINGS, dataset, parsed.sha256)):
        check.errors.append(dup)
    check.errors.sort(key=lambda e: e.line)
    return check


def check_registry(data: bytes) -> UploadCheck:
    """Validate a registry file (admin). No writes. Uploaded registries use data set ""."""
    parsed = parse_registry(data)
    check = UploadCheck(REGISTRY, parsed.sha256, "", parsed.rows, list(parsed.errors))
    by_name = _districts_by_name()
    for r in parsed.rows:
        district = by_name.get(r.district)
        if district is None:
            # An empty district was already reported by the parser as a missing value, so an
            # empty name is not reported a second time here.
            if r.district:
                check.errors.append(
                    LineError(
                        r.line, "district", _("unknown district '%(name)s'") % {"name": r.district}
                    )
                )
        else:
            check.row_districts[r.line] = district
    if parsed.ok and (dup := _duplicate(REGISTRY, "", parsed.sha256)):
        check.errors.append(dup)
    check.errors.sort(key=lambda e: e.line)
    return check


def check_upload(kind: str, data: bytes, user: Any, dataset: str = "") -> UploadCheck:
    """Check a file of the given kind. Routes to the listings or the registry checker."""
    if kind == LISTINGS:
        return check_listings(data, user, dataset)
    return check_registry(data)


def audit_out_of_district(user: Any, check: UploadCheck, path: str, source_name: str) -> None:
    """The whole file was refused because rows name another district (D30)."""
    names = sorted({r.district for r in check.rows if r.line in check.out_of_district_lines})
    audit.log(
        user,
        "permission_denied",
        "upload",
        "",
        {
            "reason": "out_of_district",
            "kind": check.kind,
            "path": path[:200],  # cut to 200 characters so the audit entry stays small
            "source": source_name,
            "sha256": check.sha256,
            "districts": names,
            "lines": check.out_of_district_lines[:50],  # first 50 line numbers only
            "line_count": len(check.out_of_district_lines),
        },
    )


# ------------------------------------------------------------------------ save


def save_upload(check: UploadCheck, user: Any, source_name: str) -> UploadBatch:
    """Store a checked file: batch + rows + one audit entry, all or nothing."""
    if not check.ok:
        raise UploadRejected(check.errors)
    try:
        with transaction.atomic():
            batch = UploadBatch.objects.create(
                type=check.kind,
                uploader=user,
                district=check.batch_district,
                dataset=check.dataset,
                source_name=source_name[:255],  # cut to 255 characters to keep it short
                file_sha256=check.sha256,
                row_count=len(check.rows),
            )
            if check.kind == LISTINGS:

                def district_of(row: ListingRow) -> District:
                    """Return the district that was checked for this row."""
                    return check.row_districts[row.line]

                Listing.objects.bulk_create(listing_objects(check.rows, batch, district_of))
            else:
                # The registry builder takes a name-to-district map, so build it from the rows.
                names = {d.name_en: d for d in check.row_districts.values()}
                RegistryEntry.objects.bulk_create(registry_objects(check.rows, batch, names))
            # Audit entry: the usual batch facts, plus the district split and the fact that
            # the upload came through the web.
            meta = batch_meta(batch) | {
                "district": check.batch_district.name_en if check.batch_district else "",
                "districts": {d.name_en: n for d, n in check.district_counts()},
                "via": "web",
            }
            audit.log(user, f"{check.kind}_upload", "upload_batch", batch.pk, meta)
    except IntegrityError:
        # Same file confirmed twice at the same moment: the unique constraint wins.
        raise UploadRejected([LineError(0, "", already_loaded_message(check.dataset))]) from None
    return batch


# --------------------------------------------------------------------- pending


@dataclass
class Pending:
    """A checked file waiting in the cache for the user to confirm it."""

    token: str
    kind: str
    data: bytes
    source_name: str
    dataset: str


def stash(user: Any, kind: str, data: bytes, source_name: str, dataset: str) -> str:
    """Keep a checked file in the cache for PENDING_SECONDS and return its token.

    The token is 32 random bytes, encoded as URL-safe text. A guess would be practically
    impossible, so a token alone is enough to find the file.
    """
    token = secrets.token_urlsafe(32)
    cache.set(
        _KEY.format(token),
        {
            "user": user.pk,  # only this user may later confirm the file
            "kind": kind,
            "data": data,
            "source_name": source_name,
            "dataset": dataset,
        },
        timeout=PENDING_SECONDS,
    )
    return token


def pending(user: Any, kind: str, token: str) -> Pending | None:
    """The pending upload for this token, if it belongs to `user` and is of `kind`."""
    if not _TOKEN.match(token or ""):
        return None
    value = cache.get(_KEY.format(token))
    # Returns None for a different user or kind, so no other user can confirm the file.
    if not value or value.get("user") != user.pk or value.get("kind") != kind:
        return None
    return Pending(token, kind, value["data"], value["source_name"], value["dataset"])


def discard(token: str) -> None:
    """Remove a pending upload from the cache. A malformed token is ignored, not an error."""
    if _TOKEN.match(token or ""):
        cache.delete(_KEY.format(token))
