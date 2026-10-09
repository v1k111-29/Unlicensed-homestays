"""M9 tourist check (essentialfeatures.md T1): four outcomes, the verbatim disclaimer, neutral
wording, public fields only, no IP/query stored, no cookies, rate limit.

All registry rows below are synthetic and made up for these tests (AGENTS.md rule 3)."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

import pytest
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import resolve

from accounts.models import District
from registry.models import RegistryEntry, UploadBatch
from tourist import service
from tourist.models import TouristCheck
from tourist.service import Query

pytestmark = pytest.mark.django_db

URL = "/check/"
DISCLAIMER = "This does not mean the stay is illegal. The registry may be incomplete."
FORBIDDEN = re.compile(r"\b(illegal|fake|unlicensed)\b", re.IGNORECASE)
SECRET_IP = "203.0.113.77"


def _entry(batch, district, licence, name, locality, **extra) -> RegistryEntry:
    values = {
        "category": "homestay",
        "valid_from": date(2024, 1, 1),
        "valid_to": date(2028, 12, 31),
        "status": "active",
    }
    values.update(extra)
    return RegistryEntry.objects.create(
        batch=batch, district=district, licence_no=licence, name=name, locality=locality, **values
    )


@pytest.fixture
def registry(db) -> dict:
    nil = District.objects.get(name_en="Nilgiris")
    mad = District.objects.get(name_en="Madurai")
    # "synthetic-dev" -> validity judged on the synthetic reference date 2026-04-01 (D54).
    batch = UploadBatch.objects.create(
        type="registry", dataset="synthetic-dev", file_sha256="m9" * 32, row_count=6
    )
    rows = {
        "found": _entry(
            batch,
            nil,
            "SYN-NLG-90001-A",
            "Kurinji Mist Homestay",
            "Ooty",
            address_en="12 Synthetic Lane, Ooty",
            address_ta="12 செயற்கை தெரு, ஊட்டி",
            pincode="643001",
            lat=Decimal("11.410200"),
            lng=Decimal("76.695000"),
        ),
        "expired": _entry(
            batch,
            nil,
            "SYN-NLG-90002-B",
            "Cedar Fold Cottage",
            "Coonoor",
            category="cottage",
            valid_to=date(2025, 12, 31),
            status="expired",
        ),
        "twin_a": _entry(batch, nil, "SYN-NLG-90003-C", "Silver Fern Lodge", "Kotagiri"),
        "twin_b": _entry(batch, nil, "SYN-NLG-90004-D", "Silver Fern Lodge Annexe", "Kotagiri"),
        "madurai": _entry(batch, mad, "SYN-MDU-90005-E", "Temple Lane Residency", "Simmakkal"),
    }
    rows["batch"] = batch
    rows["nil"], rows["mad"] = nil, mad
    return rows


def _post(client: Client, **data) -> object:
    return client.post(URL, data, REMOTE_ADDR=SECRET_IP)


def _text(response) -> str:
    return response.content.decode()


# ------------------------------------------------------------------ service outcomes


def test_found_by_name_and_locality(registry) -> None:
    r = service.check(Query(name="Kurinji Mist Homestay", locality="Ooty"))
    assert r.outcome == "found"
    assert [e.name for e in r.entries] == ["Kurinji Mist Homestay"]
    assert r.as_of == date(2026, 4, 1)


def test_found_by_licence_ignores_case_and_punctuation(registry) -> None:
    r = service.check(Query(licence="syn nlg 90001 a"))
    assert r.outcome == "found"


def test_found_with_tamil_locality(registry) -> None:
    r = service.check(Query(name="Kurinji Mist Homestay", locality="ஊட்டி"))
    assert r.outcome == "found"


def test_differs_when_not_valid_on_date(registry) -> None:
    r = service.check(Query(name="Cedar Fold Cottage", locality="Coonoor"))
    assert r.outcome == "differs"
    assert r.differences == ("validity",)
    assert r.entries[0].valid_on_date is False


def test_differs_when_licence_name_disagrees(registry) -> None:
    r = service.check(Query(licence="SYN-NLG-90001-A", name="Harbour Pearl Villa"))
    assert r.outcome == "differs"
    assert "name" in r.differences


def test_differs_when_licence_unknown_but_name_found(registry) -> None:
    r = service.check(
        Query(licence="SYN-NLG-11111-Z", name="Kurinji Mist Homestay", locality="Ooty")
    )
    assert r.outcome == "differs"
    assert r.differences[0] == "licence"


def test_several_similar(registry) -> None:
    r = service.check(Query(name="Silver Fern Lodge", locality="Kotagiri"))
    assert r.outcome == "several"
    assert {e.name for e in r.entries} == {"Silver Fern Lodge", "Silver Fern Lodge Annexe"}


def test_not_found(registry) -> None:
    assert service.check(Query(name="Blue Lagoon Stay", locality="Ooty")).outcome == "not_found"
    assert service.check(Query(licence="SYN-NLG-00000-X")).outcome == "not_found"


def test_district_filter_narrows_search(registry) -> None:
    q = Query(name="Kurinji Mist Homestay", locality="Ooty", district_id=registry["mad"].pk)
    assert service.check(q).outcome == "not_found"
    q = Query(licence="SYN-MDU-90005-E", district_id=registry["mad"].pk)
    assert service.check(q).outcome == "found"


def test_check_is_deterministic(registry) -> None:
    q = Query(name="Silver Fern Lodge", locality="Kotagiri")
    assert service.check(q) == service.check(q)


def test_check_reads_registry_only(registry) -> None:
    """Never ground truth, listings or match results (D35)."""
    with CaptureQueriesContext(connection) as ctx:
        service.check(Query(name="Kurinji Mist Homestay", locality="Ooty"))
        service.check(Query(licence="SYN-NLG-90003-C"))
    sql = " ".join(q["sql"].lower() for q in ctx.captured_queries)
    for table in ("groundtruth", "ground_truth", "listings_listing", "matching_match"):
        assert table not in sql


def test_reserved_test_set_is_never_searched(db) -> None:
    UploadBatch.objects.create(
        type="registry", dataset="synthetic-test", file_sha256="t" * 64, row_count=0
    )
    with pytest.raises(service.RegistryUnavailable):
        service.check(Query(licence="SYN-NLG-90001-A"))


# ------------------------------------------------------------------ page


def test_page_is_public_and_allowlisted(db) -> None:
    assert resolve(URL).url_name == "tourist_check"
    response = Client().get(URL)
    assert response.status_code == 200
    html = _text(response)
    assert "Check a stay" in html
    assert "synthetic" in html.lower()
    assert "<script" not in html.lower()  # no JS/HTMX dependency


@pytest.mark.parametrize(
    ("data", "title", "css"),
    [
        ({"name": "Kurinji Mist Homestay", "locality": "Ooty"}, "Found in the registry", "found"),
        ({"name": "Cedar Fold Cottage", "locality": "Coonoor"}, "some details differ", "differs"),
        ({"name": "Silver Fern Lodge", "locality": "Kotagiri"}, "Several possible", "several"),
        ({"name": "Blue Lagoon Stay", "locality": "Ooty"}, "Not found in the", "not-found"),
    ],
)
def test_each_outcome_renders_and_logs(registry, data, title, css) -> None:
    response = _post(Client(), **data)
    assert response.status_code == 200
    html = _text(response)
    assert title in html
    assert f"result--{css}" in html
    assert TouristCheck.objects.get().result == css.replace("-", "_")


def test_not_found_shows_disclaimer_verbatim(registry) -> None:
    html = _text(_post(Client(), name="Blue Lagoon Stay", locality="Ooty"))
    assert f'<p class="disclaimer">{DISCLAIMER}</p>' in html


def test_disclaimer_only_on_not_found(registry) -> None:
    html = _text(_post(Client(), name="Kurinji Mist Homestay", locality="Ooty"))
    assert DISCLAIMER not in html


@pytest.mark.parametrize(
    "data",
    [
        {"name": "Kurinji Mist Homestay", "locality": "Ooty"},
        {"licence": "SYN-NLG-90001-A", "name": "Harbour Pearl Villa"},
        {"name": "Silver Fern Lodge", "locality": "Kotagiri"},
        {"name": "Blue Lagoon Stay", "locality": "Ooty"},
        {"name": "Blue Lagoon Stay"},
        {},
    ],
)
def test_no_forbidden_words_in_tourist_output(registry, data) -> None:
    html = _text(Client().get(URL)) + _text(_post(Client(), **data))
    html = html.replace(DISCLAIMER, "")  # the one mandated sentence (AGENTS.md rule 2)
    assert FORBIDDEN.findall(html) == []


def test_only_public_fields_are_shown(registry) -> None:
    html = _text(_post(Client(), name="Kurinji Mist Homestay", locality="Ooty"))
    assert "Kurinji Mist Homestay" in html and "Ooty" in html and "Homestay" in html
    for private in ("SYN-NLG-90001-A", "12 Synthetic Lane", "செயற்கை", "643001", "11.41", "76.69"):
        assert private not in html, private
    # Several: other entries' licence numbers are not exposed either.
    html = _text(_post(Client(), name="Silver Fern Lodge", locality="Kotagiri"))
    assert "SYN-NLG-90003-C" not in html and "SYN-NLG-90004-D" not in html


def test_public_entry_has_only_public_fields() -> None:
    assert set(service.PublicEntry.__dataclass_fields__) == {
        "name",
        "locality",
        "category",
        "status",
        "valid_from",
        "valid_to",
        "valid_on_date",
    }


# ------------------------------------------------------------------ privacy


def test_log_model_has_result_and_timestamp_only() -> None:
    assert {f.name for f in TouristCheck._meta.get_fields()} == {"id", "result", "created_at"}


def test_no_ip_or_query_stored_anywhere(registry) -> None:
    client = Client(HTTP_USER_AGENT="SyntheticAgent/9.9")
    client.post(URL, {"name": "Kurinji Mist Homestay", "locality": "Ooty"}, REMOTE_ADDR=SECRET_IP)
    client.post(URL, {"name": "Zephyrine Nook", "locality": "Ooty"}, REMOTE_ADDR=SECRET_IP)
    assert TouristCheck.objects.count() == 2
    dump = []
    with connection.cursor() as cursor:
        for table in connection.introspection.table_names():
            cursor.execute(f'SELECT * FROM "{table}"')  # noqa: S608 (test, table names from DB)
            dump.extend(repr(row) for row in cursor.fetchall())
    blob = "\n".join(dump)
    for needle in (SECRET_IP, "Zephyrine", "SyntheticAgent", "tourist-check-ip"):
        assert needle not in blob, needle


def test_rate_limit_counter_is_in_process_memory_only(registry) -> None:
    """D88: the address HMAC lives in the per-process memory cache, never in a database table
    (so it cannot reach django_cache or a backup)."""
    from django.conf import settings
    from django.core.cache import caches
    from django.test import RequestFactory

    from tourist import throttle

    backend = settings.CACHES[throttle.CACHE_ALIAS]["BACKEND"]
    assert backend == "django.core.cache.backends.locmem.LocMemCache"
    _post(Client(), licence="SYN-NLG-90001-A")
    key = throttle.cache_key(RequestFactory().post(URL, REMOTE_ADDR=SECRET_IP))
    assert caches[throttle.CACHE_ALIAS].get(key) == 1
    with connection.cursor() as cursor:
        cursor.execute("SELECT cache_key FROM django_cache")
        keys = [row[0] for row in cursor.fetchall()]
    assert not any("tourist" in k for k in keys), keys


def test_no_cookies_set(registry) -> None:
    client = Client()
    responses = [
        client.get(URL),
        _post(client, name="Kurinji Mist Homestay", locality="Ooty"),
        _post(client, name="Blue Lagoon Stay", locality="Ooty"),
        _post(client),
    ]
    for response in responses:
        assert response.cookies == {} or not response.cookies
        assert "Set-Cookie" not in response.headers
    assert not client.cookies


def test_invalid_form_logs_nothing(registry) -> None:
    response = _post(Client(), name="Kurinji Mist Homestay")
    assert response.status_code == 200
    html = _text(response)
    assert 'role="alert"' in html and 'aria-invalid="true"' in html
    assert TouristCheck.objects.count() == 0
    html = _text(_post(Client()))
    assert "Enter a licence number" in html


def test_no_registry_shows_error_state(db) -> None:
    response = _post(Client(), licence="SYN-NLG-90001-A")
    assert response.status_code == 503
    assert "not available" in _text(response)
    assert TouristCheck.objects.count() == 0


# ------------------------------------------------------------------ rate limit


def test_rate_limit_per_address(registry, settings) -> None:
    settings.TOURIST_THROTTLE = {"max_checks": 2, "window_seconds": 300}
    client = Client()
    data = {"licence": "SYN-NLG-90001-A"}
    assert client.post(URL, data, REMOTE_ADDR=SECRET_IP).status_code == 200
    assert client.post(URL, data, REMOTE_ADDR=SECRET_IP).status_code == 200
    blocked = client.post(URL, data, REMOTE_ADDR=SECRET_IP)
    assert blocked.status_code == 429
    assert "Please wait and try again." in _text(blocked)
    assert "result--" not in _text(blocked)
    assert TouristCheck.objects.count() == 2
    # Another address is not affected.
    assert client.post(URL, data, REMOTE_ADDR="198.51.100.5").status_code == 200


def test_rate_limit_ignores_spoofed_forwarded_for_behind_proxy(registry, settings) -> None:
    settings.TOURIST_THROTTLE = {"max_checks": 1, "window_seconds": 300}
    settings.CLIENT_IP_HEADER = "HTTP_X_FORWARDED_FOR"
    settings.TRUSTED_PROXY_HOPS = 1
    client = Client()
    data = {"licence": "SYN-NLG-90001-A"}
    first = client.post(URL, data, HTTP_X_FORWARDED_FOR=f"1.1.1.1, {SECRET_IP}")
    assert first.status_code == 200
    # A different client-supplied prefix does not give a fresh allowance.
    second = client.post(URL, data, HTTP_X_FORWARDED_FOR=f"2.2.2.2, {SECRET_IP}")
    assert second.status_code == 429
