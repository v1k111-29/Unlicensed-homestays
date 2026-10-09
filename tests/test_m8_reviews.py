"""M8: review queue, case detail, decisions, evidence page, dashboard counts.

Covers: queue scoping per district, filters, order and pagination; the decision permission
matrix; `suspected_unlicensed` needs a reason and an officer; every decision is audited;
optimistic concurrency; confirmed pairs suppressed on a later real run; evidence page content
and hash; other-district objects give 404 plus an audit row. All data synthetic; the dev set
only (never the test set, AGENTS.md rule 9). No `transactional_db` (audit trigger, D65).
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client

from audit.models import AuditLog
from ingest.load import load_synthetic_set
from listings.models import Listing
from matching import engine
from matching.models import MatchCandidate, MatchResult, MatchRun
from registry.models import RegistryEntry, UploadBatch
from reviews import services
from reviews.models import ConfirmedPair, EvidencePack, Review

pytestmark = pytest.mark.django_db

DEV = Path(__file__).resolve().parents[1] / "data" / "synthetic" / "out" / "dev"
QUEUE = "/officer/queue/"
SUSPECTED = "suspected_unlicensed"


def _client(user, **kwargs) -> Client:
    client = Client(**kwargs)
    client.force_login(user)
    return client


def _case(pk: int) -> str:
    return f"/officer/cases/{pk}/"


def _decide_url(pk: int) -> str:
    return f"/officer/cases/{pk}/decide/"


@pytest.fixture
def cases(users, districts) -> dict:
    """Per district: one run with three listings in three different bands, two candidates
    for the first listing. Everything synthetic."""
    out: dict = {}
    for key, district in districts.items():
        officer = users[f"off_{key}"]
        reg_batch = UploadBatch.objects.create(
            type="registry", file_sha256=f"r8{key}", row_count=2, dataset="m8-test"
        )
        lst_batch = UploadBatch.objects.create(
            type="listings",
            file_sha256=f"l8{key}",
            row_count=3,
            uploader=officer,
            district=district,
            dataset="m8-test",
        )
        entries = [
            RegistryEntry.objects.create(
                licence_no=f"SYN-{key}-{n}",
                name=f"Synthetic Registry Stay {key} {n}",
                locality=f"Synthetic Hill {key}",
                valid_to=date(2030, 1, 1),
                batch=reg_batch,
                district=district,
            )
            for n in (1, 2)
        ]
        run = MatchRun.objects.create(
            district=district,
            params_version="m8-test",
            created_by=officer,
            thresholds={"fingerprint": "abc123"},
            as_of=date(2026, 4, 1),
            listing_batch=lst_batch,
            registry_batch=reg_batch,
        )
        specs = [
            # title, locality, band, score
            (f"Synthetic Listing {key} A", f"Synthetic Hill {key}", "review_score", 0.80),
            (f"Synthetic Listing {key} B", "Synthetic Lake", "review_licence", 0.60),
            (f"Synthetic Listing {key} C", "Synthetic Lake", "matched_licence", 0.95),
        ]
        listings, results = [], []
        for title, locality, band, score in specs:
            listing = Listing.objects.create(
                platform="synthetic",
                title=title,
                locality_text=locality,
                batch=lst_batch,
                district=district,
            )
            listings.append(listing)
            results.append(
                MatchResult.objects.create(
                    run=run,
                    listing=listing,
                    status=engine.STATUS[band],
                    band=band,
                    reasons=["score_between_thresholds"],
                    top_registry_entry=entries[0],
                    score=score,
                    priority=engine.PRIORITY[band],
                )
            )
        for rank, entry in enumerate(entries, start=1):
            MatchCandidate.objects.create(
                run=run,
                listing=listings[0],
                registry_entry=entry,
                score=0.8 - rank / 10,
                rank=rank,
                features={
                    "licence": None,
                    "name": 0.9,
                    "address": 1.0,
                    "distance": None,
                    "pincode": 0.0,
                    "category": 1.0,
                    "blocked_by": ["locality", "name_key"],
                    "detail": {"distance_km": None},
                },
            )
        out[key] = {
            "run": run,
            "entries": entries,
            "listings": listings,
            "results": results,
            "officer": officer,
        }
    return out


def _form(case: dict, idx: int = 0, **extra) -> dict:
    listing = case["listings"][idx]
    latest = Review.objects.filter(listing=listing).order_by("-id").first()
    data = {
        "run": case["run"].pk,
        "version": latest.pk if latest else 0,
        "decision": "confirm_match",
        "registry_entry": case["entries"][0].pk,
        "reason": "",
    }
    data.update(extra)
    return data


# ------------------------------------------------------------------ queue


def test_queue_is_scoped_per_district(users, cases) -> None:
    nil = _client(users["off_nil"]).get(QUEUE + "?state=all")
    assert nil.status_code == 200
    seen = {row["result"].listing_id for row in nil.context["rows"]}
    assert seen == {x.pk for x in cases["nil"]["listings"]}

    mad = _client(users["off_mad"]).get(QUEUE + "?state=all")
    assert {row["result"].listing_id for row in mad.context["rows"]} == {
        x.pk for x in cases["mad"]["listings"]
    }
    assert "Synthetic Listing nil" not in mad.content.decode()

    admin = _client(users["admin"]).get(QUEUE + "?state=all")
    assert len(admin.context["rows"]) == 6


def test_queue_order_and_open_state(users, cases) -> None:
    page = _client(users["off_nil"]).get(QUEUE)
    bands = [row["result"].band for row in page.context["rows"]]
    # Open queue: matched_licence is open too (no decision yet); priority order.
    assert bands == ["review_licence", "review_score", "matched_licence"]


def test_queue_ties_lower_score_first(users, cases) -> None:
    nil = cases["nil"]
    for result, score in zip(nil["results"], (0.85, 0.70, 0.95), strict=True):
        MatchResult.objects.filter(pk=result.pk).update(
            band="review_score", priority=3, status="needs_review", score=score
        )
    page = _client(users["off_nil"]).get(QUEUE)
    assert [row["result"].score for row in page.context["rows"]] == [0.70, 0.85, 0.95]


def test_queue_filters(users, cases) -> None:
    client = _client(users["off_nil"])
    by_band = client.get(QUEUE + "?band=review_licence")
    assert [r["result"].band for r in by_band.context["rows"]] == ["review_licence"]
    assert by_band.context["total_unbanded"] == 3
    by_status = client.get(QUEUE + "?status=matched")
    assert [r["result"].band for r in by_status.context["rows"]] == ["matched_licence"]
    by_locality = client.get(QUEUE + "?locality=lake")
    assert len(by_locality.context["rows"]) == 2
    bogus = client.get(QUEUE + "?band=nope&status=x&state=y&page=abc")
    assert bogus.status_code == 200 and len(bogus.context["rows"]) == 3
    empty = client.get(QUEUE + "?locality=nowhere")
    assert "No cases match these filters." in empty.content.decode()


def test_queue_pagination(users, cases, monkeypatch) -> None:
    from reviews import views

    monkeypatch.setattr(views, "PAGE_SIZE", 2)
    client = _client(users["off_nil"])
    first = client.get(QUEUE + "?state=all")
    assert len(first.context["rows"]) == 2
    body = first.content.decode()
    assert "Page 1 of 2" in body and "state=all&amp;page=2" in body
    second = client.get(QUEUE + "?state=all&page=2")
    assert len(second.context["rows"]) == 1


def test_queue_uses_latest_run_only(users, cases) -> None:
    nil = cases["nil"]
    newer = MatchRun.objects.create(district=nil["run"].district, params_version="m8-test")
    MatchResult.objects.create(
        run=newer,
        listing=nil["listings"][0],
        status="no_match",
        band="no_candidate",
        priority=2,
    )
    rows = _client(users["off_nil"]).get(QUEUE + "?state=all").context["rows"]
    assert len(rows) == 3
    first = next(r["result"] for r in rows if r["result"].listing_id == nil["listings"][0].pk)
    assert first.run_id == newer.pk and first.band == "no_candidate"


def test_empty_queue_message(users, districts) -> None:
    body = _client(users["off_nil"]).get(QUEUE).content.decode()
    assert "No cases need review." in body


# ------------------------------------------------------------------- case


def test_case_detail_shows_candidates_and_features(users, cases) -> None:
    listing = cases["nil"]["listings"][0]
    page = _client(users["off_nil"]).get(_case(listing.pk))
    assert page.status_code == 200
    body = page.content.decode()
    assert "badge badge--review_score" in body
    assert "Synthetic Registry Stay nil 1" in body and "SYN-nil-2" in body
    assert "Score between the lower and upper thresholds" in body  # reason label
    assert "same locality, similar name" in body
    assert "0.90" in body  # stored name feature
    assert 'name="csrfmiddlewaretoken"' in body
    assert f'name="run" value="{cases["nil"]["run"].pk}"' in body


def test_other_district_case_is_404_and_audited(users, cases) -> None:
    listing = cases["nil"]["listings"][0]
    mad = _client(users["off_mad"])
    assert mad.get(_case(listing.pk)).status_code == 404
    assert mad.post(_decide_url(listing.pk), _form(cases["nil"])).status_code == 404
    assert mad.get(f"/officer/cases/{listing.pk}/evidence/").status_code == 404
    assert mad.post(f"/officer/cases/{listing.pk}/evidence/").status_code == 404
    assert not Review.objects.exists() and not EvidencePack.objects.exists()
    denials = AuditLog.objects.filter(
        action="permission_denied", actor="officer_mad", meta__reason="out_of_district"
    )
    assert denials.count() == 4


def test_unknown_case_is_404(users, cases) -> None:
    assert _client(users["off_nil"]).get(_case(999999)).status_code == 404


# -------------------------------------------------------------- decisions


def test_confirm_match_saves_review_pair_and_audit(users, cases) -> None:
    nil = cases["nil"]
    listing = nil["listings"][0]
    response = _client(users["off_nil"]).post(_decide_url(listing.pk), _form(nil))
    assert response.status_code == 302 and response["Location"] == _case(listing.pk)
    review = Review.objects.get()
    assert review.decision == "confirm_match" and review.reviewer == users["off_nil"]
    assert review.run == nil["run"] and review.registry_entry == nil["entries"][0]
    assert ConfirmedPair.objects.filter(listing=listing, registry_entry=nil["entries"][0]).exists()
    entry = AuditLog.objects.get(action="review.decide")
    assert entry.actor == "officer_nil" and entry.entity == "listing"
    assert entry.entity_id == str(listing.pk)
    assert entry.meta["decision"] == "confirm_match" and entry.meta["review"] == review.pk
    assert entry.meta["confirmed_pair"] == "added" and entry.meta["licence_no"] == "SYN-nil-1"
    # Decided cases leave the open queue.
    rows = _client(users["off_nil"]).get(QUEUE).context["rows"]
    assert listing.pk not in {r["result"].listing_id for r in rows}


def test_reject_match_removes_confirmed_pair(users, cases) -> None:
    nil = cases["nil"]
    listing = nil["listings"][0]
    client = _client(users["off_nil"])
    client.post(_decide_url(listing.pk), _form(nil))
    response = client.post(_decide_url(listing.pk), _form(nil, decision="reject_match"))
    assert response.status_code == 302
    assert not ConfirmedPair.objects.exists()
    assert Review.objects.count() == 2  # history kept, nothing updated
    last = AuditLog.objects.filter(action="review.decide").order_by("-id").first()
    assert last.meta["confirmed_pair"] == "removed" and last.meta["supersedes"] is not None


def test_confirm_requires_a_candidate_entry(users, cases) -> None:
    nil = cases["nil"]
    listing = nil["listings"][0]
    client = _client(users["off_nil"])
    missing = client.post(_decide_url(listing.pk), _form(nil, registry_entry=""))
    assert missing.status_code == 400
    assert "Choose the registry entry" in missing.content.decode()
    # An entry of the same district that is not a candidate of this listing.
    other = client.post(_decide_url(listing.pk), _form(nil, registry_entry=99999))
    assert other.status_code == 400
    # An entry from another district is refused the same way.
    foreign = client.post(
        _decide_url(listing.pk), _form(nil, registry_entry=cases["mad"]["entries"][0].pk)
    )
    assert foreign.status_code == 400
    assert not Review.objects.exists() and not ConfirmedPair.objects.exists()
    assert not AuditLog.objects.filter(action="review.decide").exists()


def test_suspected_requires_reason(users, cases) -> None:
    nil = cases["nil"]
    listing = nil["listings"][1]
    client = _client(users["off_nil"])
    for reason in ("", "   \n  "):
        response = client.post(
            _decide_url(listing.pk), _form(nil, 1, decision=SUSPECTED, reason=reason)
        )
        assert response.status_code == 400
        assert "A written reason is required" in response.content.decode()
        assert 'aria-invalid="true"' in response.content.decode()
    assert not Review.objects.exists()

    ok = client.post(
        _decide_url(listing.pk),
        _form(nil, 1, decision=SUSPECTED, reason="Synthetic note: licence number not found."),
    )
    assert ok.status_code == 302
    review = Review.objects.get()
    assert review.decision == SUSPECTED and review.registry_entry is None
    audit_row = AuditLog.objects.get(action="review.decide")
    assert audit_row.meta["reason"] == "Synthetic note: licence number not found."


def test_reason_length_limit(users, cases) -> None:
    nil = cases["nil"]
    response = _client(users["off_nil"]).post(
        _decide_url(nil["listings"][1].pk),
        _form(nil, 1, decision="dismiss", reason="x" * (services.MAX_REASON + 1)),
    )
    assert response.status_code == 400 and not Review.objects.exists()


def test_admin_cannot_mark_suspected(users, cases) -> None:
    nil = cases["nil"]
    listing = nil["listings"][1]
    admin = _client(users["admin"])
    page = admin.get(_case(listing.pk)).content.decode()
    assert f'value="{SUSPECTED}"' not in page
    response = admin.post(
        _decide_url(listing.pk), _form(nil, 1, decision=SUSPECTED, reason="synthetic reason")
    )
    assert response.status_code == 403
    assert not Review.objects.exists()
    assert AuditLog.objects.filter(
        action="permission_denied", actor="admin_one", meta__reason="decision_not_allowed_for_role"
    ).exists()
    # Other decisions are allowed for an admin.
    ok = admin.post(_decide_url(listing.pk), _form(nil, 1, decision="dismiss"))
    assert ok.status_code == 302 and Review.objects.get().reviewer == users["admin"]


def test_officer_sees_suspected_option(users, cases) -> None:
    page = _client(users["off_nil"]).get(_case(cases["nil"]["listings"][1].pk))
    assert f'value="{SUSPECTED}"' in page.content.decode()


@pytest.mark.parametrize("decision", ["", "approve", "SUSPECTED_UNLICENSED"])
def test_unknown_decision_rejected(users, cases, decision) -> None:
    nil = cases["nil"]
    response = _client(users["off_nil"]).post(
        _decide_url(nil["listings"][0].pk), _form(nil, decision=decision)
    )
    assert response.status_code == 400 and not Review.objects.exists()


def test_decision_permission_matrix(users, cases, districts) -> None:
    listing = cases["nil"]["listings"][0]
    data = _form(cases["nil"])
    # Anonymous: login redirect, nothing saved.
    anon = Client().post(_decide_url(listing.pk), data)
    assert anon.status_code == 302 and "/login/" in anon["Location"]
    # Inactive officer: force_login is refused by the auth backend -> treated as anonymous.
    inactive = Client()
    inactive.force_login(users["inactive"])
    assert inactive.post(_decide_url(listing.pk), data).status_code in (302, 403)
    # Other-district officer: 404.
    assert _client(users["off_mad"]).post(_decide_url(listing.pk), data).status_code == 404
    assert not Review.objects.exists()
    # Own-district officer and admin: allowed.
    assert _client(users["off_nil"]).post(_decide_url(listing.pk), data).status_code == 302
    data2 = _form(cases["nil"], decision="dismiss")
    assert _client(users["admin"]).post(_decide_url(listing.pk), data2).status_code == 302
    assert Review.objects.count() == 2


def test_decide_is_post_only_and_needs_csrf(users, cases) -> None:
    listing = cases["nil"]["listings"][0]
    client = _client(users["off_nil"])
    assert client.get(_decide_url(listing.pk)).status_code == 405
    strict = _client(users["off_nil"], enforce_csrf_checks=True)
    assert strict.post(_decide_url(listing.pk), _form(cases["nil"])).status_code == 403
    assert not Review.objects.exists()


def test_stale_form_is_a_conflict(users, cases) -> None:
    nil = cases["nil"]
    listing = nil["listings"][0]
    stale = _form(nil)  # version 0
    assert (
        _client(users["admin"])
        .post(_decide_url(listing.pk), _form(nil, decision="dismiss"))
        .status_code
        == 302
    )
    response = _client(users["off_nil"]).post(_decide_url(listing.pk), stale)
    assert response.status_code == 409
    body = response.content.decode()
    assert "Not saved: this case changed while you were viewing it." in body
    assert "admin_one" in body
    assert Review.objects.count() == 1 and not ConfirmedPair.objects.exists()


def test_new_run_makes_form_stale(users, cases) -> None:
    nil = cases["nil"]
    listing = nil["listings"][0]
    data = _form(nil)
    newer = MatchRun.objects.create(district=nil["run"].district, params_version="m8-test")
    MatchResult.objects.create(
        run=newer, listing=listing, status="no_match", band="no_candidate", priority=2
    )
    response = _client(users["off_nil"]).post(_decide_url(listing.pk), data)
    assert response.status_code == 409
    assert "A newer matching run replaced the result" in response.content.decode()
    assert not Review.objects.exists()


def test_listing_without_run_cannot_be_decided(users, cases, districts) -> None:
    listing = Listing.objects.create(
        platform="synthetic",
        title="Synthetic Unrun Listing",
        locality_text="Synthetic Lake",
        district=districts["nil"],
    )
    client = _client(users["off_nil"])
    page = client.get(_case(listing.pk))
    assert "has not been through a matching run yet" in page.content.decode()
    response = client.post(_decide_url(listing.pk), {"decision": "dismiss", "run": 0})
    assert response.status_code == 400 and not Review.objects.exists()


def test_model_refuses_cross_district_review(users, cases) -> None:
    from django.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        Review.objects.create(
            listing=cases["nil"]["listings"][0],
            reviewer=users["off_nil"],
            decision="confirm_match",
            registry_entry=cases["mad"]["entries"][0],
        )


# --------------------------------------------------------------- evidence


def test_evidence_page_content_and_hash(users, cases) -> None:
    nil = cases["nil"]
    listing = nil["listings"][0]
    client = _client(users["off_nil"])
    empty = client.get(f"/officer/cases/{listing.pk}/evidence/")
    assert empty.status_code == 200 and "No evidence page has been created" in (
        empty.content.decode()
    )
    client.post(_decide_url(listing.pk), _form(nil, reason="Synthetic check of name."))

    response = client.post(f"/officer/cases/{listing.pk}/evidence/")
    pack = EvidencePack.objects.get()
    assert response.status_code == 302 and response["Location"] == f"/officer/evidence/{pack.pk}/"
    assert pack.sha256 == services.snapshot_sha256(pack.snapshot)
    assert pack.snapshot["statement"] == services.EVIDENCE_STATEMENT
    assert pack.snapshot["decision"]["decision"] == "confirm_match"
    assert [c["registry_entry"]["licence_no"] for c in pack.snapshot["candidates"]] == [
        "SYN-nil-1",
        "SYN-nil-2",
    ]
    assert pack.snapshot["run"]["params_version"] == "m8-test"
    audit_row = AuditLog.objects.get(action="evidence.create")
    assert audit_row.entity_id == str(pack.pk) and audit_row.meta["sha256"] == pack.sha256

    page = client.get(response["Location"])
    body = page.content.decode()
    main = body[body.index('<main id="main"') :]
    # The O5 statement comes before any data on the page.
    statement = (
        '<p class="evidence-statement">Supporting evidence for officer review, not a finding.</p>'
    )
    assert statement in main
    assert main.index(statement) < main.index("Listing snapshot")
    assert pack.sha256 in body and "still produces this SHA-256" in body
    assert "synthetic" in body.lower()
    assert "Synthetic check of name." in body and "Confirm match" in body
    assert "Feature scores" in body and "SYN-nil-2" in body
    # The case page's GET now redirects to the latest evidence page.
    latest = client.get(f"/officer/cases/{listing.pk}/evidence/")
    assert latest.status_code == 302 and latest["Location"] == f"/officer/evidence/{pack.pk}/"


def test_evidence_page_other_district_404(users, cases) -> None:
    listing = cases["nil"]["listings"][0]
    _client(users["off_nil"]).post(f"/officer/cases/{listing.pk}/evidence/")
    pack = EvidencePack.objects.get()
    assert _client(users["off_mad"]).get(f"/officer/evidence/{pack.pk}/").status_code == 404
    assert AuditLog.objects.filter(
        action="permission_denied", actor="officer_mad", entity="reviews.EvidencePack"
    ).exists()


def test_case_evidence_get_redirects_to_newest_pack_and_post_adds_one(users, cases) -> None:
    listing = cases["nil"]["listings"][0]
    client = _client(users["off_nil"])
    first = client.post(f"/officer/cases/{listing.pk}/evidence/")
    second = client.post(f"/officer/cases/{listing.pk}/evidence/")
    packs = list(EvidencePack.objects.order_by("id"))
    assert len(packs) == 2 and first["Location"] != second["Location"]
    latest = client.get(f"/officer/cases/{listing.pk}/evidence/")
    assert latest["Location"] == f"/officer/evidence/{packs[1].pk}/"
    # Each pack is audited once; a GET is not a state change.
    assert AuditLog.objects.filter(action="evidence.create").count() == 2
    # Another listing of the same district still has no pack.
    other = cases["nil"]["listings"][1]
    empty = client.get(f"/officer/cases/{other.pk}/evidence/")
    assert empty.status_code == 200 and "No evidence page has been created" in (
        empty.content.decode()
    )


def test_evidence_detail_reports_a_changed_snapshot(users, cases) -> None:
    listing = cases["nil"]["listings"][0]
    client = _client(users["off_nil"])
    client.post(f"/officer/cases/{listing.pk}/evidence/")
    pack = EvidencePack.objects.get()
    ok = client.get(f"/officer/evidence/{pack.pk}/").content.decode()
    assert "still produces this SHA-256" in ok and "does not produce" not in ok
    changed = {**pack.snapshot, "statement": "edited after the fact"}
    EvidencePack.objects.filter(pk=pack.pk).update(snapshot=changed)
    body = client.get(f"/officer/evidence/{pack.pk}/").content.decode()
    assert "Problem: the stored snapshot does not produce this SHA-256." in body


def test_evidence_detail_get_only_unknown_and_anonymous(users, cases) -> None:
    listing = cases["nil"]["listings"][0]
    client = _client(users["off_nil"])
    client.post(f"/officer/cases/{listing.pk}/evidence/")
    pack = EvidencePack.objects.get()
    assert client.post(f"/officer/evidence/{pack.pk}/").status_code == 405
    assert client.get("/officer/evidence/999999/").status_code == 404
    anon = Client().get(f"/officer/evidence/{pack.pk}/")
    assert anon.status_code == 302 and "/login/" in anon["Location"]
    assert Client().post(f"/officer/cases/{listing.pk}/evidence/").status_code == 302
    assert EvidencePack.objects.count() == 1


def test_evidence_print_css_present() -> None:
    css = (Path(__file__).resolve().parents[1] / "src" / "static" / "css" / "app.css").read_text(
        encoding="utf-8"
    )
    assert "@media print" in css and ".evidence-statement" in css


# --------------------------------------------------------------- dashboard


def test_dashboard_counts_scoped(users, cases) -> None:
    nil = cases["nil"]
    _client(users["off_nil"]).post(_decide_url(nil["listings"][0].pk), _form(nil))
    nil_counts = _client(users["off_nil"]).get("/dashboard/").context["counts"]
    assert nil_counts["listings"] == 3 and nil_counts["with_result"] == 3
    assert nil_counts["open"] == 2 and nil_counts["decisions"] == 1
    assert nil_counts["confirmed_pairs"] == 1
    mad_counts = _client(users["off_mad"]).get("/dashboard/").context["counts"]
    assert mad_counts["open"] == 3 and mad_counts["decisions"] == 0
    admin_counts = _client(users["admin"]).get("/dashboard/").context["counts"]
    assert admin_counts["listings"] == 6 and admin_counts["open"] == 5


# ------------------------------------------- confirmed pair suppression (real run)


@pytest.fixture
def dev_set(db) -> None:
    load_synthetic_set(DEV, "synthetic-dev", "system:test")


def _officer_batch(client: Client) -> UploadBatch:
    data = (DEV / "demo_listings.csv").read_bytes()
    preview = client.post(
        "/officer/uploads/",
        {"file": SimpleUploadedFile("demo.csv", data, "text/csv"), "dataset": "synthetic-dev"},
    )
    token = re.search(r'name="token" value="([^"]+)"', preview.content.decode()).group(1)
    client.post("/officer/uploads/confirm/", {"token": token})
    return UploadBatch.objects.get(source_name="demo.csv")


def test_confirmed_pair_is_suppressed_on_next_run(users, dev_set) -> None:
    client = _client(users["off_nil"])
    batch = _officer_batch(client)
    client.post("/officer/runs/start/", {"batch": batch.pk})
    first_run = MatchRun.objects.get(listing_batch=batch)
    # A listing in a review band whose top candidate is valid on the run date.
    result = next(
        r
        for r in MatchResult.objects.filter(run=first_run, band="review_score").select_related(
            "top_registry_entry"
        )
        if r.top_registry_entry
        and r.top_registry_entry.status == "active"
        and r.top_registry_entry.valid_to >= first_run.as_of
    )
    response = client.post(
        _decide_url(result.listing_id),
        {
            "run": first_run.pk,
            "version": 0,
            "decision": "confirm_match",
            "registry_entry": result.top_registry_entry_id,
            "reason": "",
        },
    )
    assert response.status_code == 302

    client.post("/officer/runs/start/", {"batch": batch.pk})
    second_run = MatchRun.objects.filter(listing_batch=batch).order_by("-id").first()
    assert second_run.pk != first_run.pk
    again = MatchResult.objects.get(run=second_run, listing_id=result.listing_id)
    assert again.band == "matched_confirmed"
    assert again.top_registry_entry_id == result.top_registry_entry_id
    # Not re-flagged: absent from the open queue, present when asking for decided cases.
    open_rows = client.get(QUEUE).context["rows"]
    assert result.listing_id not in {r["result"].listing_id for r in open_rows}
    decided = client.get(QUEUE + "?state=decided").context["rows"]
    assert result.listing_id in {r["result"].listing_id for r in decided}
