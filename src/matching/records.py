"""Plain input records for the matching engine. Pure Python, no Django.

What this file is for: it defines the two record types the engine works on, a registry
entry (an official licensed property) and a listing (a property advertised to tourists).
It also reads both from the synthetic CSV files.

Who calls it: ``matching.services`` builds the records from database rows, and the
evaluation harness and tests build them from the CSV readers below.

The engine only sees these records, never Django models, so it can be tested and evaluated
without a database. ``services.py`` builds them from the database; ``*_from_csv`` builds them
from the synthetic CSV files (used by tests and the M5 eval harness).

Ground truth is deliberately absent: there is no record type for it and no reader for
``ground_truth.csv`` here (D35).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path

# An id can be a database number or a text id from a CSV file.
RecordId = int | str


@dataclass(frozen=True)
class RegistryRecord:
    """One licensed property from the official registry."""

    id: RecordId
    licence_no: str
    name: str
    district: str
    locality: str
    valid_to: date  # the licence expires after this date
    address_en: str = ""
    address_ta: str = ""  # address in Tamil script, when given
    pincode: str = ""
    lat: float | None = None
    lng: float | None = None
    category: str = ""
    valid_from: date | None = None  # the licence starts on this date, when given
    status: str = "active"  # any value other than "active" makes the entry invalid


@dataclass(frozen=True)
class ListingRecord:
    """One property advertised to tourists. The licence it claims may be wrong or missing."""

    id: RecordId
    title: str
    locality_text: str  # the place as the listing writes it, free text
    district: str
    pincode: str = ""
    lat: float | None = None
    lng: float | None = None
    claimed_licence_no: str = ""  # the licence number the listing shows, if any


def _float(value: object) -> float | None:
    """Read a number from a CSV cell. An empty cell becomes ``None``."""
    if value is None or value == "":
        return None
    return float(value)  # type: ignore[arg-type]


def _date(value: str) -> date | None:
    """Read an ISO date (for example ``2026-04-01``) from a CSV cell. Empty gives ``None``."""
    return date.fromisoformat(value) if value else None


def _rows(path: Path | str) -> list[dict[str, str]]:
    """Read every row of a CSV file as a dict keyed by column name.

    ``utf-8-sig`` also skips a byte-order mark that Windows editors sometimes add.
    """
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def registry_records_from_csv(path: Path | str) -> list[RegistryRecord]:
    """Registry CSV (data-and-matching.md §1). ``id`` is the licence number."""
    out = []
    for r in _rows(path):
        valid_to = _date(r["valid_to"])
        # The expiry date decides validity, so a row without it cannot be used at all.
        if valid_to is None:
            raise ValueError(f"{path}: valid_to is required ({r['licence_no']})")
        out.append(
            RegistryRecord(
                id=r["licence_no"],
                licence_no=r["licence_no"],
                name=r["name"],
                district=r["district"],
                locality=r["locality"],
                valid_to=valid_to,
                # Optional columns use .get(), so an older file without them still loads.
                address_en=r.get("address_en", ""),
                address_ta=r.get("address_ta", ""),
                pincode=r.get("pincode", ""),
                lat=_float(r.get("lat")),
                lng=_float(r.get("lng")),
                category=r.get("category", ""),
                valid_from=_date(r.get("valid_from", "")),
                # An empty status cell means "active", the normal case.
                status=r.get("status", "") or "active",
            )
        )
    return out


def listing_records_from_csv(path: Path | str) -> list[ListingRecord]:
    """Listings CSV. ``id`` is the synthetic ``listing_id`` (D35) or the 1-based row number."""
    out = []
    # enumerate(..., start=1) numbers the rows from 1, used as a fallback id.
    for n, r in enumerate(_rows(path), start=1):
        out.append(
            ListingRecord(
                id=r.get("listing_id") or n,
                title=r["title"],
                locality_text=r["locality_text"],
                district=r.get("district", ""),
                pincode=r.get("pincode", ""),
                lat=_float(r.get("lat")),
                lng=_float(r.get("lng")),
                claimed_licence_no=r.get("claimed_licence_no", ""),
            )
        )
    return out
