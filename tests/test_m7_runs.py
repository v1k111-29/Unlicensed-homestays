"""M7 run endpoints: a run produces results and an audit entry; district scoping; permission
matrix. All synthetic; uses the DEV set only (never the test set, AGENTS.md rule 9)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from audit.models import AuditLog
from ingest.load import load_listings, load_synthetic_set
from listings.models import Listing
from matching import engine
from matching.models import MatchResult, MatchRun
from registry.models import UploadBatch

pytestmark = pytest.mark.django_db

DEV = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "out" / "dev"
RUNS = "/officer/runs/"
START = "/officer/runs/start/"


def _client(user) -> Client:
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def dev_set(db) -> None:
    load_synthetic_set(DEV, "synthetic-dev", "system:test")


def _officer_batch(client: Client, dataset: str = "synthetic-dev") -> UploadBatch:
    """Upload dev/demo_listings.csv (25 Nilgiris listings) through the web flow."""
    data = (DEV / "demo_listings.csv").read_bytes()
    preview = client.post(
        "/officer/uploads/",
        {"file": SimpleUploadedFile("demo.csv", data, "text/csv"), "dataset": dataset},
    )
    assert preview.status_code == 200, preview.content.decode()[:500]
    token = re.search(r'name="token" value="([^"]+)"', preview.content.decode()).group(1)
    client.post("/officer/uploads/confirm/", {"token": token})
    return UploadBatch.objects.get(source_name="demo.csv")


def test_officer_run_produces_results_and_audit(users, districts, dev_set) -> None:
    client = _client(users["off_nil"])
    batch = _officer_batch(client)

    response = client.post(START, {"batch": batch.pk})
    run = MatchRun.objects.get(listing_batch=batch)
    assert response.status_code == 302 and response["Location"] == f"/officer/runs/{run.pk}/"
    assert run.district == districts["nil"] and run.created_by == users["off_nil"]
    assert run.registry_batch.dataset == "synthetic-dev"
    results = MatchResult.objects.filter(run=run)
    assert results.count() == 25 == Listing.objects.filter(batch=batch).count()
    assert all(r.band in engine.BANDS for r in results)

    entry = AuditLog.objects.get(action="match_run.create", entity_id=str(run.pk))
    assert entry.actor == "officer_nil" and entry.meta["listings"] == 25
    assert entry.meta["district"] == "Nilgiris"

    page = client.get(response["Location"])
    assert page.status_code == 200
    body = page.content.decode()
    assert "not findings" in body
    for band in MatchResult.Band:
        assert str(band.label) in body
    counts = {b: results.filter(band=b).count() for b in engine.BANDS}
    for band, n in counts.items():
        assert n == page.context["bands"][engine.BANDS.index(band)]["count"]
    assert page.context["total"] == 25


def test_runs_page_lists_only_own_district(users, dev_set) -> None:
    nil = _client(users["off_nil"])
    batch = _officer_batch(nil)
    nil.post(START, {"batch": batch.pk})
    run = MatchRun.objects.get()

    mad_page = _client(users["off_mad"]).get(RUNS)
    assert mad_page.status_code == 200
    assert list(mad_page.context["batches"]) == [] and list(mad_page.context["runs"]) == []
    assert "No listing batches yet." in mad_page.content.decode()

    nil_page = nil.get(RUNS)
    assert [b.pk for b in nil_page.context["batches"]] == [batch.pk]
    assert [r.pk for r in nil_page.context["runs"]] == [run.pk]


def test_officer_cannot_run_or_view_another_district(users, dev_set) -> None:
    nil = _client(users["off_nil"])
    batch = _officer_batch(nil)
    nil.post(START, {"batch": batch.pk})
    run = MatchRun.objects.get()

    mad = _client(users["off_mad"])
    assert mad.post(START, {"batch": batch.pk}).status_code == 404
    assert mad.get(f"/officer/runs/{run.pk}/").status_code == 404
    assert MatchRun.objects.count() == 1
    denials = AuditLog.objects.filter(
        action="permission_denied", actor="officer_mad", meta__reason="out_of_district"
    )
    assert denials.count() == 2


def test_officer_cannot_run_admin_multi_district_batch(users, dev_set) -> None:
    batch = UploadBatch.objects.get(type="listings", dataset="synthetic-dev")
    assert batch.district is None
    response = _client(users["off_nil"]).post(START, {"batch": batch.pk})
    assert response.status_code == 404  # not in the officer's scope (D64)
    assert not MatchRun.objects.exists()


def test_admin_run_on_multi_district_batch_makes_one_run_per_district(users) -> None:
    data = (
        b"listing_id,platform,title,locality_text,pincode,district\n"
        b"A-1,synthetic,Synthetic Stay A,Ooty,643001,Nilgiris\n"
        b"A-2,synthetic,Synthetic Stay B,Madurai town,625001,Madurai\n"
    )
    registry = (
        b"licence_no,name,locality,district,valid_to\n"
        b"SYN-NLG-90001-A,Synthetic Stay A,Ooty,Nilgiris,2030-01-01\n"
        b"SYN-MDU-90002-B,Synthetic Lodge,Madurai town,Madurai,2030-01-01\n"
    )
    from ingest.load import load_registry

    load_registry(registry, "reg.csv", "", "system:test")
    batch = load_listings(data, "multi.csv", "", "system:test")
    response = _client(users["admin"]).post(START, {"batch": batch.pk}, follow=True)
    assert response.status_code == 200
    runs = MatchRun.objects.filter(listing_batch=batch)
    assert sorted(r.district.name_en for r in runs) == ["Madurai", "Nilgiris"]
    assert all(MatchResult.objects.filter(run=r).count() == 1 for r in runs)
    assert "one per district" in response.content.decode()


def test_run_without_registry_shows_error_and_saves_nothing(users) -> None:
    client = _client(users["off_nil"])
    batch = _officer_batch(client, dataset="")
    response = client.post(START, {"batch": batch.pk}, follow=True)
    assert response.status_code == 200
    assert "Matching could not start" in response.content.decode()
    assert not MatchRun.objects.exists()
    assert not AuditLog.objects.filter(action="match_run.create").exists()


def test_reserved_test_set_batch_is_not_runnable(users) -> None:
    from ingest.load import load_synthetic_set as load

    load(DEV.parent / "test", "synthetic-test", "system:test")
    batch = UploadBatch.objects.get(type="listings", dataset="synthetic-test")
    client = _client(users["admin"])
    assert batch.pk not in [b.pk for b in client.get(RUNS).context["batches"]]
    assert client.post(START, {"batch": batch.pk}).status_code == 404
    assert not MatchRun.objects.exists()


@pytest.mark.parametrize("value", ["", "abc", "999999"])
def test_bad_batch_ids_give_404(users, value: str) -> None:
    assert _client(users["off_nil"]).post(START, {"batch": value}).status_code == 404


def test_start_is_post_only(users) -> None:
    assert _client(users["off_nil"]).get(START).status_code == 405


@pytest.mark.parametrize(
    ("role", "url", "method", "expected"),
    [
        ("off_nil", RUNS, "get", 200),
        ("off_mad", RUNS, "get", 200),
        ("admin", RUNS, "get", 200),
        ("inactive", RUNS, "get", 302),
        ("inactive", START, "post", 302),
    ],
)
def test_run_permission_matrix(users, role: str, url: str, method: str, expected: int) -> None:
    response = getattr(_client(users[role]), method)(url, {"batch": "1"})
    assert response.status_code == expected


@pytest.mark.parametrize(
    ("url", "method"), [(RUNS, "get"), (START, "post"), ("/officer/runs/1/", "get")]
)
def test_anonymous_cannot_run(url: str, method: str, db) -> None:
    response = getattr(Client(), method)(url, {"batch": "1"})
    assert response.status_code == 302 and "/login/" in response["Location"]
    assert not MatchRun.objects.exists()
