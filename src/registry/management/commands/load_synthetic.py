"""Management command: load the synthetic dev and test data sets into the database.

Run it as `manage.py load_synthetic`. It loads the committed synthetic sets, then checks that the
number of rows in the database equals the number of data rows in each CSV file. The data is
synthetic only (AGENTS.md rule 3).
"""

import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ingest.load import LoadError, load_synthetic_set

# Name written into audit entries for loads run from this command, not from a person.
ACTOR = "system:load_synthetic"


def csv_data_rows(path: Path) -> int:
    """Count the data rows in a CSV file, not counting the header row.

    Blank lines (lines with only spaces or commas) are not counted. The file is read with a
    BOM-tolerant encoding, because some spreadsheet tools add a byte order mark.
    """
    with path.open(encoding="utf-8-sig", newline="") as f:
        return sum(1 for row in csv.reader(f) if any(c.strip() for c in row)) - 1


class Command(BaseCommand):
    """The `load_synthetic` management command. Accepts `--set dev|test|all`."""

    help = "Load data/synthetic/out/{dev,test} (registry, listings, ground truth). Synthetic only."

    def add_arguments(self, parser) -> None:
        """Declare the command's options: which set to load, and where the sets are."""
        parser.add_argument("--set", choices=["dev", "test", "all"], default="all")
        parser.add_argument(
            "--dir",
            type=Path,
            default=settings.REPO_ROOT / "data" / "synthetic" / "out",
            help="Folder that holds the dev/ and test/ sub-folders.",
        )

    def handle(self, *args, **options) -> None:
        """Load each chosen set, then compare the loaded row counts with the CSV row counts.

        A mismatch raises CommandError so the command exits with an error code.
        """
        names = ["dev", "test"] if options["set"] == "all" else [options["set"]]
        for name in names:
            folder = options["dir"] / name
            try:
                counts = load_synthetic_set(folder, dataset=f"synthetic-{name}", actor=ACTOR)
            except LoadError as exc:
                raise CommandError(str(exc)) from exc
            expected = {
                "registry": csv_data_rows(folder / "registry.csv"),
                "listings": csv_data_rows(folder / "listings.csv"),
                "ground_truth": csv_data_rows(folder / "ground_truth.csv"),
            }
            loaded = vars(counts)
            # Print one line per table so a person can see which count is wrong.
            for key, want in expected.items():
                status = "OK" if loaded[key] == want else "MISMATCH"
                self.stdout.write(f"{name} {key}: loaded {loaded[key]}, CSV rows {want} {status}")
            if loaded != expected:
                raise CommandError(f"row counts differ for set '{name}'")
