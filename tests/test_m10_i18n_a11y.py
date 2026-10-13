"""M10: English/Tamil, accessibility and empty/error states.

- Catalog: every translatable msgid in src/ has a Tamil msgstr ("no missing keys"), the
  committed .po/.mo are current, placeholders survive, Tamil is marked machine translation.
- Language: `/` is the tourist check (dashboard once signed in), English unprefixed, Tamil
  under `/ta/`, `/en/...` redirects, the header switch works without JavaScript or cookies.
- Tourist wording in Tamil: the disclaimer is pinned and no other tourist text uses a Tamil
  word for illegal / fake / unlicensed.
- Accessibility: static checks (tests/a11y_check.py) on every core screen in both languages,
  plus the error pages. No browser or screen reader involved (see docs/ui-and-accessibility.md).

All data synthetic; dev set only (AGENTS.md rules 3 and 9). No `transactional_db` (D65).
"""

from __future__ import annotations

import gettext
import logging
import re
from datetime import date
from pathlib import Path

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, RequestFactory
from django.utils import translation

from config import catalog
from tests import a11y_check

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "synthetic" / "out" / "dev"

DISCLAIMER_EN = "This does not mean the stay is illegal. The registry may be incomplete."
# Pinned: changing the Tamil disclaimer is a deliberate act (AGENTS.md §11, tourist wording).
# Meaning: "This does not mean that the stay is illegal. The registry may be incomplete."
DISCLAIMER_TA = "இதன் பொருள் அந்தத் தங்குமிடம் சட்டவிரோதமானது என்பதல்ல. பதிவேடு முழுமையற்றதாக இருக்கலாம்."
FORBIDDEN_EN = re.compile(r"\b(illegal|fake|unlicensed)\b", re.IGNORECASE)
# Tamil words/stems for illegal, fake/counterfeit, unlicensed/unauthorised (AGENTS.md rule 2).
# Only the mandated disclaimer may carry the "illegal" meaning in tourist text.
FORBIDDEN_TA = re.compile(
    r"சட்டவிரோத|சட்ட விரோத|சட்டத்துக்குப் புறம்பான|போலி|உரிமமற்ற|உரிமம் இல்லாத|உரிமம் பெறாத"
    r"|அனுமதியற்ற|அனுமதி இல்லாத|அங்கீகாரமற்ற|முறைகேடான|மோசடி"
)
TOURIST_SOURCES = (
    "templates/tourist/",
    "tourist/",
    "templates/base.html",
    "templates/404.html",
    "templates/403.html",
    "templates/500.html",
    "templates/403_csrf.html",
)
CORE_TEMPLATES = [
    "templates/base.html",
    "templates/tourist/check.html",
    "templates/tourist/_entry.html",
    "templates/registration/login.html",
    "templates/accounts/dashboard.html",
    "templates/reviews/queue.html",
    "templates/reviews/case.html",
    "templates/reviews/evidence.html",
    "templates/reviews/evidence_empty.html",
    "templates/ingest/upload.html",
    "templates/ingest/preview.html",
    "templates/matching/runs.html",
    "templates/matching/run_detail.html",
    "templates/audit/log.html",
    "templates/accounts/manage_list.html",
    "templates/accounts/manage_create.html",
    "templates/accounts/manage_password.html",
    "templates/403.html",
    "templates/404.html",
    "templates/500.html",
    "templates/403_csrf.html",
]


def u(lang: str, path: str) -> str:
    return path if lang == "en" else f"/{lang}{path}"


# ------------------------------------------------------------------ catalog (no DB)


@pytest.fixture(scope="module")
def built() -> tuple[str, bytes, list[catalog.Entry]]:
    return catalog.build("ta")


def test_no_missing_tamil_translations(built) -> None:
    _, _, entries = built
    assert len(entries) > 300
    missing = [e.msgid for e in entries if not e.translated]
    assert missing == []
    assert [e.msgid for e in entries if "fuzzy" in e.flags] == []  # fuzzy would be dropped


def test_committed_catalog_is_current(built) -> None:
    po, mo, _ = built
    path = catalog.po_path("ta")
    assert path.read_text(encoding="utf-8") == po, "run `python tasks.py messages`"
    assert path.with_suffix(".mo").read_bytes() == mo, "run `python tasks.py messages`"


