"""Tests for the M1 synthetic data generator (data/synthetic/generator.py)."""

import csv
import math
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from data.synthetic import generator as gen

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "data" / "synthetic" / "out"
FILES = [
    "dev/registry.csv",
    "dev/listings.csv",
    "dev/ground_truth.csv",
    "dev/demo_listings.csv",
    "test/registry.csv",
    "test/listings.csv",
    "test/ground_truth.csv",
    "name_spotcheck.csv",
    "README_SYNTHETIC.txt",
]
LICENCE_RE = re.compile(r"^SYN-([A-Z]{3})-(\d{5})-([A-Z])$")


def _read(path: Path) -> list[dict[str, str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _header(path: Path) -> list[str]:
    with open(path, encoding="utf-8", newline="") as fh:
        return next(csv.reader(fh))


def _km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat = (lat2 - lat1) * 111.0
    dlng = (lng2 - lng1) * 111.0 * math.cos(math.radians(lat1))
    return math.hypot(dlat, dlng)


@pytest.fixture(scope="module")
def out(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("synthetic")
    gen.generate(path)
    return path


@pytest.fixture(scope="module")
def data(out) -> dict[str, dict[str, list[dict[str, str]]]]:
    return {
        s: {
            "registry": _read(out / s / "registry.csv"),
            "listings": _read(out / s / "listings.csv"),
            "truth": _read(out / s / "ground_truth.csv"),
        }
        for s in ("dev", "test")
    }


# ---------------------------------------------------------------- determinism


def test_same_seed_gives_byte_identical_files(out, tmp_path) -> None:
    gen.generate(tmp_path)
    for name in FILES:
        assert (out / name).read_bytes() == (tmp_path / name).read_bytes(), name


def test_identical_under_different_hash_seed(out, tmp_path) -> None:
    env = {**os.environ, "PYTHONHASHSEED": "12345", "PYTHONIOENCODING": "utf-8"}
    script = ROOT / "data" / "synthetic" / "generator.py"
    subprocess.run(
        [sys.executable, str(script), "--out", str(tmp_path)], check=True, env=env, cwd=ROOT
    )
    for name in FILES:
        assert (out / name).read_bytes() == (tmp_path / name).read_bytes(), name


def test_committed_files_match_fresh_generation(out) -> None:
    for name in FILES:
        assert (COMMITTED / name).read_bytes() == (out / name).read_bytes(), (
            f"{name} is stale: run `python tasks.py seed` and commit the result"
        )


def test_different_seed_gives_different_output(out, tmp_path) -> None:
    gen.generate(tmp_path, dev_seed=7, test_seed=8)
    assert (out / "dev/listings.csv").read_bytes() != (tmp_path / "dev/listings.csv").read_bytes()


def test_dev_and_test_seeds_must_differ(tmp_path) -> None:
    with pytest.raises(ValueError):
        gen.generate(tmp_path, dev_seed=5, test_seed=5)


def test_files_are_lf_without_bom(out) -> None:
    for name in FILES:
        raw = (out / name).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        assert b"\r" not in raw


# ---------------------------------------------------------------- schema and sizes


def test_headers_match_schema(out) -> None:
    for s in ("dev", "test"):
        assert _header(out / s / "registry.csv") == gen.REGISTRY_COLUMNS
        assert _header(out / s / "listings.csv") == gen.LISTING_COLUMNS
        assert _header(out / s / "ground_truth.csv") == [
            "listing_id",
            "true_registry_id",
            "type",
            "noise",
        ]
    assert (
        gen.REGISTRY_COLUMNS
        == (
            "licence_no name address_en address_ta locality pincode lat lng category "
            "valid_from valid_to status district"
        ).split()
    )
    assert (
        gen.LISTING_COLUMNS[1:]
        == (
            "platform ref_url title locality_text pincode lat lng claimed_licence_no notes district"
        ).split()
    )


def test_sizes_and_district_density(data) -> None:
    reg = data["dev"]["registry"] + data["test"]["registry"]
    lst = data["dev"]["listings"] + data["test"]["listings"]
    assert 250 <= len(reg) <= 320
    assert 450 <= len(lst) <= 550
    per_district = {d: sum(1 for r in reg if r["district"] == d) for d in gen.DISTRICTS}
    assert 55 <= per_district["Nilgiris"] <= 65
    for d in gen.DISTRICTS[1:]:
        assert 25 <= per_district[d] <= 35, d
    assert {r["district"] for r in lst} == set(gen.DISTRICTS)
    assert all(r["district"] for r in reg + lst)


def test_required_fields_present(data) -> None:
    for s in ("dev", "test"):
        for r in data[s]["registry"]:
            assert all(r[k] for k in ("licence_no", "name", "locality", "district", "valid_to"))
        for r in data[s]["listings"]:
            assert all(r[k] for k in ("platform", "title", "locality_text", "district"))


def test_registry_dates_and_status(data) -> None:
    ref = gen.REFERENCE_DATE.isoformat()
    for s in ("dev", "test"):
        statuses = set()
        for r in data[s]["registry"]:
            statuses.add(r["status"])
            assert r["valid_from"] < r["valid_to"]
            assert (r["valid_to"] < ref) == (r["status"] == "expired")
        assert statuses == {"active", "expired", "suspended"}


def test_demo_slice(out, data) -> None:
    demo = _read(out / "dev" / "demo_listings.csv")
    assert 20 <= len(demo) <= 30
    assert all(r["district"] == "Nilgiris" for r in demo)
    dev_ids = {r["listing_id"]: r for r in data["dev"]["listings"]}
    assert all(dev_ids[r["listing_id"]] == r for r in demo)
    types = {t["listing_id"]: t["type"] for t in data["dev"]["truth"]}
    assert {types[r["listing_id"]] for r in demo} == set(gen.LISTING_TYPES)


# ---------------------------------------------------------------- licences


def test_licence_numbers_unique_and_well_formed(data) -> None:
    for s in ("dev", "test"):
        numbers = [r["licence_no"] for r in data[s]["registry"]]
        assert len(numbers) == len(set(numbers))
        for r in data[s]["registry"]:
            m = LICENCE_RE.match(r["licence_no"])
            assert m, r["licence_no"]
            assert m.group(1) == gen.DISTRICT_CODES[r["district"]]
            assert m.group(3) == gen.check_letter(m.group(1), m.group(2))


def test_malformed_licence_fails_check_letter() -> None:
    bad = gen.make_licence("NLG", 1234, valid=False)
    m = LICENCE_RE.match(bad)
    assert m and m.group(3) != gen.check_letter("NLG", "01234")


# ---------------------------------------------------------------- ground truth and types


def test_ground_truth_consistency(data) -> None:
    for s in ("dev", "test"):
        reg = {r["licence_no"]: r for r in data[s]["registry"]}
        listings = {r["listing_id"]: r for r in data[s]["listings"]}
        truth = data[s]["truth"]
        assert [t["listing_id"] for t in truth] == list(listings)
        for t in truth:
            assert t["type"] in gen.LISTING_TYPES
            if t["type"] in ("no_counterpart", "hard_negative"):
                assert t["true_registry_id"] == ""
            else:
                entry = reg[t["true_registry_id"]]
                assert entry["district"] == listings[t["listing_id"]]["district"]
        assert {t["type"] for t in truth} == set(gen.LISTING_TYPES)
        assert "cross_district" not in {t["type"] for t in truth}


def test_type_shares(data) -> None:
    for s in ("dev", "test"):
        truth = data[s]["truth"]
        for ltype, share in gen.TYPE_SHARES.items():
            n = sum(1 for t in truth if t["type"] == ltype)
            assert abs(n / len(truth) - share) < 0.03, (s, ltype)


def test_clean_matches_are_exact(data) -> None:
    for s in ("dev", "test"):
        reg = {r["licence_no"]: r for r in data[s]["registry"]}
        listings = {r["listing_id"]: r for r in data[s]["listings"]}
        for t in data[s]["truth"]:
            if t["type"] == "clean":
                entry, lst = reg[t["true_registry_id"]], listings[t["listing_id"]]
                assert lst["title"] == entry["name"]
                assert lst["locality_text"] == entry["locality"]
                assert t["noise"] == ""


def test_wrong_or_expired_licences(data) -> None:
    for s in ("dev", "test"):
        reg = {r["licence_no"]: r for r in data[s]["registry"]}
        listings = {r["listing_id"]: r for r in data[s]["listings"]}
        for t in data[s]["truth"]:
            if t["type"] != "wrong_or_expired":
                continue
            claimed = listings[t["listing_id"]]["claimed_licence_no"]
            assert claimed
            if claimed == t["true_registry_id"]:
                assert reg[claimed]["status"] != "active"
            else:
                assert reg[t["true_registry_id"]]["status"] == "active"


def test_correct_claimed_licences_only_for_own_entry(data) -> None:
    for s in ("dev", "test"):
        listings = {r["listing_id"]: r for r in data[s]["listings"]}
        for t in data[s]["truth"]:
            claimed = listings[t["listing_id"]]["claimed_licence_no"]
            if t["type"] in ("clean", "noisy"):
                assert claimed in ("", t["true_registry_id"])
            if t["type"] in ("no_counterpart", "hard_negative"):
                assert claimed == ""


def test_hard_negatives_share_locality_and_a_name_token(data) -> None:
    for s in ("dev", "test"):
        reg = data[s]["registry"]
        listings = {r["listing_id"]: r for r in data[s]["listings"]}
        names = {r["name"] for r in reg}
        for t in data[s]["truth"]:
            if t["type"] != "hard_negative":
                continue
            lst = listings[t["listing_id"]]
            assert lst["title"] not in names
            tokens = set(gen.name_core_tokens(lst["title"]))
            siblings = [
                r
                for r in reg
                if r["district"] == lst["district"]
                and tokens & set(gen.name_core_tokens(r["name"]))
            ]
            assert siblings
            if lst["lat"]:
                lat, lng = float(lst["lat"]), float(lst["lng"])
                assert any(
                    _km(float(r["lat"]), float(r["lng"]), lat, lng) <= 0.35 for r in siblings
                )


def test_unmatched_names_not_in_registry(data) -> None:
    for s in ("dev", "test"):
        cores = {tuple(gen.name_core_tokens(r["name"])) for r in data[s]["registry"]}
        listings = {r["listing_id"]: r for r in data[s]["listings"]}
        for t in data[s]["truth"]:
            if t["type"] in ("no_counterpart", "hard_negative"):
                title = listings[t["listing_id"]]["title"]
                assert tuple(gen.name_core_tokens(title)) not in cores


def test_test_names_are_fresh(data) -> None:
    def cores(s: str) -> set[tuple[str, ...]]:
        names = [r["name"] for r in data[s]["registry"]]
        names += [
            r["title"]
            for r, t in zip(data[s]["listings"], data[s]["truth"], strict=True)
            if t["type"] in ("no_counterpart", "hard_negative")
        ]
        return {tuple(gen.name_core_tokens(n)) for n in names}

    assert not cores("dev") & cores("test")


# ---------------------------------------------------------------- noise


def test_noise_templates_per_set(data) -> None:
    for s, allowed in gen.NOISE_BY_SET.items():
        counts = dict.fromkeys(allowed, 0)
        for t in data[s]["truth"]:
            applied = [n for n in t["noise"].split(";") if n]
            if t["type"] == "noisy":
                assert 1 <= len(applied) <= 2
            else:
                assert applied == []
            for n in applied:
                assert n in allowed, (s, n)
                counts[n] += 1
        assert all(c >= 5 for c in counts.values()), (s, counts)


def test_noisy_titles_differ_from_registry(data) -> None:
    for s in ("dev", "test"):
        reg = {r["licence_no"]: r for r in data[s]["registry"]}
        listings = {r["listing_id"]: r for r in data[s]["listings"]}
        for t in data[s]["truth"]:
            if t["type"] == "noisy":
                lst = listings[t["listing_id"]]
                entry = reg[t["true_registry_id"]]
                assert (lst["title"], lst["locality_text"]) != (entry["name"], entry["locality"])


def test_tamil_noise_uses_tamil_script(data) -> None:
    listings = {r["listing_id"]: r for r in data["test"]["listings"]}
    for t in data["test"]["truth"]:
        if "tamil" in t["noise"]:
            assert re.search(r"[஀-௿]", listings[t["listing_id"]]["title"])
    for r in data["dev"]["listings"]:
        assert not re.search(r"[஀-௿]", r["title"] + r["locality_text"])


def test_alt_spellings_are_not_gazetteer_aliases() -> None:
    aliases = {row["alias"] for row in gen.load_gazetteer()}
    assert not set(gen.LOCALITY_ALT_SPELLINGS.values()) & aliases


# ---------------------------------------------------------------- privacy and real names


def test_no_personal_data_columns_or_numbers(out) -> None:
    banned = {"owner", "phone", "email", "mobile", "aadhaar", "contact"}
    for name in FILES:
        text = (out / name).read_text(encoding="utf-8")
        header = text.splitlines()[0].lower()
        assert not any(b in header for b in banned), name
        # Phone numbers (10 digits) and Aadhaar-like IDs (12 digits) would show as long runs.
        assert not re.search(r"\d{10,}", text), name
        assert "@" not in text, name


def test_ref_urls_use_reserved_example_domain(data) -> None:
    for s in ("dev", "test"):
        for r in data[s]["listings"]:
            assert re.match(r"^https://[a-z-]+\.example/", r["ref_url"]), r["ref_url"]
            assert r["platform"] in {"platform_a", "platform_b", "direct"}


def test_no_generated_name_matches_blocklist(out) -> None:
    blocklist = gen.load_blocklist()
    names = [r["name"] for r in _read(out / "name_spotcheck.csv")]
    assert names
    assert not [n for n in names if gen.is_blocked(n, blocklist)]


def test_blocklist_check_catches_real_names() -> None:
    blocklist = gen.load_blocklist()
    assert gen.is_blocked("Savoy Cottage", blocklist)
    assert gen.is_blocked("Green Valley Homestay", blocklist)
    assert gen.is_blocked("Fern Hill Lodge", blocklist)
    assert gen.is_blocked("Westin Grove Cottage", blocklist)  # D90 brand additions
    assert gen.is_blocked("Hilton Homestay", blocklist)
    assert not gen.is_blocked("Cedar Nook Homestay", blocklist)


# ---------------------------------------------------------------- geography and gazetteer


def test_coordinates_near_locality_centroid(data) -> None:
    centroids = {(loc.district, loc.name): loc for loc in gen.load_localities()}
    for s in ("dev", "test"):
        for r in data[s]["registry"]:
            loc = centroids[(r["district"], r["locality"])]
            assert r["pincode"] == loc.pincode
            assert _km(loc.lat, loc.lng, float(r["lat"]), float(r["lng"])) <= 1.6
        district_locs = {}
        for loc in centroids.values():
            district_locs.setdefault(loc.district, []).append(loc)
        for r in data[s]["listings"]:
            if r["lat"]:
                lat, lng = float(r["lat"]), float(r["lng"])
                assert min(_km(c.lat, c.lng, lat, lng) for c in district_locs[r["district"]]) < 2


def test_gazetteer_structure() -> None:
    rows = gen.load_gazetteer()
    keys = [(r["district"], r["alias"]) for r in rows]
    assert len(keys) == len(set(keys))
    localities = gen.load_localities()
    known = {(loc.district, loc.name) for loc in localities}
    for r in rows:
        assert (r["district"], r["locality"]) in known
        assert r["script"] in {"latin", "tamil"}
        assert (r["needs_review"] == "1") == (r["script"] == "tamil")
        if r["script"] == "tamil":
            assert re.search(r"[஀-௿]", r["alias"])
    tamil = {(r["district"], r["locality"]) for r in rows if r["script"] == "tamil"}
    nilgiris = [loc for loc in localities if loc.district == "Nilgiris"]
    assert all(("Nilgiris", loc.name) in tamil for loc in nilgiris)
    for d in gen.DISTRICTS[1:]:
        assert 2 <= sum(1 for k in tamil if k[0] == d) <= 3, d
    assert {loc.district for loc in localities} == set(gen.DISTRICTS)
