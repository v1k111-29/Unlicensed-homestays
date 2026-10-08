"""Loading the M1 synthetic sets into PostgreSQL (M2 done-criterion: row counts match CSVs).

All tests here need a database; they are skipped when DATABASE_URL is unset or unreachable.
"""

import csv
import shutil
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction

from accounts.models import District, User
from audit.models import AuditLog
from ingest.load import LoadError, load_registry, load_synthetic_set
from listings.models import Listing
from matching.models import GroundTruth
from registry.models import RegistryEntry, UploadBatch
from reviews.models import Review

OUT = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "out"

pytestmark = pytest.mark.django_db


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_districts_seeded_by_migration() -> None:
    assert District.objects.count() == 8
    assert District.objects.filter(name_en="Nilgiris").exists()


def test_load_command_row_counts_match_csvs() -> None:
    out = StringIO()
    call_command("load_synthetic", "--set", "all", stdout=out)
    assert "MISMATCH" not in out.getvalue()
    for name in ("dev", "test"):
        dataset = f"synthetic-{name}"
        registry = _rows(OUT / name / "registry.csv")
        listings = _rows(OUT / name / "listings.csv")
        truth = _rows(OUT / name / "ground_truth.csv")
        assert RegistryEntry.objects.filter(batch__dataset=dataset).count() == len(registry)
        assert Listing.objects.filter(batch__dataset=dataset).count() == len(listings)
        assert GroundTruth.objects.filter(listing__batch__dataset=dataset).count() == len(truth)
        with_entry = sum(1 for r in truth if r["true_registry_id"])
        assert (
            GroundTruth.objects.filter(
                listing__batch__dataset=dataset, true_registry_entry__isnull=False
            ).count()
            == with_entry
        )
        # Per-district counts match too (district scoping depends on this column).
        for district in {r["district"] for r in registry}:
            want = sum(1 for r in registry if r["district"] == district)
            got = RegistryEntry.objects.filter(
                batch__dataset=dataset, district__name_en=district
            ).count()
            assert got == want


def test_loaded_values_round_trip() -> None:
    load_synthetic_set(OUT / "dev", "synthetic-dev", "system:test")
    first = _rows(OUT / "dev" / "listings.csv")[0]
    listing = Listing.objects.get(batch__dataset="synthetic-dev", external_id=first["listing_id"])
    assert listing.title == first["title"]
    assert listing.raw == first
    assert listing.district.name_en == first["district"]
    reg = _rows(OUT / "dev" / "registry.csv")[0]
    entry = RegistryEntry.objects.get(batch__dataset="synthetic-dev", licence_no=reg["licence_no"])
    assert entry.address_ta == reg["address_ta"]
    assert entry.valid_to.isoformat() == reg["valid_to"]


def test_load_writes_audit_entries() -> None:
    load_synthetic_set(OUT / "dev", "synthetic-dev", "system:test")
    actions = list(AuditLog.objects.order_by("id").values_list("action", flat=True))
    assert actions == ["registry_upload", "listings_upload", "ground_truth_load"]
    upload = AuditLog.objects.get(action="registry_upload")
    batch = UploadBatch.objects.get(type="registry", dataset="synthetic-dev")
    assert upload.entity_id == str(batch.pk)
    assert upload.meta["sha256"] == batch.file_sha256
    assert upload.actor == "system:test"


def test_second_load_of_same_set_refused() -> None:
    load_synthetic_set(OUT / "dev", "synthetic-dev", "system:test")
    with pytest.raises(LoadError, match="already loaded"):
        load_synthetic_set(OUT / "dev", "synthetic-dev", "system:test")
    assert RegistryEntry.objects.count() == len(_rows(OUT / "dev" / "registry.csv"))


def test_command_fails_cleanly_when_already_loaded() -> None:
    call_command("load_synthetic", "--set", "dev", stdout=StringIO())
    with pytest.raises(CommandError, match="already loaded"):
        call_command("load_synthetic", "--set", "dev", stdout=StringIO())


def test_bad_ground_truth_saves_nothing_from_the_set(tmp_path: Path) -> None:
    folder = tmp_path / "dev"
    shutil.copytree(OUT / "dev", folder)
    gt = folder / "ground_truth.csv"
    gt.write_text(
        gt.read_text(encoding="utf-8") + "NOT-A-LISTING,,no_counterpart,\n", encoding="utf-8"
    )
    with pytest.raises(LoadError, match="not in the listings batch"):
        load_synthetic_set(folder, "synthetic-dev", "system:test")
    assert RegistryEntry.objects.count() == 0
    assert Listing.objects.count() == 0
    assert UploadBatch.objects.count() == 0
    assert AuditLog.objects.count() == 0


def test_unknown_district_rejected_and_nothing_saved() -> None:
    data = (
        b"licence_no,name,locality,district,valid_to\n"
        b"SYN-X-1,Stay One,Ooty,Nilgiris,2027-01-01\n"
        b"SYN-X-2,Stay Two,Somewhere,Atlantis,2027-01-01\n"
    )
    with pytest.raises(LoadError) as exc:
        load_registry(data, "bad.csv", "t", "system:test")
    assert [str(e) for e in exc.value.errors] == [
        "line 3, column 'district': unknown district 'Atlantis'"
    ]
    assert RegistryEntry.objects.count() == 0 and UploadBatch.objects.count() == 0


def test_invalid_file_saves_nothing() -> None:
    with pytest.raises(LoadError):
        load_registry(b"licence_no,name\nA,B\n", "bad.csv", "t", "system:test")
    assert UploadBatch.objects.count() == 0 and AuditLog.objects.count() == 0


def test_officer_must_have_district() -> None:
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.create(username="officer1", role=User.Role.OFFICER, district=None)
    User.objects.create(username="admin1", role=User.Role.ADMIN, district=None)


def test_suspected_unlicensed_requires_reason() -> None:
    load_synthetic_set(OUT / "dev", "synthetic-dev", "system:test")
    listing = Listing.objects.first()
    officer = User.objects.create(
        username="officer1", role=User.Role.OFFICER, district=listing.district
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Review.objects.create(
            listing=listing,
            reviewer=officer,
            decision=Review.Decision.SUSPECTED_UNLICENSED,
            reason="",
        )
    Review.objects.create(
        listing=listing,
        reviewer=officer,
        decision=Review.Decision.SUSPECTED_UNLICENSED,
        reason="Synthetic test reason.",
    )