def test_every_core_screen_template_is_extracted(built) -> None:
    _, _, entries = built
    refs = {ref for e in entries for ref in e.refs}
    assert [t for t in CORE_TEMPLATES if t not in refs] == []


def test_placeholders_survive_translation(built) -> None:
    _, _, entries = built
    bad = []
    for e in entries:
        sources = [e.msgid, e.msgid_plural or e.msgid]
        for i, text in enumerate(e.translations):
            expected = set(catalog.FORMAT_RE.findall(sources[min(i, 1)]))
            if set(catalog.FORMAT_RE.findall(text)) != expected:
                bad.append(e.msgid)
    assert bad == []


def test_mo_loads_and_translates(built) -> None:
    _, _, entries = built
    path = catalog.po_path("ta").with_suffix(".mo")
    with path.open("rb") as fh:
        trans = gettext.GNUTranslations(fh)
    assert trans.info()["plural-forms"] == "nplurals=2; plural=(n != 1);"
    for e in entries:
        if e.msgid_plural:
            assert trans.ngettext(e.msgid, e.msgid_plural, 1) == e.msgstr_plural[0]
            assert trans.ngettext(e.msgid, e.msgid_plural, 5) == e.msgstr_plural[1]
        elif e.msgctxt is None:
            assert trans.gettext(e.msgid) == e.msgstr


def test_tamil_marked_as_machine_translation() -> None:
    text = catalog.po_path("ta").read_text(encoding="utf-8")
    assert "MACHINE TRANSLATION - NEEDS REVIEW" in text
    assert "X-Review-Status: machine translation, needs review" in text


def test_tamil_disclaimer_is_pinned(built) -> None:
    _, _, entries = built
    (entry,) = [e for e in entries if e.msgid == DISCLAIMER_EN]
    assert entry.msgstr == DISCLAIMER_TA


def test_tamil_tourist_text_avoids_forbidden_words(built) -> None:
    _, _, entries = built
    tourist = [
        e
        for e in entries
        if e.msgid != DISCLAIMER_EN and any(r.startswith(TOURIST_SOURCES) for r in e.refs)
    ]
    assert len(tourist) > 40
    hits = [
        (e.msgid, t)
        for e in tourist
        for t in e.translations
        if FORBIDDEN_TA.search(t) or FORBIDDEN_EN.search(t)
    ]
    assert hits == []
    # The ban list really matches the disclaimer's own word, so it would catch a slip.
    assert FORBIDDEN_TA.search(DISCLAIMER_TA)


def test_po_round_trip_and_escapes() -> None:
    entries = [
        catalog.Entry('Say "hi"\\now', refs=["a.py"], msgstr='சொல் "வணக்கம்"\nவரி'),
        catalog.Entry("%(n)s row", "%(n)s rows", refs=["b.html"], msgstr_plural=["x", "y"]),
        catalog.Entry("Open", msgctxt="door", refs=["c.py"], msgstr="திற"),
    ]
    _, parsed = catalog.parse_po(catalog.write_po("ta", entries))
    assert [(p.msgid, p.msgid_plural, p.msgctxt, p.msgstr, p.msgstr_plural) for p in parsed] == [
        (e.msgid, e.msgid_plural, e.msgctxt, e.msgstr, e.msgstr_plural) for e in entries
    ]
    assert "python-format" in parsed[1].flags


def test_template_extraction_covers_tag_forms() -> None:
    text = (
        "{% load i18n %}{% translate 'One (1)' %}{% translate \"Two\" as two %}"
        "{% blocktranslate count n=x %}{{ n }} item{% plural %}{{ n }} items{% endblocktranslate %}"
        "{% translate 'Door' context 'verb' %}{{ v|default:_('Three') }}"
    )
    got = [catalog._entry_from_call(n, a) for n, a in catalog._template_calls(text, "t.html")]
    assert [(e.msgctxt, e.msgid, e.msgid_plural) for e in got] == [
        (None, "One (1)", None),
        (None, "Two", None),
        (None, "%(n)s item", "%(n)s items"),
        ("verb", "Door", None),
        (None, "Three", None),
    ]


