# Progress Log

Append newest entries at the top. Each entry: module · done · partial · decisions · problems · next step · stage definition-of-done status.

## M2 — Schema + loaders (done locally; DB tests verified on SQLite only, PostgreSQL run pending)
- Done: Django 5.2 project `src/config` (settings from env; `DATABASE_URL` parsed with stdlib, `config/dburl.py`; argon2 hasher; `settings_test.py` for pytest). Apps `accounts` (District, custom User), `registry` (UploadBatch, RegistryEntry), `listings` (Listing), `matching` (MatchRun, MatchCandidate, MatchResult, GroundTruth), `reviews` (Review, ConfirmedPair, EvidencePack), `audit` (AuditLog + `audit.log()`). Migrations incl. 8-district seed and PostgreSQL append-only trigger on `audit_log`. `src/ingest/` parsers (pure, line-level errors) + loader (all-or-nothing, audit-logged). Command `load_synthetic` (`python tasks.py load`) loads dev + test and compares row counts with the CSVs. `tasks.py`: `migrate`, `run`, `load` implemented; reads `.env`. CI: Postgres 16 service, `REQUIRE_DB=1`, plus `make migrate` and `make load` steps. Dockerfile CMD now gunicorn (still unbuilt).
- Tests: 97 total. Without a DB: 83 passed, 14 skipped (skips say why). Against a throwaway SQLite settings module (scratch, not committed): 95 passed, 2 skipped (PostgreSQL trigger tests); `load_synthetic` printed OK for all six counts: dev 162/300/300, test 108/200/200 [V on SQLite]. `tasks.py lint` clean; `pip_audit -r requirements.txt` no known vulnerabilities [V].
- Partial: nothing has run on PostgreSQL yet (none installed here). The trigger SQL and the Postgres-specific paths are unverified until CI or a local install runs them [A]. CI result unknown until pushed.
- Decisions: D39 (native PostgreSQL via `DATABASE_URL`, Docker not required), D40 (dev+test in one DB, `dataset` label), D41 (ingest rules), D42 (audit two-layer guard), D43 (full §3 schema + custom user now), D44 (`.env` reading, `load` target). No new dependencies.
- Open questions added: Q15 (matching scope per dataset), Q16 (unknown CSV columns), Q17 (registry re-upload semantics). Q13 answered.
- Problems: `makemigrations --check` needs DB access, so the missing-migrations test uses the autodetector directly. `docs/progress.md` M1 entry still says "not committed"; M1 is commit `4db3f18`.
- How to set up PostgreSQL on Windows (native, no Docker):
  1. Download the PostgreSQL 16 or 17 Windows installer (EDB) from postgresql.org/download/windows and run it. Keep port 5432; set a password for the `postgres` superuser; Stack Builder is not needed.
  2. Open "SQL Shell (psql)" from the Start menu, log in as `postgres`, then run: `CREATE ROLE verified_stays LOGIN PASSWORD '<choose one>' CREATEDB;` and `CREATE DATABASE verified_stays OWNER verified_stays;` (`CREATEDB` lets pytest create its test database).
  3. Copy `.env.example` to `.env` and set `DATABASE_URL=postgres://verified_stays:<password>@localhost:5432/verified_stays` and `DJANGO_DEBUG=1`. Percent-encode special characters in the password.
  4. Run `.venv\Scripts\python.exe tasks.py migrate`, then `tasks.py load` (expect six "OK" lines), then `tasks.py test` (expect 0 skipped).
- Stage 1 definition of done: generator reproducible from a seed - MET. Schema migrated locally - UNMET until PostgreSQL is installed (migrations verified on SQLite only). CI green - UNVERIFIED (not pushed). Not at risk of a cut-order item; it needs the local install or a CI run.
- Next: human installs PostgreSQL (steps above) or pushes `m2-schema-loaders` to see CI run the DB tests; then M3 (normalisation + gazetteer).

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
