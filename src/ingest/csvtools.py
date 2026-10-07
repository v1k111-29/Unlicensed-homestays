"""Generic CSV reading and field checks with line-level errors. No database access.

Rules (docs/data-and-matching.md §1, §3; docs/security-and-privacy.md §5):
- UTF-8 only (a BOM is accepted). Values are stored as text; nothing is evaluated.
- Missing required columns and unknown columns are errors on line 1.
- All-or-nothing: callers must not save anything if any error is returned.
"""

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

MAX_BYTES = 5 * 1024 * 1024  # [A] generous for a district-level CSV; revisit in M7


@dataclass(frozen=True)
class LineError:
    line: int
    column: str
    message: str

    def __str__(self) -> str:
        where = f"line {self.line}" + (f", column '{self.column}'" if self.column else "")
        return f"{where}: {self.message}"


@dataclass
class CsvTable:
    header: list[str]
    rows: list[tuple[int, dict[str, str]]]  # (line number, row)
    sha256: str
    errors: list[LineError] = field(default_factory=list)


def read_csv(data: bytes, required: list[str], optional: list[str]) -> CsvTable:
    """Decode and split a CSV file. Cell values are stripped of surrounding whitespace."""
    sha = hashlib.sha256(data).hexdigest()
    table = CsvTable(header=[], rows=[], sha256=sha)
    if len(data) > MAX_BYTES:
        table.errors.append(LineError(0, "", f"file is larger than {MAX_BYTES} bytes"))
        return table
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        table.errors.append(LineError(0, "", f"file is not valid UTF-8 ({exc.reason})"))
        return table
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        table.errors.append(LineError(1, "", "file is empty"))
        return table
    except csv.Error as exc:
        table.errors.append(LineError(1, "", f"cannot read header: {exc}"))
        return table
    table.header = [h.strip() for h in header]
    table.errors.extend(_check_header(table.header, required, optional))
    if table.errors:
        return table
    try:
        for cells in reader:
            line = reader.line_num
            if not any(c.strip() for c in cells):
                continue  # blank line
            if len(cells) != len(table.header):
                table.errors.append(
                    LineError(line, "", f"expected {len(table.header)} cells, got {len(cells)}")
                )
                continue
            table.rows.append(
                (line, {h: c.strip() for h, c in zip(table.header, cells, strict=True)})
            )
    except csv.Error as exc:
        table.errors.append(LineError(reader.line_num, "", f"malformed CSV: {exc}"))
    if not table.rows and not table.errors:
        table.errors.append(LineError(2, "", "file has a header but no data rows"))
    return table


def _check_header(header: list[str], required: list[str], optional: list[str]) -> list[LineError]:
    errors = []
    seen: set[str] = set()
    for name in header:
        if name in seen:
            errors.append(LineError(1, name, "duplicate column"))
        seen.add(name)
        if name not in required and name not in optional:
            errors.append(LineError(1, name, "unknown column"))
    for name in required:
        if name not in seen:
            errors.append(LineError(1, name, "required column is missing"))
    return errors


class RowChecker:
    """Collects errors for one row while converting its fields."""

    def __init__(self, line: int, row: dict[str, str], errors: list[LineError]) -> None:
        self.line = line
        self.row = row
        self.errors = errors

    def error(self, column: str, message: str) -> None:
        self.errors.append(LineError(self.line, column, message))

    def text(self, column: str, max_length: int, required: bool = False) -> str:
        value = self.row.get(column, "")
        if required and not value:
            self.error(column, "required value is empty")
        if len(value) > max_length:
            self.error(column, f"longer than {max_length} characters")
        return value

    def choice(self, column: str, allowed: list[str], required: bool = False) -> str:
        value = self.row.get(column, "")
        if not value:
            if required:
                self.error(column, "required value is empty")
            return value
        if value not in allowed:
            self.error(column, f"must be one of: {', '.join(allowed)}")
        return value

    def pincode(self, column: str = "pincode") -> str:
        value = self.row.get(column, "")
        if value and not (len(value) == 6 and value.isascii() and value.isdigit()):
            self.error(column, "must be 6 digits or empty")
        return value

    def date(self, column: str, required: bool = False) -> date | None:
        value = self.row.get(column, "")
        if not value:
            if required:
                self.error(column, "required value is empty")
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            self.error(column, "must be a date in YYYY-MM-DD format")
            return None

    def coords(self) -> tuple[Decimal | None, Decimal | None]:
        lat = self._coordinate("lat", 90)
        lng = self._coordinate("lng", 180)
        if (lat is None) != (lng is None) and not self._had_error("lat", "lng"):
            self.error("lat", "lat and lng must both be given or both be empty")
            return None, None
        return lat, lng

    def _coordinate(self, column: str, limit: int) -> Decimal | None:
        value = self.row.get(column, "")
        if not value:
            return None
        try:
            number = Decimal(value)
        except InvalidOperation:
            self.error(column, "must be a decimal number")
            return None
        if not number.is_finite() or abs(number) > limit:
            self.error(column, f"must be between -{limit} and {limit}")
            return None
        return number.quantize(Decimal("0.000001"))

    def _had_error(self, *columns: str) -> bool:
        return any(e.line == self.line and e.column in columns for e in self.errors)