GOOD_PAGE = """<!doctype html><html lang="en"><head><title>T</title></head><body>
<a class="skip-link" href="#main">Skip</a>
<header><nav class="site-nav lang-switch" aria-label="Language"><ul>
<li><a href="/x/" lang="en" hreflang="en" aria-current="true">English</a></li>
<li><a href="/ta/x/" lang="ta" hreflang="ta">தமிழ்</a></li></ul></nav></header>
<main id="main" tabindex="-1"><h1>Title</h1>
<form><label for="a">A</label><input id="a" name="a"><button type="submit">Go</button></form>
<table><caption>C</caption><tr><th scope="col">H</th></tr></table></main>
<footer><p>F</p></footer></body></html>"""


def test_a11y_checker_accepts_a_good_page() -> None:
    assert a11y_check.problems(GOOD_PAGE, "en") == []


@pytest.mark.parametrize(
    ("old", "new", "expected"),
    [
        ('<html lang="en">', '<html lang="ta">', "<html lang>"),
        ('<label for="a">A</label>', "", "has no label"),
        ("<caption>C</caption>", "", "<table> without caption"),
        ('<th scope="col">H</th>', "<th>H</th>", "without scope"),
        ("<h1>Title</h1>", "<h1>Title</h1><h3>Sub</h3>", "jumps from h1 to h3"),
        ("<h1>Title</h1>", "<h2>Title</h2>", "expected one <h1>"),
        ('<a class="skip-link" href="#main">Skip</a>', "", "skip link"),
        ('<button type="submit">Go</button>', '<button type="submit"></button>', "accessible"),
        ('<input id="a" name="a">', '<input id="a" name="a" style="width:10em">', "inline"),
        ('<input id="a" name="a">', '<input id="a" name="a" aria-invalid="true">', "invalid"),
        ('<input id="a" name="a">', '<input id="a" name="a" aria-describedby="nope">', "nope"),
        ('aria-current="true">English', ">English", "current language"),
        ('aria-label="Language"', "", "<nav> without aria-label"),
        ("<main", '<a href="/x" tabindex="2">x</a><main', "positive tabindex"),
    ],
)
def test_a11y_checker_catches_problems(old: str, new: str, expected: str) -> None:
    assert GOOD_PAGE.count(old) == 1
    found = a11y_check.problems(GOOD_PAGE.replace(old, new), "en")
    assert any(expected in p for p in found), found


# ------------------------------------------------------------------ pages (DB)

pytest_db = pytest.mark.django_db


def _untranslated(html: str, msgids: list[str]) -> list[str]:
    """English UI sentences left in a Tamil page: catalog msgids of three or more words with
    no placeholders that appear verbatim in the visible text."""
    text = a11y_check.visible_text(html)
    return [m for m in msgids if m in text]


@pytest.fixture(scope="module")
def english_sentences(built) -> list[str]:
    _, _, entries = built
    return [
        e.msgid
        for e in entries
        if len(e.msgid.split()) >= 3 and "%" not in e.msgid and e.msgid != e.msgstr
    ]


def _check_page(response, lang: str, english_sentences, switch: bool = True) -> str:
    html = response.content.decode()
    assert a11y_check.problems(html, lang, switch=switch) == [], response.request["PATH_INFO"]
    if lang == "ta":
        assert _untranslated(html, english_sentences) == [], response.request["PATH_INFO"]
    return html


@pytest.fixture
def registry(db) -> dict:
    from accounts.models import District
    from registry.models import RegistryEntry, UploadBatch

    nil = District.objects.get(name_en="Nilgiris")
    batch = UploadBatch.objects.create(
        type="registry", dataset="synthetic-dev", file_sha256="m10" * 21 + "a", row_count=3
    )

    def entry(licence, name, locality, **extra):
        values = {
            "category": "homestay",
            "valid_from": date(2024, 1, 1),
            "valid_to": date(2028, 12, 31),
            "status": "active",
        }
        values.update(extra)
        return RegistryEntry.objects.create(
            batch=batch, district=nil, licence_no=licence, name=name, locality=locality, **values
        )

    entry("SYN-NLG-91001-A", "Misty Fern Homestay", "Ooty")
    entry("SYN-NLG-91002-B", "Pine Shade Cottage", "Coonoor", valid_to=date(2025, 1, 1))
    entry("SYN-NLG-91003-C", "Silver Brook Lodge", "Kotagiri")
    entry("SYN-NLG-91004-D", "Silver Brook Lodge Annexe", "Kotagiri")
    return {"nil": nil}


