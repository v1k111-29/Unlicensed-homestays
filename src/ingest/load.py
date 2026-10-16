"""Load parsed CSV files into the database. All-or-nothing per call (one transaction).

Used by the `load_synthetic` management command (M2). The M7 upload views use
`ingest.uploads`, which shares the row builders below.

Terms used here:
- A "batch" (``UploadBatch``) is one saved file. Every saved row points back to its batch,
  so an officer can later see where a row came from and remove or review the whole file.
- A "dataset" is a label for a group of files that belong together, such as a synthetic
  test set. The empty string means an uploaded registry with no synthetic label.
- "Row builders" are the functions that turn parsed rows into unsaved model objects.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

from django.db import transaction
from django.utils.translation import gettext as _

import audit
from accounts.models import District
from ingest.csvtools import LineError
from ingest.parsers import (
    ListingRow,
    Parsed,
    RegistryRow,
    parse_ground_truth,
    parse_listings,
    parse_registry,
)
from listings.models import Listing
from matching.models import GroundTruth
from registry.models import RegistryEntry, UploadBatch


class LoadError(Exception):
    """Raised when a file cannot be saved. Carries the errors, so the caller can show them.

    The message lists at most the first 20 errors, so a file with thousands of problems does
    not flood the console or the logs.
    """

    def __init__(self, source: str, errors: list[LineError]) -> None:
        self.source = source
        self.errors = errors
        shown = "\n".join(f"  {e}" for e in errors[:20])
        more = f"\n  ... and {len(errors) - 20} more" if len(errors) > 20 else ""
        super().__init__(f"{source}: {len(errors)} error(s); nothing saved\n{shown}{more}")


@dataclass
class SetCounts:
    """How many rows were saved from each of the three files of one synthetic set."""

    registry: int
    listings: int
    ground_truth: int


def _raise_if(source: str, errors: list[LineError]) -> None:
    """Raise LoadError if there are any errors. Nothing is saved when this raises."""
    if errors:
        raise LoadError(source, errors)


def _districts(rows: list, source: str) -> dict[str, District]:
    """Return every district the file names, keyed by English name.

    A district name that is not in the database is an error for the whole file.
    Rows with an empty district are allowed here and are checked elsewhere.
    """
    by_name = {d.name_en: d for d in District.objects.all()}
    errors = [
        LineError(r.line, "district", _("unknown district '%(name)s'") % {"name": r.district})
        for r in rows
        if r.district and r.district not in by_name
    ]
    _raise_if(source, errors)
    return by_name


def _new_batch(kind: str, parsed: Parsed, source: str, dataset: str, **extra) -> UploadBatch:
    """Create the batch row for one file, unless this exact file was loaded before.

    The check uses the file's SHA-256 fingerprint plus its type and dataset. This stops the
    same file from being saved twice into the same dataset by accident.
    """
    if UploadBatch.objects.filter(type=kind, dataset=dataset, file_sha256=parsed.sha256).exists():
        raise LoadError(source, [LineError(0, "", already_loaded_message(dataset))])
    return UploadBatch.objects.create(
        type=kind,
        dataset=dataset,
        source_name=source,
        file_sha256=parsed.sha256,
        row_count=len(parsed.rows),
        **extra,
    )


def already_loaded_message(dataset: str) -> str:
    """The message shown when a file was already loaded. Shared with ``ingest.uploads``."""
    if dataset:
        return _("already loaded into dataset '%(dataset)s'") % {"dataset": dataset}
    return _("this file has already been uploaded")


def registry_objects(
    rows: list[RegistryRow], batch: UploadBatch, districts: dict[str, District]
) -> Iterator[RegistryEntry]:
    """Turn parsed registry rows into unsaved ``RegistryEntry`` objects.

    This is a generator: objects are made one at a time as ``bulk_create`` consumes them.
    Nothing is written to the database here.
    """
    for r in rows:
        yield RegistryEntry(
            licence_no=r.licence_no,
            name=r.name,
            address_en=r.address_en,
            address_ta=r.address_ta,
            locality=r.locality,
            pincode=r.pincode,
            lat=r.lat,
            lng=r.lng,
            category=r.category,
            valid_from=r.valid_from,
            valid_to=r.valid_to,
            status=r.status,
            batch=batch,
            district=districts[r.district],
        )


def listing_objects(
    rows: list[ListingRow], batch: UploadBatch, district_of: Callable[[ListingRow], District]
) -> Iterator[Listing]:
    """Turn parsed listing rows into unsaved ``Listing`` objects.

    ``district_of`` decides the district of each row. The caller supplies it, because an
    admin file names the district on each row, while an officer file uses the officer's own
    district.
    """
    for r in rows:
        yield Listing(
            source=Listing.Source.OFFICER_CSV,
            external_id=r.external_id,
            platform=r.platform,
            ref_url=r.ref_url,
            title=r.title,
            locality_text=r.locality_text,
            pincode=r.pincode,
            lat=r.lat,
            lng=r.lng,
            claimed_licence_no=r.claimed_licence_no,
            raw=r.raw,
            batch=batch,
            district=district_of(r),
        )


def load_registry(data: bytes, source: str, dataset: str, actor: str) -> UploadBatch:
    """Save a registry file in one transaction and write one audit entry. Returns the batch."""
    parsed = parse_registry(data)
    _raise_if(source, parsed.errors)
    # The transaction makes the batch row, its entries and the audit entry succeed or fail
    # together.
    with transaction.atomic():
        districts = _districts(parsed.rows, source)
        batch = _new_batch(UploadBatch.Type.REGISTRY, parsed, source, dataset)
        RegistryEntry.objects.bulk_create(registry_objects(parsed.rows, batch, districts))
        audit.log(actor, "registry_upload", "upload_batch", batch.pk, batch_meta(batch))
    return batch


def load_listings(data: bytes, source: str, dataset: str, actor: str) -> UploadBatch:
    """Admin-style load: every row names its district (D19)."""
    parsed = parse_listings(data, require_district=True)
    _raise_if(source, parsed.errors)
    with transaction.atomic():
        districts = _districts(parsed.rows, source)
        # The set of distinct district names in the file. If there is exactly one, the whole
        # batch belongs to that district. If there are several, the batch has no single
        # district and each listing keeps its own.
        names = {r.district for r in parsed.rows}
        batch = _new_batch(
            UploadBatch.Type.LISTINGS,
            parsed,
            source,
            dataset,
            district=districts[names.pop()] if len(names) == 1 else None,
        )
        Listing.objects.bulk_create(
            listing_objects(parsed.rows, batch, lambda r: districts[r.district])
        )
        audit.log(actor, "listings_upload", "upload_batch", batch.pk, batch_meta(batch))
    return batch


def load_ground_truth(
    data: bytes, source: str, listings_batch: UploadBatch, registry_batch: UploadBatch, actor: str
) -> int:
    """Labels join on `listing_id` (listings batch) and `licence_no` (registry batch).

    Ground truth is the answer key for the synthetic data: which registry entry each listing
    really belongs to. Each label must point at a listing and (if it names an entry) a
    registry entry that exist in the batches being loaded alongside it.
    """
    parsed = parse_ground_truth(data)
    _raise_if(source, parsed.errors)
    with transaction.atomic():
        # Look up the saved rows by their keys, so each label can be joined to its objects.
        listings = {lst.external_id: lst for lst in Listing.objects.filter(batch=listings_batch)}
        entries = {e.licence_no: e for e in RegistryEntry.objects.filter(batch=registry_batch)}
        errors = []
        for r in parsed.rows:
            if r.listing_id not in listings:
                errors.append(LineError(r.line, "listing_id", "not in the listings batch"))
            if r.true_registry_id and r.true_registry_id not in entries:
                errors.append(LineError(r.line, "true_registry_id", "not in the registry batch"))
        _raise_if(source, errors)
        # An empty true_registry_id is stored as None (no entry), not as an error. That is how
        # labels for listings with no real counterpart are represented.
        GroundTruth.objects.bulk_create(
            GroundTruth(
                listing=listings[r.listing_id],
                true_registry_entry=entries.get(r.true_registry_id),
                type=r.type,
                noise=r.noise,
            )
            for r in parsed.rows
        )
        audit.log(
            actor,
            "ground_truth_load",
            "upload_batch",
            listings_batch.pk,
            {"source": source, "sha256": parsed.sha256, "row_count": len(parsed.rows)},
        )
    return len(parsed.rows)


def load_synthetic_set(folder: Path, dataset: str, actor: str) -> SetCounts:
    """Load registry.csv, listings.csv and ground_truth.csv from one M1 output folder.
    One transaction: if any file fails, nothing from the set is saved."""
    files = {name: folder / f"{name}.csv" for name in ("registry", "listings", "ground_truth")}
    for path in files.values():
        if not path.is_file():
            raise LoadError(str(path), [LineError(0, "", "file not found")])
    # Registry and listings are loaded first, because the ground truth refers to both.
    with transaction.atomic():
        reg = load_registry(files["registry"].read_bytes(), _rel(files["registry"]), dataset, actor)
        lst = load_listings(files["listings"].read_bytes(), _rel(files["listings"]), dataset, actor)
        gt = load_ground_truth(
            files["ground_truth"].read_bytes(), _rel(files["ground_truth"]), lst, reg, actor
        )
    return SetCounts(registry=reg.row_count, listings=lst.row_count, ground_truth=gt)


def _rel(path: Path) -> str:
    """Return the last three parts of a path, so the stored source name is not a local path."""
    parts = path.resolve().parts
    return "/".join(parts[-3:])  # e.g. "out/dev/registry.csv"; no absolute local paths stored


def batch_meta(batch: UploadBatch) -> dict:
    """The facts about one batch that go into its audit entry."""
    return {
        "type": batch.type,
        "dataset": batch.dataset,
        "source": batch.source_name,
        "sha256": batch.file_sha256,
        "row_count": batch.row_count,
    }
