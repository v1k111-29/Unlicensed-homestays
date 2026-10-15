"""Parse registry, listings and ground-truth CSV files into plain rows. No database access.

Column sets follow docs/data-and-matching.md §1 and the M1 generator (D35). District names are
returned as text; the loader resolves them against the `District` table.

Each ``parse_*`` function does the same three things:
1. Read the file with ``read_csv``, which checks the header and the raw cells.
2. Turn each row into a small dataclass (``RegistryRow``, ``ListingRow``, ...), using a
   ``RowChecker`` to validate every field as it goes.
3. Check the whole file for duplicates, then return a ``Parsed`` object. Its ``errors`` list
   is sorted by line number, so the user sees the errors in file order.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.utils.translation import gettext as _

from ingest.csvtools import CsvTable, LineError, RowChecker, read_csv

# "Required" means the column must be present in the header. Whether each cell is filled in
# is checked separately, per column, in the parse function.
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
# The allowed values for the choice columns. Anything else is an error for that row.
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
# The five kinds of listing in the synthetic answer key (see synthetic-data-spec.md).
GROUND_TRUTH_TYPES = ["clean", "noisy", "wrong_or_expired", "no_counterpart", "hard_negative"]


@dataclass
class RegistryRow:
    """One validated row of a registry file, ready to become a ``RegistryEntry``."""

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
    """One validated row of a listings file, ready to become a ``Listing``.

    ``raw`` keeps the whole original row as text, so nothing the officer typed is lost even
    when it is not one of the named fields.
    """

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
    """One validated label from the synthetic answer key."""

    line: int
    listing_id: str
    true_registry_id: str
    type: str
    noise: str


@dataclass
class Parsed:
    """The result of parsing one file.

    ``sha256`` fingerprints the raw bytes. ``rows`` holds the row objects, and ``errors``
    lists every problem found. A file is safe to save only when ``ok`` is True.
    """

    sha256: str
    rows: list
    errors: list[LineError]

    @property
    def ok(self) -> bool:
        """True when the file had no errors at all."""
        return not self.errors


def _duplicates(table: CsvTable, column: str, errors: list[LineError]) -> None:
    """Add an error for every row whose value in ``column`` was already seen above it.

    Empty values are skipped, so several rows with no key do not count as duplicates.
    Each error names the first line that had the value.
    """
    first: dict[str, int] = {}  # value -> line where it was first seen
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
    """Parse a registry file (licensed properties). Returns rows and every error found."""
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
            # An empty status means the entry is active. "or" applies this default only when
            # the choice check returned an empty string.
            status=c.choice("status", REGISTRY_STATUSES) or "active",
            district=c.text("district", 100, required=True),
        )
        # A licence cannot start after it ends. Both dates must be present to compare them.
        if entry.valid_from and entry.valid_to and entry.valid_from > entry.valid_to:
            c.error("valid_from", _("is after valid_to"))
        rows.append(entry)
    _duplicates(table, "licence_no", errors)
    # Sort by line so the errors read in file order, not in the order the checks ran.
    return Parsed(table.sha256, rows, sorted(errors, key=lambda e: e.line))


def parse_listings(data: bytes, require_district: bool) -> Parsed:
    """Parse a listings file (online homestay listings to be checked).

    `require_district` is True for admin and synthetic loads (D19). Officer uploads may leave
    the district empty, because the upload uses the officer's own district.
    """
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
                raw=dict(row),  # a copy, so later changes to `row` cannot change this entry
            )
        )
    _duplicates(table, "listing_id", errors)
    return Parsed(table.sha256, rows, sorted(errors, key=lambda e: e.line))


def parse_ground_truth(data: bytes) -> Parsed:
    """Parse the answer key that says which registry entry each synthetic listing belongs to.

    A listing of type clean, noisy or wrong_or_expired must point at a registry entry. A
    no_counterpart or hard_negative listing must not, because no real entry exists for it.
    """
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
        # The pairing rule above, checked per row.
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
