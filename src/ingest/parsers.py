"""Parse registry, listings and ground-truth CSV files into plain rows. No database access.

Column sets follow docs/data-and-matching.md §1 and the M1 generator (D35). District names are
returned as text; the loader resolves them against the `District` table.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils.translation import gettext as _

from ingest.csvtools import CsvTable, LineError, RowChecker, read_csv

REGISTRY_REQUIRED = ["licence_no", "name", "locality", "district", "valid_to"]
REGISTRY_OPTIONAL = [
    "address_en",
    "address_ta",
    "pincode",
    "lat",
    "lng",
    "category",
    "valid_from",
    "status",
]
REGISTRY_CATEGORIES = ["homestay", "cottage", "guest_house", "lodge"]
REGISTRY_STATUSES = ["active", "expired", "suspended"]

LISTING_REQUIRED = ["platform", "title", "locality_text"]
# `listing_id` is the synthetic join key (D35); stored as Listing.external_id when present.
LISTING_OPTIONAL = [
    "listing_id",
    "ref_url",
    "pincode",
    "lat",
    "lng",
    "claimed_licence_no",
    "notes",
    "district",
]

GROUND_TRUTH_REQUIRED = ["listing_id", "true_registry_id", "type"]
GROUND_TRUTH_OPTIONAL = ["noise"]
GROUND_TRUTH_TYPES = ["clean", "noisy", "wrong_or_expired", "no_counterpart", "hard_negative"]


@dataclass
class RegistryRow:
    line: int
    licence_no: str
    name: str
    address_en: str
    address_ta: str
    locality: str
    pincode: str
    lat: Decimal | None
    lng: Decimal | None
    category: str
    valid_from: date | None
    valid_to: date | None
    status: str
    district: str


@dataclass
class ListingRow:
    line: int
    external_id: str
    platform: str
    ref_url: str
    title: str
    locality_text: str
    pincode: str
    lat: Decimal | None
    lng: Decimal | None
    claimed_licence_no: str
    district: str
    raw: dict[str, str]


@dataclass
class GroundTruthRow:
    line: int
    listing_id: str
    true_registry_id: str
    type: str
    noise: str


@dataclass
class Parsed:
    sha256: str
    rows: list
    errors: list[LineError]

    @property
    def ok(self) -> bool:
        return not self.errors


def _duplicates(table: CsvTable, column: str, errors: list[LineError]) -> None:
    first: dict[str, int] = {}
    for line, row in table.rows:
        value = row.get(column, "")
        if not value:
            continue
        if value in first:
            errors.append(
                LineError(line, column, _("duplicate of line %(line)d") % {"line": first[value]})
            )
        else:
            first[value] = line


def parse_registry(data: bytes) -> Parsed:
    table = read_csv(data, REGISTRY_REQUIRED, REGISTRY_OPTIONAL)
    errors = list(table.errors)
    rows: list[RegistryRow] = []
    for line, row in table.rows:
        c = RowChecker(line, row, errors)
        lat, lng = c.coords()
        entry = RegistryRow(
            line=line,
            licence_no=c.text("licence_no", 64, required=True),
            name=c.text("name", 255, required=True),
            address_en=c.text("address_en", 500),
            address_ta=c.text("address_ta", 500),
            locality=c.text("locality", 255, required=True),
            pincode=c.pincode(),
            lat=lat,
            lng=lng,
            category=c.choice("category", REGISTRY_CATEGORIES),
            valid_from=c.date("valid_from"),
            valid_to=c.date("valid_to", required=True),
            status=c.choice("status", REGISTRY_STATUSES) or "active",
            district=c.text("district", 100, required=True),
        )
        if entry.valid_from and entry.valid_to and entry.valid_from > entry.valid_to:
            c.error("valid_from", _("is after valid_to"))
        rows.append(entry)
    _duplicates(table, "licence_no", errors)
    return Parsed(table.sha256, rows, sorted(errors, key=lambda e: e.line))


def parse_listings(data: bytes, require_district: bool) -> Parsed:
    """`require_district` is True for admin and synthetic loads (D19)."""
    table = read_csv(data, LISTING_REQUIRED, LISTING_OPTIONAL)
    errors = list(table.errors)
    rows: list[ListingRow] = []
    for line, row in table.rows:
        c = RowChecker(line, row, errors)
        lat, lng = c.coords()
        rows.append(
            ListingRow(
                line=line,
                external_id=c.text("listing_id", 64),
                platform=c.text("platform", 64, required=True),
                ref_url=c.text("ref_url", 500),
                title=c.text("title", 255, required=True),
                locality_text=c.text("locality_text", 255, required=True),
                pincode=c.pincode(),
                lat=lat,
                lng=lng,
                claimed_licence_no=c.text("claimed_licence_no", 64),
                district=c.text("district", 100, required=require_district),
                raw=dict(row),
            )
        )
    _duplicates(table, "listing_id", errors)
    return Parsed(table.sha256, rows, sorted(errors, key=lambda e: e.line))


def parse_ground_truth(data: bytes) -> Parsed:
    table = read_csv(data, GROUND_TRUTH_REQUIRED, GROUND_TRUTH_OPTIONAL)
    errors = list(table.errors)
    rows: list[GroundTruthRow] = []
    for line, row in table.rows:
        c = RowChecker(line, row, errors)
        truth = GroundTruthRow(
            line=line,
            listing_id=c.text("listing_id", 64, required=True),
            true_registry_id=c.text("true_registry_id", 64),
            type=c.choice("type", GROUND_TRUTH_TYPES, required=True),
            noise=c.text("noise", 100),
        )
        needs_entry = truth.type in ("clean", "noisy", "wrong_or_expired")
        if needs_entry and not truth.true_registry_id:
            c.error("true_registry_id", _("required for type '%(type)s'") % {"type": truth.type})
        if truth.type in ("no_counterpart", "hard_negative") and truth.true_registry_id:
            c.error(
                "true_registry_id", _("must be empty for type '%(type)s'") % {"type": truth.type}
            )
        rows.append(truth)
    _duplicates(table, "listing_id", errors)
    return Parsed(table.sha256, rows, sorted(errors, key=lambda e: e.line))
