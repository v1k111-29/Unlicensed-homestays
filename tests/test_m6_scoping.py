"""District scoping (AGENTS.md rule 7): an officer cannot read or change another district's data
through the shared helper, through a view that uses it, or by naming another district."""

import pytest
from django.apps import apps
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import ImproperlyConfigured

from accounts.scoping import DISTRICT_PATHS, can_act_in_district, district_path, scoped
from audit.models import AuditLog
from listings.models import Listing
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
def test_match_run_spanning_districts_is_not_duplicated(users, district_data) -> None:
    from matching.models import MatchResult

    run = district_data["nil"]["MatchRun"]
    MatchResult.objects.create(
        run=run,
        listing=Listing.objects.create(
            platform="synthetic",
            title="extra",
            locality_text="x",
            district=district_data["nil"]["District"],
        ),
        status="no_match",
    )
    from matching.models import MatchRun

    assert scoped(MatchRun, users["off_nil"]).filter(pk=run.pk).count() == 1


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
