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

## 4. Manual pre-submission checklist
- Fresh browser/incognito run of the full demo on the live URL.
- Tamil pages checked for wrapping and obvious translation errors.
- Backup restore performed once.
- No real data anywhere; synthetic banner visible.
