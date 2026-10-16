"""Generic CSV reading and field checks, with errors that point at a line and a column.

This module knows nothing about the database. It turns raw bytes into a ``CsvTable`` (header
plus rows) and collects every problem it finds as a ``LineError``. Other modules then turn
the good rows into model objects.

Rules (docs/data-and-matching.md §1, §3; docs/security-and-privacy.md §5):
- UTF-8 only (a BOM is accepted). Values are stored as text; nothing is evaluated.
- At most MAX_BYTES bytes and MAX_ROWS data rows per file (D67).
- Missing required columns and unknown columns are errors on line 1.
- Cells that a spreadsheet program would run as a formula are errors (CSV injection, D67).
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

# [A] assumed limits. A district-level CSV is far smaller than the byte limit (dev listings are
# about 40 KB), and the largest synthetic file has 300 rows, so the row limit is generous.
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 5000

# Leading characters that make Excel/LibreOffice/Sheets treat a cell as a formula (OWASP
# "CSV injection"). "-" is allowed when the whole cell is a plain number (e.g. a longitude).
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@dataclass(frozen=True)
class LineError:
    """One problem found in a file: where it is (line and column) and what is wrong.

    Line 0 means the problem is about the whole file, not one row. An empty column name
    means the problem is about the whole row.
    """

    line: int
    column: str
    message: str

    def __str__(self) -> str:
        where = f"line {self.line}" + (f", column '{self.column}'" if self.column else "")
        return f"{where}: {self.message}"


@dataclass
class CsvTable:
    """A parsed CSV file: its header, its good rows, a fingerprint of the bytes, and errors.

    ``rows`` holds ``(line number, {column: value})`` pairs. The line number is kept so that
    later errors can still point at the right line in the user's file.
    """

    header: list[str]
    rows: list[tuple[int, dict[str, str]]]  # (line number, row)
    sha256: str  # fingerprint of the raw bytes; used to spot a file that was loaded before
    errors: list[LineError] = field(default_factory=list)


def looks_like_formula(value: str) -> bool:
    """True if a spreadsheet program could run `value` as a formula when the data is opened
    or exported later. Plain numbers such as "-12.5" are not formulas."""
    if not value or not value.startswith(FORMULA_PREFIXES):
        return False
    # A leading "+" or "-" is only a formula if the rest is not a plain number. Decimal()
    # accepts "-12.5" but rejects "-SUM(A1)", and it also accepts "NaN" and "Infinity",
    # which the is_finite() check rejects.
    if value[0] in "+-":
        try:
            return not Decimal(value).is_finite()
        except InvalidOperation:
            return True
    return True


def read_csv(data: bytes, required: list[str], optional: list[str]) -> CsvTable:
    """Decode and split a CSV file. Cell values are stripped of surrounding whitespace.

    The function stops early at each stage (size, encoding, header) because later checks
    would be meaningless on a file that failed an earlier one.
    """
    sha = hashlib.sha256(data).hexdigest()
    table = CsvTable(header=[], rows=[], sha256=sha)
    # Reject oversized files before decoding them, so a huge upload is never parsed.
    if len(data) > MAX_BYTES:
        table.errors.append(
            LineError(0, "", _("file is larger than %(max)d bytes") % {"max": MAX_BYTES})
        )
        return table
    try:
        # "utf-8-sig" decodes UTF-8 and quietly drops a byte-order mark (BOM) that Excel adds.
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        table.errors.append(
            LineError(0, "", _("file is not valid UTF-8 (%(reason)s)") % {"reason": exc.reason})
        )
        return table
    # newline="" lets the csv module handle line endings and quoted line breaks itself.
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
        # A bad header makes every row ambiguous, so stop before reading the rows.
        return table
    try:
        for cells in reader:
            # The line number where this record ends. A quoted cell can span several
            # physical lines, so this is not always the row count plus one.
            line = reader.line_num
            if not any(c.strip() for c in cells):
                continue  # blank line: ignored, not an error
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
            # Pair each header name with its cell. strict=True raises if the lengths differ,
            # which the check above has already ruled out.
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
    # A file with a header and nothing else is an error, so an upload cannot save zero rows
    # by accident. Line 2 is where the first data row would be.
    if not table.rows and not table.errors:
        table.errors.append(LineError(2, "", _("file has a header but no data rows")))
    return table


def _check_header(header: list[str], required: list[str], optional: list[str]) -> list[LineError]:
    """Check the header row: no duplicates, no unknown columns, and all required columns present.

    Every problem is reported on line 1, because the header is line 1 of the file.
    """
    errors = []
    seen: set[str] = set()
    for name in header:
        if name in seen:
            errors.append(LineError(1, name, _("duplicate column")))
        seen.add(name)
        if name not in required and name not in optional:
            errors.append(LineError(1, name, _("unknown column")))
    # Checked after the loop, against everything the header actually contains.
    for name in required:
        if name not in seen:
            errors.append(LineError(1, name, _("required column is missing")))
    return errors


class RowChecker:
    """Collects errors for one row while converting its fields.

    Each helper method reads one column, checks it, records any error against this row's line
    number, and returns the (cleaned) value. The caller then builds the model object from the
    returned values. A row with errors is never saved, because the whole file is rejected.
    """

    def __init__(self, line: int, row: dict[str, str], errors: list[LineError]) -> None:
        self.line = line
        self.row = row
        self.errors = errors  # shared list: every checker appends to the same error list

    def error(self, column: str, message: str) -> None:
        """Record one error against this row."""
        self.errors.append(LineError(self.line, column, message))

    def text(self, column: str, max_length: int, required: bool = False) -> str:
        """Return a text column, checking that it is not empty (if required) and not too long.

        A missing column reads as an empty string, so ``required`` catches it too.
        """
        value = self.row.get(column, "")
        if required and not value:
            self.error(column, _("required value is empty"))
        if len(value) > max_length:
            self.error(column, _("longer than %(max)d characters") % {"max": max_length})
        return value

    def choice(self, column: str, allowed: list[str], required: bool = False) -> str:
        """Return a column that must be one of ``allowed``. Empty is fine unless required."""
        value = self.row.get(column, "")
        if not value:
            if required:
                self.error(column, _("required value is empty"))
            return value
        if value not in allowed:
            self.error(column, _("must be one of: %(allowed)s") % {"allowed": ", ".join(allowed)})
        return value

    def pincode(self, column: str = "pincode") -> str:
        """Return a postcode column. It must be exactly 6 ASCII digits, or empty.

        ``isascii()`` is checked too, because ``isdigit()`` alone also accepts digits from
        other scripts (such as Tamil or Devanagari), which would not be valid pincodes.
        """
        value = self.row.get(column, "")
        if value and not (len(value) == 6 and value.isascii() and value.isdigit()):
            self.error(column, _("must be 6 digits or empty"))
        return value

    def date(self, column: str, required: bool = False) -> date | None:
        """Return a date in YYYY-MM-DD form, or None if the cell is empty or invalid."""
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
        """Return (lat, lng). Both must be given together, or both left empty."""
        lat = self._coordinate("lat", 90)  # latitude runs from -90 to 90
        lng = self._coordinate("lng", 180)  # longitude runs from -180 to 180
        # A row with only one of the two is an error. It is skipped when lat or lng already
        # has its own error, so the user does not see two messages for one mistake.
        if (lat is None) != (lng is None) and not self._had_error("lat", "lng"):
            self.error("lat", _("lat and lng must both be given or both be empty"))
            return None, None
        return lat, lng

    def _coordinate(self, column: str, limit: int) -> Decimal | None:
        """Parse one coordinate. It must be a finite decimal with absolute value <= limit.

        The result is rounded to six decimal places (about 0.1 m), which is more precision
        than the data needs.
        """
        value = self.row.get(column, "")
        if not value:
            return None
        try:
            number = Decimal(value)
        except InvalidOperation:
            self.error(column, _("must be a decimal number"))
            return None
        # is_finite() rejects NaN and infinity, which Decimal() would otherwise accept.
        if not number.is_finite() or abs(number) > limit:
            self.error(column, _("must be between -%(limit)d and %(limit)d") % {"limit": limit})
            return None
        return number.quantize(Decimal("0.000001"))

    def _had_error(self, *columns: str) -> bool:
        """True if this row already has an error in one of the named columns."""
        return any(e.line == self.line and e.column in columns for e in self.errors)