OUTCOMES = [
    ({"name": "Misty Fern Homestay", "locality": "Ooty"}, "found"),
    ({"name": "Pine Shade Cottage", "locality": "Coonoor"}, "differs"),
    ({"name": "Silver Brook Lodge", "locality": "Kotagiri"}, "several"),
    ({"name": "Quiet Harbour Rooms", "locality": "Ooty"}, "not-found"),
]


@pytest_db
@pytest.mark.parametrize("lang", ["en", "ta"])
def test_home_page_is_the_tourist_check_for_visitors(lang, users) -> None:
    response = Client().get(u(lang, "/"))
    assert response.status_code == 302 and response["Location"] == u(lang, "/check/")
    client = Client()
    client.force_login(users["off_nil"])
    response = client.get(u(lang, "/"))
    assert response.status_code == 302 and response["Location"] == u(lang, "/dashboard/")


@pytest_db
def test_language_prefixes_and_lang_attribute(registry) -> None:
    assert '<html lang="en">' in Client().get("/check/").content.decode()
    tamil = Client().get("/ta/check/").content.decode()
    assert '<html lang="ta">' in tamil
    assert "தங்குமிடத்தைச் சரிபார்க்கவும்" in tamil and "Check a stay" not in tamil
    # Links inside a Tamil page stay Tamil (the URL carries the choice; no cookie needed).
    assert 'action="/ta/check/#result"' in tamil
    login = Client().get("/ta/login/").content.decode()
    assert 'action="/ta/login/"' in login


@pytest_db
def test_en_prefix_redirects_without_open_redirect() -> None:
    client = Client()
    assert client.get("/en/check/")["Location"] == "/check/"
    assert client.get("/en/officer/queue/?band=x")["Location"] == "/officer/queue/?band=x"
    assert client.get("/en/")["Location"] == "/"
    for evil in ("/en//evil.example/", "/en/\\evil.example/", "/en/%2F%2Fevil.example"):
        location = client.get(evil)["Location"]
        assert location.startswith("/") and not location.startswith(("//", "/\\")), location


@pytest_db
def test_language_switch_links(registry, users) -> None:
    html = Client().get("/ta/check/").content.decode()
    assert re.search(r'<a href="/check/" lang="en" hreflang="en">English</a>', html)
    assert re.search(r'<a href="/ta/check/" lang="ta" hreflang="ta" aria-current="true">', html)
    client = Client()
    client.force_login(users["off_nil"])
    html = client.get("/ta/officer/queue/?band=review_score&state=open").content.decode()
    assert 'href="/officer/queue/?band=review_score&amp;state=open" lang="en"' in html
    # 404 pages link to the start page of the other language.
    html = Client().get("/ta/no-such-page/").content.decode()
    assert 'href="/" lang="en"' in html


@pytest_db
@pytest.mark.parametrize("lang", ["en", "ta"])
def test_tourist_pages_accessible_and_cookie_free(lang, registry, english_sentences) -> None:
    client = Client()
    responses = [client.get(u(lang, "/check/"))]
    for data, css in OUTCOMES:
        response = client.post(u(lang, "/check/"), data)
        assert f"result--{css}" in response.content.decode()
        responses.append(response)
    responses.append(client.post(u(lang, "/check/"), {"name": "Misty Fern Homestay"}))
    responses.append(client.post(u(lang, "/check/"), {}))
    for response in responses:
        assert response.status_code == 200
        assert "Set-Cookie" not in response.headers
        _check_page(response, lang, english_sentences)
    assert not client.cookies


