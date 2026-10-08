"""Load parsed CSV files into the database. All-or-nothing per call (one transaction).

Used by the `load_synthetic` management command (M2). M7 upload views will reuse the
registry/listings functions with a real uploader.
"""

from dataclasses import dataclass
from pathlib import Path

from django.db import transaction

import audit
from accounts.models import District
from ingest.csvtools import LineError
from ingest.parsers import Parsed, parse_ground_truth, parse_listings, parse_registry
from listings.models import Listing
from matching.models import GroundTruth
from registry.models import RegistryEntry, UploadBatch


class LoadError(Exception):
    def __init__(self, source: str, errors: list[LineError]) -> None:
        self.source = source
        self.errors = errors
        shown = "\n".join(f"  {e}" for e in errors[:20])
        more = f"\n  ... and {len(errors) - 20} more" if len(errors) > 20 else ""
        super().__init__(f"{source}: {len(errors)} error(s); nothing saved\n{shown}{more}")


@dataclass
class SetCounts:
    registry: int
    listings: int
    ground_truth: int


def _raise_if(source: str, errors: list[LineError]) -> None:
    if errors:
        raise LoadError(source, errors)


def _districts(rows: list, source: str) -> dict[str, District]:
    by_name = {d.name_en: d for d in District.objects.all()}
    errors = [
        LineError(r.line, "district", f"unknown district '{r.district}'")
        for r in rows
        if r.district and r.district not in by_name
    ]
    _raise_if(source, errors)
    return by_name


def _new_batch(kind: str, parsed: Parsed, source: str, dataset: str, **extra) -> UploadBatch:
    if UploadBatch.objects.filter(type=kind, dataset=dataset, file_sha256=parsed.sha256).exists():
        raise LoadError(source, [LineError(0, "", f"already loaded into dataset '{dataset}'")])
    return UploadBatch.objects.create(
        type=kind,
        dataset=dataset,
        source_name=source,
        file_sha256=parsed.sha256,
        row_count=len(parsed.rows),
        **extra,
    )


def load_registry(data: bytes, source: str, dataset: str, actor: str) -> UploadBatch:
    parsed = parse_registry(data)
    _raise_if(source, parsed.errors)
    with transaction.atomic():
        districts = _districts(parsed.rows, source)
        batch = _new_batch(UploadBatch.Type.REGISTRY, parsed, source, dataset)
        RegistryEntry.objects.bulk_create(
            RegistryEntry(
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
            for r in parsed.rows
        )
        audit.log(actor, "registry_upload", "upload_batch", batch.pk, _batch_meta(batch))
    return batch


def load_listings(data: bytes, source: str, dataset: str, actor: str) -> UploadBatch:
    """Admin-style load: every row names its district (D19)."""
    parsed = parse_listings(data, require_district=True)
    _raise_if(source, parsed.errors)
    with transaction.atomic():
        districts = _districts(parsed.rows, source)
        names = {r.district for r in parsed.rows}
        batch = _new_batch(
            UploadBatch.Type.LISTINGS,
            parsed,
            source,
            dataset,
            district=districts[names.pop()] if len(names) == 1 else None,
        )
        Listing.objects.bulk_create(
            Listing(
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
                district=districts[r.district],
            )
            for r in parsed.rows
        )
        audit.log(actor, "listings_upload", "upload_batch", batch.pk, _batch_meta(batch))
    return batch


def load_ground_truth(
    data: bytes, source: str, listings_batch: UploadBatch, registry_batch: UploadBatch, actor: str
) -> int:
    """Labels join on `listing_id` (listings batch) and `licence_no` (registry batch)."""
    parsed = parse_ground_truth(data)
    _raise_if(source, parsed.errors)
    with transaction.atomic():
        listings = {lst.external_id: lst for lst in Listing.objects.filter(batch=listings_batch)}
        entries = {e.licence_no: e for e in RegistryEntry.objects.filter(batch=registry_batch)}
        errors = []
        for r in parsed.rows:
            if r.listing_id not in listings:
                errors.append(LineError(r.line, "listing_id", "not in the listings batch"))
            if r.true_registry_id and r.true_registry_id not in entries:
                errors.append(LineError(r.line, "true_registry_id", "not in the registry batch"))
        _raise_if(source, errors)
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
    with transaction.atomic():
        reg = load_registry(files["registry"].read_bytes(), _rel(files["registry"]), dataset, actor)
        lst = load_listings(files["listings"].read_bytes(), _rel(files["listings"]), dataset, actor)
        gt = load_ground_truth(
            files["ground_truth"].read_bytes(), _rel(files["ground_truth"]), lst, reg, actor
        )
    return SetCounts(registry=reg.row_count, listings=lst.row_count, ground_truth=gt)


def _rel(path: Path) -> str:
    parts = path.resolve().parts
    return "/".join(parts[-3:])  # e.g. "out/dev/registry.csv"; no absolute local paths stored


def _batch_meta(batch: UploadBatch) -> dict:
    return {
        "type": batch.type,
        "dataset": batch.dataset,
        "source": batch.source_name,
        "sha256": batch.file_sha256,
        "row_count": batch.row_count,
    }
