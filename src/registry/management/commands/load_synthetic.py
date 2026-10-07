"""Load the M1 synthetic data sets into the database and check row counts against the CSVs."""

import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ingest.load import LoadError, load_synthetic_set

ACTOR = "system:load_synthetic"


def csv_data_rows(path: Path) -> int:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return sum(1 for row in csv.reader(f) if any(c.strip() for c in row)) - 1


class Command(BaseCommand):
    help = "Load data/synthetic/out/{dev,test} (registry, listings, ground truth). Synthetic only."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--set", choices=["dev", "test", "all"], default="all")
        parser.add_argument(
            "--dir",
            type=Path,
            default=settings.REPO_ROOT / "data" / "synthetic" / "out",
            help="Folder that holds the dev/ and test/ sub-folders.",
        )

    def handle(self, *args, **options) -> None:
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
            for key, want in expected.items():
                status = "OK" if loaded[key] == want else "MISMATCH"
                self.stdout.write(f"{name} {key}: loaded {loaded[key]}, CSV rows {want} {status}")
            if loaded != expected:
                raise CommandError(f"row counts differ for set '{name}'")