@pytest_db
@pytest.mark.parametrize("lang", ["en", "ta"])
def test_tourist_wording_is_neutral_in_both_languages(lang, registry) -> None:
    disclaimer = DISCLAIMER_EN if lang == "en" else DISCLAIMER_TA
    client = Client()
    pages = [client.get(u(lang, "/check/")).content.decode()]
    for data, css in OUTCOMES:
        html = client.post(u(lang, "/check/"), data).content.decode()
        if css == "not-found":
            assert f'<p class="disclaimer">{disclaimer}</p>' in html
        else:
            assert disclaimer not in html
        pages.append(html)
    pages.append(client.post(u(lang, "/check/"), {}).content.decode())
    for html in pages:
        text = html.replace(disclaimer, "")
        assert FORBIDDEN_EN.findall(text) == []
        assert FORBIDDEN_TA.findall(text) == []


@pytest_db
def test_tamil_district_choices_show_stored_tamil_name(registry) -> None:
    html = Client().get("/ta/check/").content.decode()
    nil = registry["nil"]
    if nil.name_ta:
        assert f"{nil.name_ta} ({nil.name_en})" in html
    assert "அனைத்து மாவட்டங்களும்" in html  # "All districts"


@pytest_db
@pytest.mark.parametrize("lang", ["en", "ta"])
def test_login_and_error_pages_accessible(lang, users, password, english_sentences) -> None:
    client = Client()
    _check_page(client.get(u(lang, "/login/")), lang, english_sentences)
    bad = client.post(u(lang, "/login/"), {"username": "officer_nil", "password": "wrong"})
    html = _check_page(bad, lang, english_sentences)
    assert 'aria-invalid="true"' in html and 'role="alert"' in html
    if lang == "ta":
        assert "சரியான" in html  # Django's login error, translated in our catalog
    missing = client.get(u(lang, "/no-such-page/"))
    assert missing.status_code == 404
    _check_page(missing, lang, english_sentences)
    officer = Client()
    officer.force_login(users["off_nil"])
    denied = officer.get(u(lang, "/admin/registry/"))
    assert denied.status_code == 403
    _check_page(denied, lang, english_sentences)
    expired = Client(enforce_csrf_checks=True).post(
        u(lang, "/login/"), {"username": "officer_nil", "password": password}
    )
    assert expired.status_code == 403
    html = _check_page(expired, lang, english_sentences, switch=False)
    assert ("The form has expired" in html) == (lang == "en")


@pytest.mark.parametrize("lang", ["en", "ta"])
def test_server_error_page(lang, caplog, english_sentences) -> None:
    from config.views import server_error

    request = RequestFactory().get(u(lang, "/check/"))
    with translation.override(lang), caplog.at_level(logging.ERROR, "verified_stays.errors"):
        response = server_error(request)
    assert response.status_code == 500
    html = response.content.decode()
    error_id = re.search(r'<span class="mono">([0-9a-f]{12})</span>', html).group(1)
    assert error_id in caplog.text
    assert f'href="{u(lang, "/check/")}"' in html  # retry link
    assert a11y_check.problems(html, lang, switch=False) == []
    if lang == "ta":
        assert _untranslated(html, english_sentences) == []


# ------------------------------------------------------------------ officer screens


@pytest.fixture
def dev_set(db) -> None:
    from ingest.load import load_synthetic_set

    load_synthetic_set(DEV, "synthetic-dev", "system:test")


