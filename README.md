# Verified Stays

Helps Tamil Nadu district administrations prioritise possibly unlicensed homestays and lodges for human review, and lets tourists check whether a stay appears in the licence registry. English and Tamil.

**Status:** prototype for the Tamil Nadu Tourism Innovation Challenge 2026. Runs on **synthetic data only**. Results on synthetic data demonstrate the method, not real-world accuracy.

## What it does
- **Officer:** upload listings CSV → run matching → review a prioritised queue → record a decision → print an evidence page.
- **Tourist:** enter a licence number or name + locality → get one of four neutral outcomes.
- **Admin:** upload the registry, read the audit log (read-only), manage officer and admin accounts.

## What it does not do
It never declares a stay unlicensed. It does not scrape booking platforms. It does not use real personal data. See `non_essential_features.md`.

## Documentation map
See `AGENTS.md` §2. Start with `implementationsplan.md`.

## Quick start (Windows)
Needs Python 3.11 in the repo `.venv` and a reachable PostgreSQL (local install or a free Neon database; `start.bat` prints the steps if none is found).
```
start.bat
```
It creates a local `.env`, migrates, loads the synthetic data once, creates local demo accounts (passwords in the git-ignored `.dev-accounts.txt`), starts the server and opens `http://127.0.0.1:8000/`. There is no separate client: the app is server-rendered. Hosting for the demo (free tiers): `docs/deploy-runbook.md`.

## Licence and data notice
Licence: **TBD** (see `docs/open-questions.md`). All data in this repository is synthetic and fictional.
