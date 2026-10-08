# Progress Log

Append newest entries at the top. Each entry: module · done · partial · decisions · problems · next step · stage definition-of-done status.

## M1 — Synthetic data generator (done locally; not committed)
- Done: `data/synthetic/generator.py` (seeded, stdlib + `indic-transliteration`; dev seed 101, test seed 202, must differ); `gazetteer.csv` (30 localities, English + Tamil aliases, Tamil flagged `needs_review`); `localities.csv`; `realname_blocklist.txt`; outputs in `data/synthetic/out/{dev,test}` (`registry.csv`, `listings.csv`, `ground_truth.csv`; dev also `demo_listings.csv`), `name_spotcheck.csv`, `README_SYNTHETIC.txt` (fictional-data notice). `python tasks.py seed` wired. 31 new tests in `tests/test_synthetic_generator.py` (byte-identical reruns incl. different `PYTHONHASHSEED`, committed files equal fresh generation, schema, sizes, ground-truth consistency, noise templates per set, blocklist, fresh test names, no personal data, gazetteer).
- Sizes [V]: dev 162 registry / 300 listings; test 108 / 200; Nilgiris 60 registry across both sets; 8 districts. Listing types: clean, noisy, wrong_or_expired, no_counterpart, hard_negative. Dev noise: typo, abbreviation, reorder. Test noise: alt spelling, merged words, dropped locality, Tamil script.
- Verified [V]: `tasks.py lint` clean; `tasks.py test` 37 passed on Python 3.11.9; two `seed` runs give identical hashes.
- Fixed this session: ruff B023 closure-in-loop in the generator (now `_cycler`); added `README_SYNTHETIC.txt`.
- Decisions: D33-D38. No new dependencies.
- For M2: listings carry a synthetic-only `listing_id` column (D35); the loader must accept it.
- Partial / caveats: Tamil text is machine-generated, unreviewed (Q3). Blocklist is small; manual review of `name_spotcheck.csv` is still needed [A]. Dev and test share districts and gazetteer, so test is not fully independent (D22). Synthetic results say nothing about real-world accuracy.
- Problems: two sessions edited M1 files at the same time (merged by hand). `.gitattributes` was briefly overwritten and then restored to `* text=auto eol=lf`; docs files are CRLF in the working tree while git normalises to LF.
- Stage 1 definition of done: generator reproducible from a seed - MET. CI green - UNVERIFIED (M0 push; no `gh`). Schema migrated locally - UNMET (M2).
- Next: commit M1 (review `out/` and spotcheck first), then M2 (schema + loaders).

## M0 — Scaffold, tooling, CI (local checks done; pushed; CI result not yet confirmed)
- Done: `git init -b main`, `origin` set; `tasks.py` (stdlib) + thin `Makefile`; `pyproject.toml` (Python 3.11, ruff, pytest); pinned `requirements*.txt`; `.gitignore`, `.env.example`, `.dockerignore`; `Dockerfile` (unbuilt, Docker missing); `.github/workflows/ci.yml`; `src/` and `tests/` folders; 6 tests.
- Verified [V]: `tasks.py lint` and `test` pass on Python 3.11.9; `pip_audit` clean; `indic_transliteration` imports and transliterates Tamil on 3.11.9.
- Partial: CI never ran (nothing pushed). Eval gate and deploy steps deferred to M5 and M11. No Django project yet (M2).
- Decisions: D28–D32.
- Problems: no `gh`, Docker or PostgreSQL locally (Q13, Q14).
- Pushed by user: commit `4a73101` on `origin/main` [V via `git ls-remote`]. CI result unknown: no `gh`; GitHub API returned 404 anonymously.
- Next: user confirms CI green (Actions tab); then M1.

## Planning
- Planning documents created. No code yet.
- Next step: Module M0 (scaffold, tooling, CI).