@pytest_db
@pytest.mark.parametrize("lang", ["en", "ta"])
def test_officer_screens_accessible_with_states(lang, users, dev_set, english_sentences) -> None:
    from listings.models import Listing
    from matching.models import MatchResult, MatchRun
    from registry.models import UploadBatch

    client = Client()
    client.force_login(users["off_nil"])

    def page(path: str, status: int = 200, method: str = "get", **data) -> str:
        response = getattr(client, method)(u(lang, path), data or None)
        assert response.status_code == status, (path, response.status_code)
        return _check_page(response, lang, english_sentences)

    # Empty states before anything is uploaded.
    assert "empty-state" in page("/dashboard/")
    assert "empty-state" in page("/officer/queue/")
    assert "empty-state" in page("/officer/runs/")
    assert "empty-state" in page("/officer/uploads/")

    # Upload with line-level errors: nothing saved, errors in a captioned table.
    bad = SimpleUploadedFile("bad.csv", b"platform,title\nsynthetic,\n", "text/csv")
    html = page("/officer/uploads/", 400, "post", file=bad, dataset="synthetic-dev")
    assert 'role="alert"' in html and "errors-caption" in html

    # Valid upload -> preview -> confirm -> run.
    demo = SimpleUploadedFile("demo.csv", (DEV / "demo_listings.csv").read_bytes(), "text/csv")
    html = page("/officer/uploads/", 200, "post", file=demo, dataset="synthetic-dev")
    token = re.search(r'name="token" value="([^"]+)"', html).group(1)
    client.post(u(lang, "/officer/uploads/confirm/"), {"token": token})
    batch = UploadBatch.objects.get(source_name="demo.csv")
    page("/officer/runs/")
    client.post(u(lang, "/officer/runs/start/"), {"batch": batch.pk})
    run = MatchRun.objects.get(listing_batch=batch)

    page(f"/officer/runs/{run.pk}/")
    page("/dashboard/")
    html = page("/officer/queue/")
    assert "badge badge--" in html
    assert "empty-state" in page("/officer/queue/", locality="zzz-no-such-place")

    result = MatchResult.objects.filter(run=run).exclude(band="matched_licence").first()
    listing = Listing.objects.get(pk=result.listing_id)
    page(f"/officer/cases/{listing.pk}/")
    assert "empty-state" in page(f"/officer/cases/{listing.pk}/evidence/")
    # A refused decision (400) and a stale form (409) keep the page accessible, and the
    # language link points at the case page, not the POST-only decide URL.
    html = page(f"/officer/cases/{listing.pk}/decide/", 400, "post", run=run.pk, version=0)
    other = "en" if lang == "ta" else "ta"
    assert f'href="{u(other, f"/officer/cases/{listing.pk}/")}"' in html
    page(
        f"/officer/cases/{listing.pk}/decide/",
        409,
        "post",
        run=run.pk + 999,
        version=0,
        decision="dismiss",
    )
    response = client.post(u(lang, f"/officer/cases/{listing.pk}/evidence/"), follow=True)
    _check_page(response, lang, english_sentences)

    admin = Client()
    admin.force_login(users["admin"])
    _check_page(admin.get(u(lang, "/admin/registry/")), lang, english_sentences)
    _check_page(admin.get(u(lang, "/dashboard/")), lang, english_sentences)


# ------------------------------------------------------------------ admin screens (D92, D93)


@pytest_db
@pytest.mark.parametrize("lang", ["en", "ta"])
def test_admin_screens_accessible_with_states(lang, users, english_sentences) -> None:
    from audit.models import AuditLog

    admin = Client()
    admin.force_login(users["admin"])

    def page(path: str, status: int = 200, method: str = "get", **data) -> str:
        response = getattr(admin, method)(u(lang, path), data or None)
        assert response.status_code == status, (path, response.status_code)
        return _check_page(response, lang, english_sentences)

    # Audit log: rows, an empty filtered result and an invalid filter (error state).
    assert AuditLog.objects.exists()  # force_login wrote a login row
    assert "audit-caption" in page("/admin/audit/")
    assert "empty-state" in page("/admin/audit/", actor="zzz-nobody")
    html = page("/admin/audit/", 400, date_from="not-a-date")
    assert 'role="alert"' in html and 'aria-invalid="true"' in html

    # Accounts: list, create form, refused create (error state), created, reset.
    assert "accounts-caption" in page("/admin/accounts/")
    page("/admin/accounts/new/")
    html = page("/admin/accounts/new/", 400, "post", username="officer_NIL", role="officer")
    assert 'role="alert"' in html and 'aria-invalid="true"' in html
    page("/admin/accounts/new/", 200, "post", username=f"a11y_{lang}", role="admin")
    page(f"/admin/accounts/{users['off_nil'].pk}/reset-password/", 200, "post")
    # A disable refused for yourself comes back as an error message on the list.
    response = admin.post(u(lang, f"/admin/accounts/{users['admin'].pk}/disable/"), follow=True)
    html = _check_page(response, lang, english_sentences)
    assert "message-error" in html
