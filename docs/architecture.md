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
- `districts(id, name_en, name_ta)`
- `users(id, role[admin|officer], district_id, …)`
- `upload_batches(id, type[registry|listings], uploader_id, file_sha256, row_count, created_at)`
- `registry_entries(id, licence_no, name, address_en, address_ta, locality, pincode, lat, lng, category, valid_from, valid_to, status, batch_id, district_id)`
- `listings(id, source[officer_csv|tourist_report], platform, ref_url, title, locality_text, lat, lng, claimed_licence_no, raw jsonb, batch_id, district_id)`
- `match_runs(id, params_version, thresholds jsonb, created_by, created_at)`
- `match_candidates(id, run_id, listing_id, registry_id, score, features jsonb, rank)`
- `match_results(id, run_id, listing_id, status, top_registry_id, score, priority)`
- `reviews(id, listing_id, reviewer_id, decision, reason, created_at)`
- `confirmed_pairs(listing_id, registry_id)`
- `evidence_packs(id, listing_id, snapshot jsonb, sha256, generated_by, created_at)`
- `audit_log(id, actor, action, entity, entity_id, meta jsonb, ts)` — append-only (DB trigger blocks UPDATE/DELETE; restrict privileges where the host allows [A])

## 4. API outline
| Endpoint | Who | Purpose |
|---|---|---|
| `GET/POST /{lang}/check` | Public | Tourist check (rate-limited) |
| `POST /{lang}/report` | Public | Stretch: tourist report with consent |
| `GET/POST /login`, `/logout` | All | Session auth |
| `POST /officer/uploads` | Officer | Preview then confirm CSV |
| `POST /officer/runs` | Officer | Run matching on a batch |
| `GET /officer/queue` | Officer | Prioritised queue |
| `GET/POST /officer/cases/{id}` | Officer | Case detail + decision |
| `GET /officer/cases/{id}/evidence` | Officer | Evidence page |
| `POST /admin/registry` | Admin | Upload registry |
| `GET /admin/audit` | Admin | Audit log |
| `GET /healthz` | Monitor | Health |

## 5. Cross-cutting rules
- Every officer query is filtered by `district_id` in a shared queryset helper (never per-view ad hoc).
- Every state change calls `audit.log(...)`.
- Matching is deterministic and versioned (`params_version`).
- i18n via gettext; URL language prefix.

## 6. Folder structure
See `AGENTS.md` §6.
