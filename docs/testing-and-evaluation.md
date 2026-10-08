# Testing and Evaluation

## 1. Test layers
| Layer | Examples | Gate |
|---|---|---|
| Unit | normalisation, transliteration, scoring, status bands | CI |
| Permission | district scoping, role access, anonymous access | CI |
| Audit | every state change writes an entry; update/delete blocked | CI |
| Integration/smoke | upload → run → queue → decide → evidence | CI |
| i18n | pages render in `en` and `ta`; no missing keys on core screens | CI |
| Accessibility | automated checks where cheap + manual keyboard/screen-reader pass | Manual, Stage 5 |
| Eval | matching metrics on synthetic set | CI floor |

## 2. CI pipeline
ruff → pytest → eval gate → pip-audit → gitleaks → deploy (main only).

## 3. Matching evaluation
- **Sets:** dev (tuning), test (different seed + noise templates; run once after tuning).
- **Metrics:** precision of *Matched*; recall of true matches; share of no-counterpart listings that reach the review queue; confusion matrix by noise type.
- **Targets [A — my goals, not results]:** Matched precision ≥ 0.98; ≥ 0.95 of no-counterpart listings reach the queue.
- **Floors in CI [A]:** set slightly below the dev baseline once recorded at end of Stage 2.
- **Reporting:** report dev and test separately. State the synthetic-data caveat wherever numbers appear.

### 3.1 Implementation (M5; D55, D56)
- `python tasks.py eval` → `python -m evaluation` (from `src`): DEV set, DB-free, prints headline metrics, review workload, confusion matrix (listing type / noise template × band; a "Matched" listing on the wrong entry is its own column), extra-gate counts (Q21) and the synthetic caveat; exits 1 if a floor in `src/evaluation/gate.py` is missed. Options: `--no-gate`, `--params <version>` (dev only). CI runs `make eval`.
- Ground truth is read only by `src/evaluation/`; `src/matching` never imports it (tests).
- Tuning aid: `python -m evaluation.tune` (from `src`), DEV only: score margins + threshold grid.
- **Test-set guard:** `tasks.py eval --set test` is refused without `--final-test-run`. The single run writes `docs/eval-test-run.json` (committed); while that file exists every further test run is refused. Do not delete it to rerun; a rerun needs a new decision and a fresh held-out set (Q26).
- **Floors [A, set from the dev baseline with margin]:** Matched precision 0.98, recall of true matches 0.95, no-counterpart in queue 0.95, hard negatives not matched 0.95, wrong licence in high-priority band 0.95, blocking recall 0.98.

### 3.2 Results, params `m5-tuned-1` [V, SYNTHETIC ONLY — not a real-world accuracy claim]
| Metric | Dev (300 listings) | Test (200, single run) |
|---|---|---|
| Matched precision | 1.000 (165/165) | 1.000 (95/95) |
| Recall of true matches | 1.000 (165/165) | 0.864 (95/110) |
| No-counterpart listings reaching the queue | 1.000 (54/54) | 1.000 (36/36) |
| Hard negatives not matched | 1.000 (45/45) | 1.000 (28/28) |
| Wrong/expired licence in high-priority band | 1.000 (36/36) | 1.000 (26/26) |
| True entry is top candidate | 1.000 (165/165) | 1.000 (110/110) |
| Blocking recall | 1.000 (201/201) | 1.000 (136/136) |
| Review queue share | 0.450 (135/300) | 0.525 (105/200) |

The test set was run once, after tuning, and never used for any choice. The 15 test true pairs not matched all reach the review queue with the true entry ranked first. Dev was already saturated before tuning, so dev numbers say little about robustness; test shares districts and gazetteer with dev (D22), and its Tamil-script noise is partly circular (D37). These results show the method behaves as designed on fictional data; they do not predict real-world accuracy.

## 4. Manual pre-submission checklist
- Fresh browser/incognito run of the full demo on the live URL.
- Tamil pages checked for wrapping and obvious translation errors.
- Backup restore performed once.
- No real data anywhere; synthetic banner visible.
