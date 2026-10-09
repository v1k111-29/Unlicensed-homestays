# AGENTS.md — Instructions for AI coding agents and contributors

> Project: **Verified Stays** · Status: modules M0–M12 built and merged on `main` (CI green); nothing deployed yet (hosting, backup and demo accounts are pending human setup); video not recorded
> Labels used across all docs: **[V]** verified, **[E]** estimated, **[A]** assumed.

## 1. What this project is
A web tool that (a) helps Tamil Nadu district officers find listings that may be unlicensed homestays/lodges by matching listings to a licence registry, and (b) lets tourists check whether a stay appears in the registry. Built by one developer for the Tamil Nadu Tourism Innovation Challenge 2026. The build must be demo-ready before submission.

## 2. Read first
| File | Purpose |
|---|---|
| `implementationsplan.md` | Stage flow, definition of done per stage, cut order |
| `essentialfeatures.md` | MVP features and acceptance criteria |
| `non_essential_features.md` | Everything deliberately out of scope |
| `docs/decisions.md` | Decision log (chosen / rejected / why) |
| `docs/architecture.md` | Architecture, data model, API, folders |
| `docs/data-and-matching.md` | Pipeline, scoring, evaluation |
| `docs/security-and-privacy.md` | Roles, audit, privacy rules |
| `docs/open-questions.md` | Unresolved items — do not guess these |

## 3. Non-negotiable rules (hard constraints)
1. **The system never declares a stay "unlicensed".** It only prioritises listings for human review. Only an officer can set `suspected_unlicensed`, and a written reason is mandatory.
2. **Tourist-facing wording is neutral.** "Not found" must always carry: *"This does not mean the stay is illegal. The registry may be incomplete."* Never use the words "illegal", "fake" or "unlicensed" in tourist-facing text.
3. **Synthetic data only.** No real owner names, phone numbers, Aadhaar-like IDs, or real business names. Synthetic names must be checked so they do not match real businesses. Label synthetic data as synthetic in the UI and docs.
4. **No scraping** of booking platforms and no automated fetching of third-party listing pages. A URL may be stored as a reference string only.
5. **No tourist IP addresses or identifiers stored.** Tourist checks log result type + timestamp only.
6. **Audit log is append-only.** Never add code that updates or deletes `audit_log` rows.
7. **District scoping is enforced server-side** on every officer query. Never rely on the UI.
8. **Never commit secrets.** Use environment variables. `.env` is git-ignored.
9. **Do not tune thresholds on the test set.** Tune on dev; run the test set once at the end of tuning.
10. **Do not claim real-world accuracy** from synthetic results anywhere (code comments, docs, UI, video script).

## 4. Working agreement (how to behave)
- **Do not assume.** If a requirement, data field, or behaviour is unclear, check `docs/open-questions.md`; if it is not covered, ask the human before building.
- You may **agree or disagree** with any decision; state the reason. Do not flatter.
- **Record significant decisions** in `docs/decisions.md` (chosen / rejected / why). Skip trivial ones.
- **Label claims** as verified / estimated / assumed in docs.
- Prefer the smallest change that meets the acceptance criteria. Scope creep is the main delivery risk (solo developer).
- When behind, follow the **cut order** in `implementationsplan.md` rather than inventing a new one.
- Use parallel sub-agents only for independent tasks (e.g., writing tests vs. translating strings) and merge results through the human-reviewed branch.

## 5. Stack (see `docs/decisions.md` D4–D10 for rationale)
- Python 3.11 [V: local .venv], Django 5.2 LTS (pin `<6`: Django 6 needs Python 3.12+ [V]), PostgreSQL, server-rendered templates + HTMX, `rapidfuzz`, `indic-transliteration` [A], WhiteNoise, Gunicorn, Docker.
- Hosting (proposed, pending budget discussion): Render free web service + Neon free Postgres; backups to Cloudflare R2 [A]. **Verify free-tier limits at signup.**
- CI: GitHub Actions (ruff, pytest, pip-audit, gitleaks, eval gate, deploy on `main`).

## 6. Repository layout
```
verified-stays/
  AGENTS.md  README.md  implementationsplan.md  essentialfeatures.md  non_essential_features.md
  docs/                     # all other documentation
  data/synthetic/           # generator.py, seeds, ground_truth.csv (generated, reproducible)
  src/
    config/                 # settings, urls, wsgi
    accounts/ registry/ listings/ matching/ reviews/ audit/ tourist/
    ingest/                 # CSV parsing/validation + loaders (plain package, not an app)
    templates/ static/ locale/ta/
  tests/                    # unit, permissions, eval, smoke
  Dockerfile  .github/workflows/ (ci.yml, backup.yml)
```

## 7. Commands
> All commands below exist (M0–M10). DB targets need `DATABASE_URL` (in the shell or in the git-ignored `.env`, which `tasks.py` reads).
> `tasks.py` (stdlib only) is the single source of commands. The `Makefile` is a thin wrapper that delegates each target to `python tasks.py <target>`, for Linux CI and the Dockerfile. On Windows run `python tasks.py <target>` using `.venv\Scripts\python.exe`. `make` is not installed locally.
```
python tasks.py setup    # install deps into the EXISTING .venv (never create another)
python tasks.py run      # dev server
python tasks.py test     # pytest
python tasks.py lint     # ruff check + ruff format --check
python tasks.py eval     # run matching evaluation on dev set (prints metrics, applies CI floors)
                         # test set: single guarded run, already done (D56); never rerun
python tasks.py seed     # generate synthetic data (seeded, reproducible) [done in M1]
python tasks.py migrate  # apply migrations [M2]
python tasks.py load     # load committed M1 dev+test sets into the DB; checks row counts [M2]
python tasks.py messages # extract strings into src/locale/ta .po and compile .mo (pure Python) [M10]
                         # messages --check: fail on a stale catalog or a missing Tamil string
```
Every `make <target>` in other docs means `python tasks.py <target>`.

## 8. Code conventions
- Type hints on all non-trivial functions. Ruff for lint and format.
- Business logic in `matching/` and service modules, not in views.
- Every state-changing action writes an audit entry via `audit.log(actor, action, entity, entity_id, meta)`.
- All user-visible strings use Django `gettext` (`{% trans %}` / `_()`); never hard-code English or Tamil in templates or views.
- No fixed-width layouts (Tamil text is longer). Status is never conveyed by colour alone.
- Matching is deterministic: same inputs + same parameter version = same outputs. Store the parameter version on each `match_run`.

## 9. Testing requirements
- New logic ships with tests. Permission changes ship with a permission test.
- CI must pass: lint, unit, permissions, eval gate, `pip-audit`, `gitleaks`.
- See `docs/testing-and-evaluation.md`.

## 10. Definition of done (any task)
1. Acceptance criteria in `essentialfeatures.md` met.
2. Tests added/updated and passing; CI green.
3. Audit logging and district scoping verified where relevant.
4. Strings translatable; keyboard-operable; error/empty states present.
5. Docs updated if behaviour or a decision changed.

## 11. Ask the human before
- Adding any dependency not in section 5, or any paid service.
- Storing any new category of personal data.
- Changing the status bands, tourist wording, or role permissions.
- Anything touching real data, real platforms, or real people.
