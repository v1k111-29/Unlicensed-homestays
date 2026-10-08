"""M5 evaluation harness: metrics, gate, test-set guard, separation from the matcher.

No database. The committed TEST set is never read here: guard tests use a tiny set written
to ``tmp_path`` (AGENTS.md rule 9). Numbers are synthetic only (rule 10).
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

from evaluation import gate, harness
from evaluation import tune as tune_module
from evaluation.__main__ import main as cli_main
from evaluation.gate import FLOORS, check_gate
from evaluation.metrics import (
    WRONG_ENTRY,
    Ratio,
    Row,
    Truth,
    compute_metrics,
    confusion,
    gate_effects,
    join,
    read_truth,
    workload,
)
from matching.engine import Candidate, Outcome
from matching.params import CURRENT_VERSION, PARAMS

ROOT = Path(__file__).resolve().parents[1]
MATCHING = ROOT / "src" / "matching"


def _row(type_, band, true=None, top=None, cands=(), noise=(), reasons=()) -> Row:
    return Row(
        listing_id=f"L{id(object())}",
        type=type_,
        noise=tuple(noise),
        true_registry_id=true,
        band=band,
        reasons=tuple(reasons),
        top_registry_id=top,
        candidate_ids=tuple(cands),
    )


# ------------------------------------------------------------------ metrics


def test_ratio_formatting() -> None:
    assert Ratio(1, 4).value == 0.25
    assert str(Ratio(1, 4)) == "0.250 (1/4)"
    assert Ratio(0, 0).value is None
    assert str(Ratio(0, 0)) == "n/a (0/0)"


@pytest.fixture()
def tiny_rows() -> list[Row]:
    return [
        # clean, matched to its true entry
        _row("clean", "matched_score", "A", "A", ("A", "B")),
        # noisy, matched to the WRONG entry
        _row("noisy", "matched_score", "B", "C", ("C", "B"), noise=("typo",)),
        # noisy, sent to review; true entry is the best candidate
        _row("noisy", "review_score", "D", "D", ("D",), noise=("typo", "reorder")),
        # no counterpart, correctly in the queue
        _row("no_counterpart", "no_candidate"),
        # no counterpart, wrongly matched
        _row("no_counterpart", "matched_score", None, "E", ("E",)),
        # hard negative, not matched
        _row("hard_negative", "review_score", None, "F", ("F",), reasons=("name_differs",)),
        # wrong licence: one in the licence band, one not
        _row("wrong_or_expired", "review_licence", "G", "G", ("G",)),
        _row("wrong_or_expired", "review_score", "H", "X", ("X",)),  # true entry not blocked
    ]


def test_compute_metrics_on_hand_built_rows(tiny_rows) -> None:
    m = compute_metrics(tiny_rows)
    assert (m["matched_precision"].num, m["matched_precision"].den) == (1, 3)
    assert (m["match_recall"].num, m["match_recall"].den) == (1, 3)
    assert (m["no_counterpart_in_queue"].num, m["no_counterpart_in_queue"].den) == (1, 2)
    assert (m["hard_negative_not_matched"].num, m["hard_negative_not_matched"].den) == (1, 1)
    assert (m["wrong_licence_high_priority"].num, m["wrong_licence_high_priority"].den) == (1, 2)
    assert (m["positive_top_candidate"].num, m["positive_top_candidate"].den) == (2, 3)
    # rows with a true entry: A, B, D, G, H -> H's true entry was not a candidate
    assert (m["blocking_recall"].num, m["blocking_recall"].den) == (4, 5)
    assert (m["review_queue_share"].num, m["review_queue_share"].den) == (5, 8)


def test_metrics_on_empty_groups_are_not_computable() -> None:
    m = compute_metrics([_row("clean", "matched_licence", "A", "A", ("A",))])
    assert m["matched_precision"].value == 1.0
    assert m["no_counterpart_in_queue"].value is None
    assert m["hard_negative_not_matched"].value is None


def test_workload(tiny_rows) -> None:
    w = workload(tiny_rows)
    assert w == {
        "listings": 8,
        "queue": 5,
        "queue_true_counterpart": 1,
        "queue_other": 4,
        "matched": 3,
        "matched_wrong_entry": 2,
        "positive_no_candidate": 0,
    }


def test_confusion_by_type_and_noise(tiny_rows) -> None:
    c = confusion(tiny_rows)
    assert list(c) == [
        "clean",
        "noisy (all)",
        "noisy:reorder",
        "noisy:typo",
        "wrong_or_expired",
        "no_counterpart",
        "hard_negative",
    ]
    assert c["clean"] == {"matched_score": 1}
    assert c["noisy (all)"] == {WRONG_ENTRY: 1, "review_score": 1}
    assert c["noisy:typo"] == {WRONG_ENTRY: 1, "review_score": 1}
    assert c["noisy:reorder"] == {"review_score": 1}
    assert c["no_counterpart"] == {"no_candidate": 1, WRONG_ENTRY: 1}


def test_gate_effects(tiny_rows) -> None:
    effects = gate_effects(tiny_rows)
    assert effects["name_differs"] == {"hard_negative": 1}
    assert effects["several_similar"] == {}


def test_read_truth_and_join(tmp_path) -> None:
    path = tmp_path / "ground_truth.csv"
    path.write_text(
        "listing_id,true_registry_id,type,noise\nL1,R1,noisy,typo;reorder\nL2,,no_counterpart,\n",
        encoding="utf-8",
    )
    truth = read_truth(path)
    assert truth["L1"] == Truth("L1", "R1", "noisy", ("typo", "reorder"))
    assert truth["L2"].true_registry_id is None

    cand = Candidate("R1", "R1", 0.95, 1, ("pincode",), {})
    out = [
        Outcome("L1", "matched_score", ("score_above_t_high",), 0.95, "R1", (cand,)),
        Outcome("L2", "no_candidate", ("no_candidate_above_t_low",), None, None, ()),
    ]
    rows = join(out, truth)
    assert rows[0].matched_correctly and rows[1].in_queue
    with pytest.raises(ValueError, match="no outcome"):
        join(out[:1], truth)
    with pytest.raises(ValueError, match="no ground truth"):
        join(out, {"L1": truth["L1"]})


def test_read_truth_rejects_unknown_type(tmp_path) -> None:
    path = tmp_path / "ground_truth.csv"
    path.write_text("listing_id,true_registry_id,type,noise\nL1,,mystery,\n", encoding="utf-8")
    with pytest.raises(ValueError, match="unknown listing type"):
        read_truth(path)


# --------------------------------------------------------------------- gate


def test_gate_passes_at_and_above_floor() -> None:
    floors = {"m": 0.9}
    assert check_gate({"m": Ratio(9, 10)}, floors) == []
    assert check_gate({"m": Ratio(10, 10)}, floors) == []


def test_gate_fails_below_floor() -> None:
    (msg,) = check_gate({"m": Ratio(8, 10)}, {"m": 0.9})
    assert "below floor" in msg


def test_gate_fails_when_metric_missing_or_empty() -> None:
    assert len(check_gate({"m": Ratio(0, 0)}, {"m": 0.5})) == 1
    assert len(check_gate({}, {"m": 0.5})) == 1


def test_floors_cover_the_section3_metrics() -> None:
    assert FLOORS["matched_precision"] >= 0.98  # testing-and-evaluation.md §3 target
    assert FLOORS["no_counterpart_in_queue"] >= 0.95
    assert all(0 < v <= 1 for v in FLOORS.values())


def test_dev_gate_passes_with_current_params(capsys) -> None:
    assert harness.run_dev() == 0
    out = capsys.readouterr().out
    assert "Eval gate passed" in out
    assert "SYNTHETIC DATA ONLY" in out
    assert f"params {CURRENT_VERSION}" in out


def test_dev_gate_fails_when_a_floor_is_raised(monkeypatch, capsys) -> None:
    monkeypatch.setitem(gate.FLOORS, "review_queue_share", 0.99)  # dev is far below this
    assert harness.run_dev() == 1
    assert "EVAL GATE FAILED" in capsys.readouterr().out


def test_report_wording_is_neutral_and_caveated() -> None:
    text = harness.format_report(harness.evaluate("dev")).lower()
    assert "synthetic" in text and "do not predict real-world accuracy" in text
    for word in ("illegal", "fake", "unlicensed"):
        assert word not in text


# ---------------------------------------------------------- test-set guard


def _write_tiny_set(root: Path) -> Path:
    """A one-listing set in ``root/test``: lets the guard run without the real test set."""
    folder = root / "test"
    folder.mkdir(parents=True)
    (folder / "registry.csv").write_text(
        "licence_no,name,address_en,address_ta,locality,pincode,lat,lng,category,"
        "valid_from,valid_to,status,district\n"
        "SYN-NLG-00001-A,Teak Arbour Homestay,1 Lake Road Ooty,,Ooty,643001,11.41,76.695,"
        "homestay,2024-01-01,2030-01-01,active,Nilgiris\n",
        encoding="utf-8",
    )
    (folder / "listings.csv").write_text(
        "listing_id,platform,ref_url,title,locality_text,pincode,lat,lng,claimed_licence_no,"
        "notes,district\n"
        "T-1,direct,,Teak Arbour Homestay,Ooty,643001,11.41,76.695,,,Nilgiris\n",
        encoding="utf-8",
    )
    (folder / "ground_truth.csv").write_text(
        "listing_id,true_registry_id,type,noise\nT-1,SYN-NLG-00001-A,clean,\n", encoding="utf-8"
    )
    return root


def test_test_set_needs_explicit_flag(tmp_path) -> None:
    record = tmp_path / "record.json"
    with pytest.raises(harness.SetGuardError, match="--final-test-run"):
        harness.run_test_set(final=False, record=record, data_dir=_write_tiny_set(tmp_path))
    assert not record.exists()


def test_test_set_runs_once_then_refuses(tmp_path, capsys) -> None:
    record = tmp_path / "record.json"
    data = _write_tiny_set(tmp_path)
    assert harness.run_test_set(final=True, record=record, data_dir=data) == 0
    saved = json.loads(record.read_text(encoding="utf-8"))
    assert saved["synthetic"] is True and saved["set"] == "test"
    assert saved["params_version"] == CURRENT_VERSION
    assert saved["metrics"]["match_recall"] == {"num": 1, "den": 1, "value": 1.0}
    assert "real-world accuracy" in saved["caveat"]
    before = record.read_bytes()
    with pytest.raises(harness.SetGuardError, match="already run"):
        harness.run_test_set(final=True, record=record, data_dir=data)
    assert record.read_bytes() == before


def test_cli_refuses_test_set_without_flag(monkeypatch, capsys) -> None:
    called = []
    monkeypatch.setattr("evaluation.__main__.run_test_set", lambda **kw: called.append(kw))
    assert cli_main(["--set", "test", "--params", "m4-initial-1", "--final-test-run"]) == 2
    assert called == []

    def refuse(**kw):
        raise harness.SetGuardError("nope")

    monkeypatch.setattr("evaluation.__main__.run_test_set", refuse)
    assert cli_main(["--set", "test"]) == 3
    assert "REFUSED" in capsys.readouterr().out


def test_committed_test_run_record_blocks_reruns() -> None:
    """The single test-set run is recorded and committed; any further run is refused."""
    record = harness.TEST_RUN_RECORD
    assert record.exists(), "the single test-set run must be recorded (D56)"
    saved = json.loads(record.read_text(encoding="utf-8"))
    assert saved["synthetic"] is True
    assert saved["params_version"] in PARAMS
    with pytest.raises(harness.SetGuardError, match="already run"):
        harness.run_test_set(final=True)


# ------------------------------------------------- separation from the matcher


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    names |= {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    return names


@pytest.mark.parametrize("path", sorted(MATCHING.rglob("*.py")), ids=lambda p: p.name)
def test_matcher_never_imports_the_harness(path: Path) -> None:
    assert not any(m.split(".")[0] == "evaluation" for m in _imports(path))


def test_engine_import_does_not_load_the_harness() -> None:
    code = (
        "import sys; import matching.engine, matching.features, matching.records; "
        "sys.exit(any(m.split('.')[0] == 'evaluation' for m in sys.modules))"
    )
    assert subprocess.call([sys.executable, "-c", code], cwd=ROOT / "src") == 0


def test_tuning_module_reads_dev_only() -> None:
    assert tune_module.DEV.name == "dev"
    tree = ast.parse(Path(tune_module.__file__).read_text(encoding="utf-8"))
    doc_ids = {
        id(n.body[0].value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Module | ast.FunctionDef)
        and n.body
        and isinstance(n.body[0], ast.Expr)
        and isinstance(n.body[0].value, ast.Constant)
    }
    strings = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc_ids
    ]
    assert not [s for s in strings if "test" in s.lower()]
