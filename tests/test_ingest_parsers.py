"""CSV parsing and validation (M2). Pure functions: no database needed."""

import csv
from pathlib import Path

import pytest

from ingest import csvtools, parsers
from ingest.csvtools import MAX_BYTES
from matching.models import GroundTruth
from registry.models import RegistryEntry

OUT = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "out"
SETS = ["dev", "test"]

REG_HEADER = (
    "licence_no,name,address_en,address_ta,locality,pincode,lat,lng,category,"
    "valid_from,valid_to,status,district"
)
REG_ROW = (
    "SYN-NLG-00001-A,Test Stay,1 Road,,Ooty,643001,11.4,76.7,cottage,"
    "2024-01-01,2027-01-01,active,Nilgiris"
)
LST_HEADER = (
    "listing_id,platform,ref_url,title,locality_text,pincode,lat,lng,"
    "claimed_licence_no,notes,district"
)
LST_ROW = "X-1,platform_a,https://platform-a.example/x,Test Stay,Ooty,643001,11.4,76.7,,,Nilgiris"


def _data_rows(path: Path) -> int:
    with path.open(encoding="utf-8", newline="") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def _csv(*lines: str) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def _messages(parsed: parsers.Parsed) -> list[str]:
    return [str(e) for e in parsed.errors]


@pytest.mark.parametrize("name", SETS)
def test_committed_registry_parses_cleanly(name: str) -> None:
    path = OUT / name / "registry.csv"
    parsed = parsers.parse_registry(path.read_bytes())
    assert parsed.ok, _messages(parsed)[:5]
    assert len(parsed.rows) == _data_rows(path)


@pytest.mark.parametrize("name", SETS)
def test_committed_listings_parse_cleanly(name: str) -> None:
    path = OUT / name / "listings.csv"
    parsed = parsers.parse_listings(path.read_bytes(), require_district=True)
    assert parsed.ok, _messages(parsed)[:5]
    assert len(parsed.rows) == _data_rows(path)
    assert all(r.external_id and r.raw["listing_id"] == r.external_id for r in parsed.rows)


@pytest.mark.parametrize("name", SETS)
def test_committed_ground_truth_parses_cleanly(name: str) -> None:
    path = OUT / name / "ground_truth.csv"
    parsed = parsers.parse_ground_truth(path.read_bytes())
    assert parsed.ok, _messages(parsed)[:5]
    assert len(parsed.rows) == _data_rows(path)


def test_choice_lists_match_models() -> None:
    assert parsers.REGISTRY_CATEGORIES == RegistryEntry.Category.values
    assert parsers.REGISTRY_STATUSES == RegistryEntry.Status.values
    assert parsers.GROUND_TRUTH_TYPES == GroundTruth.Type.values


def test_valid_minimal_registry() -> None:
    parsed = parsers.parse_registry(_csv(REG_HEADER, REG_ROW))
    assert parsed.ok
    row = parsed.rows[0]
    assert row.licence_no == "SYN-NLG-00001-A" and str(row.lat) == "11.400000"
    assert len(parsed.sha256) == 64


def test_missing_and_unknown_columns_reported_on_line_1() -> None:
    parsed = parsers.parse_registry(_csv("licence_no,name,owner_phone", "A,B,123"))
    msgs = _messages(parsed)
    assert any("'owner_phone'" in m and "unknown column" in m for m in msgs)
    for col in ("locality", "district", "valid_to"):
        assert any(f"'{col}'" in m and "missing" in m for m in msgs)
    assert all(e.line == 1 for e in parsed.errors)
    assert parsed.rows == []


@pytest.mark.parametrize(
    ("column_index", "value", "fragment"),
    [
        (0, "", "required value is empty"),
        (5, "6430", "6 digits"),
        (6, "north", "decimal number"),
        (6, "95", "between -90 and 90"),
        (8, "villa", "must be one of"),
        (10, "01/01/2027", "YYYY-MM-DD"),
        (11, "closed", "must be one of"),
    ],
)
def test_bad_registry_values_give_line_errors(column_index: int, value: str, fragment: str) -> None:
    cells = REG_ROW.split(",")
    cells[0] = "SYN-NLG-00002-B"  # distinct licence, so only the tested error appears
    cells[column_index] = value
    parsed = parsers.parse_registry(_csv(REG_HEADER, REG_ROW, ",".join(cells)))
    assert not parsed.ok
    assert [e.line for e in parsed.errors] == [3]
    assert fragment in str(parsed.errors[0])


def test_valid_from_after_valid_to() -> None:
    cells = REG_ROW.split(",")
    cells[9] = "2028-01-01"
    parsed = parsers.parse_registry(_csv(REG_HEADER, ",".join(cells)))
    assert "after valid_to" in _messages(parsed)[0]


