"""District scoping (AGENTS.md rule 7): an officer cannot read or change another district's data
through the shared helper, through a view that uses it, or by naming another district."""

import pytest
from django.apps import apps
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured, ValidationError

from accounts.scoping import DISTRICT_PATHS, can_act_in_district, district_path, scoped
from audit.models import AuditLog
from listings.models import Listing
from matching.models import MatchRun
from reviews.models import Review

DATA_APPS = ["accounts", "registry", "listings", "matching", "reviews"]


def _model(key: str):
    return apps.get_model(key)


def test_every_data_model_has_a_district_path() -> None:
    """Fail closed: a new model in a data app must declare its district path before use."""
    missing = [
        f"{m._meta.app_label}.{m.__name__}"
        for label in DATA_APPS
        for m in apps.get_app_config(label).get_models()
        if f"{m._meta.app_label}.{m.__name__}" not in DISTRICT_PATHS
    ]
    assert missing == []


def test_unregistered_model_is_refused() -> None:
    with pytest.raises(ImproperlyConfigured):
        district_path(AuditLog)


@pytest.mark.django_db
@pytest.mark.parametrize("key", sorted(DISTRICT_PATHS))
def test_officer_sees_only_own_district(key: str, users, district_data) -> None:
    name = key.split(".")[1]
    model = _model(key)
    own, other = district_data["nil"][name], district_data["mad"][name]
    visible = set(scoped(model, users["off_nil"]).values_list("pk", flat=True))
    assert own.pk in visible
    assert other.pk not in visible


@pytest.mark.django_db
@pytest.mark.parametrize("key", sorted(DISTRICT_PATHS))
def test_admin_sees_all_districts(key: str, users, district_data) -> None:
    name = key.split(".")[1]
    visible = set(scoped(_model(key), users["admin"]).values_list("pk", flat=True))
    assert {district_data["nil"][name].pk, district_data["mad"][name].pk} <= visible


@pytest.mark.django_db
@pytest.mark.parametrize("key", sorted(DISTRICT_PATHS))
def test_anonymous_and_inactive_see_nothing(key: str, users, district_data) -> None:
    model = _model(key)
    assert not scoped(model, AnonymousUser()).exists()
    assert not scoped(model, users["inactive"]).exists()


@pytest.mark.django_db
def test_officer_without_district_sees_nothing(users, district_data) -> None:
    officer = users["off_nil"]
    officer.district_id = None  # in memory only; the DB check forbids saving this
    assert not scoped(Listing, officer).exists()


@pytest.mark.django_db
def test_scoping_narrows_a_given_queryset(users, district_data) -> None:
    """A caller-built queryset cannot widen the scope."""
    everything = Listing.objects.all()
    assert list(scoped(everything, users["off_mad"])) == [district_data["mad"]["Listing"]]


@pytest.mark.django_db
def test_relation_traversal_cannot_leak_other_district(users, district_data) -> None:
    """Rows reached through a visible object's reverse relation are scoped again. A result that
    slipped past validation (bulk_create skips save()) into the officer's own run, but belongs to
    another district's listing, is still filtered out."""
    from matching.models import MatchResult

    own_run = district_data["nil"]["MatchRun"]
    foreign_listing = district_data["mad"]["Listing"]
    MatchResult.objects.bulk_create(
        [MatchResult(run=own_run, listing=foreign_listing, status="no_match")]
    )
    officer = users["off_nil"]
    visible = scoped(own_run.results.all(), officer)
    assert foreign_listing.pk not in set(visible.values_list("listing_id", flat=True))
    assert visible.count() == 1
    # The other district's run is not reachable at all.
    assert not scoped(MatchRun, officer).filter(pk=district_data["mad"]["MatchRun"].pk).exists()


@pytest.mark.django_db
def test_cross_district_match_rows_are_refused(district_data) -> None:
    from matching.models import MatchCandidate, MatchResult
    from reviews.models import ConfirmedPair

    nil, mad = district_data["nil"], district_data["mad"]
    with pytest.raises(ValidationError):  # listing outside the run's district
        MatchResult(run=nil["MatchRun"], listing=mad["Listing"], status="no_match").save()
    with pytest.raises(ValidationError):  # candidate entry from another district
        MatchCandidate(
            run=nil["MatchRun"],
            listing=nil["Listing"],
            registry_entry=mad["RegistryEntry"],
            score=0.1,
            rank=2,
        ).save()
    with pytest.raises(ValidationError):
        ConfirmedPair(listing=nil["Listing"], registry_entry=mad["RegistryEntry"]).save()


@pytest.mark.django_db
def test_can_act_in_district(users, districts) -> None:
    nil, mad = districts["nil"], districts["mad"]
    assert can_act_in_district(users["off_nil"], nil)
    assert can_act_in_district(users["off_nil"], nil.pk)
    assert not can_act_in_district(users["off_nil"], mad)
    assert can_act_in_district(users["admin"], mad)
    assert not can_act_in_district(AnonymousUser(), nil)
    assert not can_act_in_district(users["off_nil"], None)


# --- through views (tests/m6_urls.py) ---


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
def test_list_view_returns_own_district_only(client, users, district_data) -> None:
    client.force_login(users["off_nil"])
    assert client.get("/t/listings/").json() == {"ids": [district_data["nil"]["Listing"].pk]}


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
def test_officer_cannot_read_other_district_object(client, users, district_data) -> None:
    other = district_data["mad"]["Listing"]
    client.force_login(users["off_nil"])
    assert client.get(f"/t/listings/{other.pk}/").status_code == 404
    row = AuditLog.objects.get(action="permission_denied")
    assert row.actor == "officer_nil"
    assert row.entity == "listings.Listing" and row.entity_id == str(other.pk)
    assert row.meta["reason"] == "out_of_district"


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
def test_officer_cannot_alter_other_district_object(client, users, district_data) -> None:
    other = district_data["mad"]["Listing"]
    reviews_before = Review.objects.filter(listing=other).count()
    client.force_login(users["off_nil"])
    response = client.post(f"/t/listings/{other.pk}/", {"title": "changed"})
    assert response.status_code == 404
    other.refresh_from_db()
    assert other.title == "Synthetic listing mad"
    assert Review.objects.filter(listing=other).count() == reviews_before


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
def test_officer_can_alter_own_district_object(client, users, district_data) -> None:
    own = district_data["nil"]["Listing"]
    client.force_login(users["off_nil"])
    assert client.post(f"/t/listings/{own.pk}/", {"title": "changed"}).status_code == 200
    own.refresh_from_db()
    assert own.title == "changed"


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
def test_missing_object_is_404_without_denial_entry(client, users, district_data) -> None:
    client.force_login(users["off_nil"])
    assert client.get("/t/listings/999999/").status_code == 404
    assert not AuditLog.objects.filter(action="permission_denied").exists()


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
def test_admin_can_read_any_district_object(client, users, district_data) -> None:
    client.force_login(users["admin"])
    for key in ("nil", "mad"):
        assert client.get(f"/t/listings/{district_data[key]['Listing'].pk}/").status_code == 200


@pytest.mark.django_db
@pytest.mark.urls("tests.m6_urls")
def test_officer_cannot_act_on_other_district_by_naming_it(client, users, districts) -> None:
    client.force_login(users["off_nil"])
    assert client.post(f"/t/upload/{districts['nil'].pk}/").status_code == 200
    assert client.post(f"/t/upload/{districts['mad'].pk}/").status_code == 403
    row = AuditLog.objects.get(action="permission_denied")
    assert row.meta["reason"] == "out_of_district"
    assert row.meta["district_id"] == districts["mad"].pk
