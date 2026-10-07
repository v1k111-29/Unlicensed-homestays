"""Generic CSV reading and field checks with line-level errors. No database access.

Rules (docs/data-and-matching.md §1, §3; docs/security-and-privacy.md §5):
- UTF-8 only (a BOM is accepted). Values are stored as text; nothing is evaluated.
- At most MAX_BYTES bytes and MAX_ROWS data rows per file (D56).
- Missing required columns and unknown columns are errors on line 1.
- Cells that a spreadsheet program would run as a formula are errors (CSV injection, D56).
- All-or-nothing: callers must not save anything if any error is returned.

Messages use gettext, so an upload page shows them in the user's language (O2).
"""

import csv
import hashlib
import io
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation

from django.utils.translation import gettext as _

MAX_BYTES = 2 * 1024 * 1024  # [A] a district-level CSV is far smaller (dev listings: ~40 KB)
MAX_ROWS = 5000  # [A] data rows per file; the largest synthetic file has 300

# Leading characters that make Excel/LibreOffice/Sheets treat a cell as a formula (OWASP
# "CSV injection"). "-" is allowed when the whole cell is a plain number (e.g. a longitude).
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


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


def looks_like_formula(value: str) -> bool:
    """True if a spreadsheet program could run `value` as a formula when the data is opened
    or exported later. Plain numbers such as "-12.5" are not formulas."""
    if not value or not value.startswith(FORMULA_PREFIXES):
        return False
    if value[0] in "+-":
        try:
            return not Decimal(value).is_finite()
        except InvalidOperation:
            return True
    return True


def read_csv(data: bytes, required: list[str], optional: list[str]) -> CsvTable:
    """Decode and split a CSV file. Cell values are stripped of surrounding whitespace."""
    sha = hashlib.sha256(data).hexdigest()
    table = CsvTable(header=[], rows=[], sha256=sha)
    if len(data) > MAX_BYTES:
        table.errors.append(
            LineError(0, "", _("file is larger than %(max)d bytes") % {"max": MAX_BYTES})
        )
        return table
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        table.errors.append(
            LineError(0, "", _("file is not valid UTF-8 (%(reason)s)") % {"reason": exc.reason})
        )
        return table
    reader = csv.reader(io.StringIO(text, newline=""))
    try:
        header = next(reader)
    except StopIteration:
        table.errors.append(LineError(1, "", _("file is empty")))
        return table
    except csv.Error as exc:
        table.errors.append(LineError(1, "", _("cannot read header: %(error)s") % {"error": exc}))
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
                    LineError(
                        line,
                        "",
                        _("expected %(expected)d cells, got %(got)d")
                        % {"expected": len(table.header), "got": len(cells)},
                    )
                )
                continue
            if len(table.rows) >= MAX_ROWS:
                table.errors.append(
                    LineError(
                        line, "", _("file has more than %(max)d data rows") % {"max": MAX_ROWS}
                    )
                )
                break
            row = {h: c.strip() for h, c in zip(table.header, cells, strict=True)}
            for column, value in row.items():
                if looks_like_formula(value):
                    table.errors.append(
                        LineError(
                            line,
                            column,
                            _(
                                "starts with '%(char)s', which spreadsheet programs may run as "
                                "a formula; remove or reword the start of the value"
                            )
                            % {"char": value[0].replace("\t", "\\t").replace("\r", "\\r")},
                        )
                    )
            table.rows.append((line, row))
    except csv.Error as exc:
        table.errors.append(
            LineError(reader.line_num, "", _("malformed CSV: %(error)s") % {"error": exc})
        )
    if not table.rows and not table.errors:
        table.errors.append(LineError(2, "", _("file has a header but no data rows")))
    return table


def _check_header(header: list[str], required: list[str], optional: list[str]) -> list[LineError]:
    errors = []
    seen: set[str] = set()
    for name in header:
        if name in seen:
            errors.append(LineError(1, name, _("duplicate column")))
        seen.add(name)
        if name not in required and name not in optional:
            errors.append(LineError(1, name, _("unknown column")))
    for name in required:
        if name not in seen:
            errors.append(LineError(1, name, _("required column is missing")))
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
            self.error(column, _("required value is empty"))
        if len(value) > max_length:
            self.error(column, _("longer than %(max)d characters") % {"max": max_length})
        return value

    def choice(self, column: str, allowed: list[str], required: bool = False) -> str:
        value = self.row.get(column, "")
        if not value:
            if required:
                self.error(column, _("required value is empty"))
            return value
        if value not in allowed:
            self.error(column, _("must be one of: %(allowed)s") % {"allowed": ", ".join(allowed)})
        return value

    def pincode(self, column: str = "pincode") -> str:
        value = self.row.get(column, "")
        if value and not (len(value) == 6 and value.isascii() and value.isdigit()):
            self.error(column, _("must be 6 digits or empty"))
        return value

    def date(self, column: str, required: bool = False) -> date | None:
        value = self.row.get(column, "")
        if not value:
            if required:
                self.error(column, _("required value is empty"))
            return None
        try:
            return date.fromisoformat(value)
        except ValueError:
            self.error(column, _("must be a date in YYYY-MM-DD format"))
            return None

    def coords(self) -> tuple[Decimal | None, Decimal | None]:
        lat = self._coordinate("lat", 90)
        lng = self._coordinate("lng", 180)
        if (lat is None) != (lng is None) and not self._had_error("lat", "lng"):
            self.error("lat", _("lat and lng must both be given or both be empty"))
            return None, None
        return lat, lng

    def _coordinate(self, column: str, limit: int) -> Decimal | None:
        value = self.row.get(column, "")
        if not value:
            return None
        try:
            number = Decimal(value)
        except InvalidOperation:
            self.error(column, _("must be a decimal number"))
            return None
        if not number.is_finite() or abs(number) > limit:
            self.error(column, _("must be between -%(limit)d and %(limit)d") % {"limit": limit})
            return None
        return number.quantize(Decimal("0.000001"))

    def _had_error(self, *columns: str) -> bool:
        return any(e.line == self.line and e.column in columns for e in self.errors)
