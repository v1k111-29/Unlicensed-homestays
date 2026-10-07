# Architecture — Verified Stays

## 1. Overview
```
Tourist (anonymous) ─┐                      ┌─ PostgreSQL (Neon free) [A]
Officer / Admin ─────┼─► Web app (Docker: Django + Gunicorn + WhiteNoise)
                     │          ├─ tourist/    public check (rate-limited)
                     │          ├─ listings/ registry/ reviews/
                     │          ├─ matching/   normalise → candidates → score
                     │          └─ audit/      append-only writer
                     │          └─► Sentry (errors)
GitHub Actions: lint → tests → eval gate → deploy; nightly pg_dump → object storage [A]
Uptime monitor → /healthz
```

## 2. Stack and rationale
| Layer | Choice | Rejected | Reason |
|---|---|---|---|
| Language/framework | Python + Django 5 | FastAPI; Next.js | Batteries included for a solo build |
| DB | PostgreSQL | SQLite | Concurrency, JSONB, trigger-based audit immutability |
| Frontend | Templates + HTMX | React SPA | Fewer moving parts; accessible by default |
| Matching libs | rapidfuzz, indic-transliteration [A] | Embeddings | Explainability, no labels |
| Static files | WhiteNoise | Separate CDN | Simplicity |
| CI | GitHub Actions | — | Free for this use [A] |

## 3. Data model
- `districts(id, name_en, name_ta)` — 8 rows seeded by migration (D18); Tamil names need review (Q3)
- `users(id, role[admin|officer], district_id, …)` — custom `accounts.User`; DB check: officer must have a district
- `upload_batches(id, type[registry|listings], uploader_id, district_id, dataset, source_name, file_sha256, row_count, created_at)` — `dataset` labels synthetic sets (D40); unique (type, dataset, file_sha256)
- `registry_entries(id, licence_no, name, address_en, address_ta, locality, pincode, lat, lng, category, valid_from, valid_to, status, batch_id, district_id)` — unique (batch, licence_no)
- `listings(id, source[officer_csv|tourist_report], external_id, platform, ref_url, title, locality_text, pincode, lat, lng, claimed_licence_no, raw jsonb, batch_id, district_id)` — `external_id` = file row id (synthetic `listing_id`, D35)
- `match_runs(id, district_id, params_version, thresholds jsonb, created_by, created_at)` — one district per run (D51)
- `match_candidates(id, run_id, listing_id, registry_id, score, features jsonb, rank)`
- `match_results(id, run_id, listing_id, status, top_registry_id, score, priority)`
- `reviews(id, listing_id, reviewer_id, decision, reason, created_at)` — DB check: `suspected_unlicensed` needs a non-empty reason
- `confirmed_pairs(listing_id, registry_id)`
- `evidence_packs(id, listing_id, snapshot jsonb, sha256, generated_by, created_at)`
- `ground_truth(listing_id, true_registry_id, type, noise)` — synthetic eval labels only; never read by the matcher (D35, D40)
- `audit_log(id, actor, action, entity, entity_id, meta jsonb, ts)` — append-only (DB triggers block UPDATE/DELETE/TRUNCATE, D53; model refuses update/delete; `actor` is text; restrict privileges where the host allows [A]) (D42)

Implemented in M2 (Django models + migrations under `src/<app>/`). Names above are logical; Django table names are `<app>_<model>` (e.g. `registry_registryentry`), except `audit_log`. CSV parsing and loading live in `src/ingest/` (D41).

## 4. API outline
| Endpoint | Who | Purpose |
|---|---|---|
| `GET/POST /{lang}/check` | Public | Tourist check (rate-limited) |
| `POST /{lang}/report` | Public | Stretch: tourist report with consent |
| `GET/POST /login/`, `POST /logout/` | All | Session auth (M6; logout is POST-only, failed logins throttled, D46-D47) |
| `GET /dashboard/` | Officer, Admin | Signed-in landing page (M6 placeholder; M8 fills it) |
| `POST /officer/uploads` | Officer | Preview then confirm CSV |
| `POST /officer/runs` | Officer | Run matching on a batch |
| `GET /officer/queue` | Officer | Prioritised queue |
| `GET/POST /officer/cases/{id}` | Officer | Case detail + decision |
| `GET /officer/cases/{id}/evidence` | Officer | Evidence page |
| `POST /admin/registry` | Admin | Upload registry |
| `GET /admin/audit` | Admin | Audit log |
| `GET /healthz` | Monitor | Health |

## 5. Cross-cutting rules
- Every officer query is filtered by `district_id` in a shared queryset helper (never per-view ad hoc): `accounts.scoping.scoped()` / `get_scoped_or_404()`; writes naming a district use `can_act_in_district()` (D48).
- Every view is guarded by a capability: `accounts.permissions.require_capability` / `CapabilityRequiredMixin` (D45).
- Every state change calls `audit.log(...)`.
- Matching is deterministic and versioned (`params_version`).
- i18n via gettext; URL language prefix.

## 6. Folder structure
See `AGENTS.md` §6.