def test_lat_without_lng_rejected() -> None:
    cells = REG_ROW.split(",")
    cells[7] = ""
    parsed = parsers.parse_registry(_csv(REG_HEADER, ",".join(cells)))
    assert "both" in _messages(parsed)[0]


def test_duplicate_licence_rejected() -> None:
    parsed = parsers.parse_registry(_csv(REG_HEADER, REG_ROW, REG_ROW))
    assert _messages(parsed) == ["line 3, column 'licence_no': duplicate of line 2"]


def test_wrong_cell_count() -> None:
    parsed = parsers.parse_registry(_csv(REG_HEADER, "a,b,c"))
    assert "expected 13 cells" in _messages(parsed)[0]


def test_non_utf8_rejected() -> None:
    parsed = parsers.parse_registry(REG_HEADER.encode() + b"\n\xff\xfe\n")
    assert "UTF-8" in _messages(parsed)[0]


def test_bom_accepted_and_blank_lines_skipped() -> None:
    parsed = parsers.parse_registry(b"\xef\xbb\xbf" + _csv(REG_HEADER, "", REG_ROW, ""))
    assert parsed.ok and len(parsed.rows) == 1


def test_empty_and_header_only_files_rejected() -> None:
    assert "empty" in _messages(parsers.parse_registry(b""))[0]
    assert "no data rows" in _messages(parsers.parse_registry(_csv(REG_HEADER)))[0]


def test_oversized_file_rejected() -> None:
    parsed = parsers.parse_registry(b"x" * (MAX_BYTES + 1))
    assert "larger than" in _messages(parsed)[0]


@pytest.mark.parametrize(
    "value", ["=HYPERLINK(1)", "+cmd|' /C calc'!A0", "-2+3", "@SUM(A1)", "-", "=1"]
)
def test_formula_like_cells_are_rejected(value: str) -> None:
    """CSV injection (D67, M7 replaces M2's "stored as text"): the file is refused with a
    line-level error, so such values never reach the database or a later export."""
    cells = REG_ROW.split(",")
    cells[1] = value
    parsed = parsers.parse_registry(_csv(REG_HEADER, ",".join(cells)))
    assert not parsed.ok
    assert [(e.line, e.column) for e in parsed.errors] == [(2, "name")]
    assert "formula" in parsed.errors[0].message


def test_quoted_tab_prefixed_cell_is_rejected() -> None:
    cells = REG_ROW.split(",")
    cells[1] = '"\t=1"'  # surrounding whitespace is stripped, so the "=" is caught
    parsed = parsers.parse_registry(_csv(REG_HEADER, ",".join(cells)))
    assert [(e.line, e.column) for e in parsed.errors] == [(2, "name")]


def test_negative_numbers_are_not_formulas() -> None:
    cells = REG_ROW.split(",")
    cells[6], cells[7] = "-11.4", "+76.7"
    parsed = parsers.parse_registry(_csv(REG_HEADER, ",".join(cells)))
    assert parsed.ok, _messages(parsed)


def test_too_many_rows_rejected(monkeypatch) -> None:
    monkeypatch.setattr(csvtools, "MAX_ROWS", 3)
    rows = [REG_ROW.replace("00001", f"0000{i}") for i in range(1, 6)]
    parsed = parsers.parse_registry(_csv(REG_HEADER, *rows))
    assert not parsed.ok
    assert any("more than 3 data rows" in m for m in _messages(parsed))


def test_listing_district_required_only_when_asked() -> None:
    no_district = LST_ROW.rsplit(",", 1)[0] + ","
    assert parsers.parse_listings(_csv(LST_HEADER, no_district), require_district=False).ok
    parsed = parsers.parse_listings(_csv(LST_HEADER, no_district), require_district=True)
    assert "'district': required" in _messages(parsed)[0]


def test_listing_without_optional_columns() -> None:
    parsed = parsers.parse_listings(
        _csv("platform,title,locality_text", "direct,Some Stay,Ooty"), require_district=False
    )
    assert parsed.ok and parsed.rows[0].external_id == "" and parsed.rows[0].lat is None


def test_duplicate_listing_id_rejected() -> None:
    parsed = parsers.parse_listings(_csv(LST_HEADER, LST_ROW, LST_ROW), require_district=True)
    assert "duplicate of line 2" in _messages(parsed)[0]


@pytest.mark.parametrize(
    ("row", "fragment"),
    [
        ("L1,,clean,", "required for type 'clean'"),
        ("L1,SYN-NLG-00001-A,no_counterpart,", "must be empty"),
        ("L1,,unknown_type,", "must be one of"),
    ],
)
def test_ground_truth_consistency(row: str, fragment: str) -> None:
    parsed = parsers.parse_ground_truth(_csv("listing_id,true_registry_id,type,noise", row))
    assert fragment in _messages(parsed)[0]
