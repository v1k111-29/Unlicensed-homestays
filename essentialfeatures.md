# Essential Features (MVP) — Verified Stays

Everything here must work end-to-end in the demo build, except where marked *stretch* or *cut-order*. Priority: **P0** = demo cannot run without it; **P1** = required for "production-quality foundations".

## Officer
### O1. Log in, see only my district — P0
- Valid credentials → dashboard.
- Officer for District X never sees District Y data (automated test).
- 5 failed logins → account/IP rate-limited.
### O2. Upload a listings CSV — P0
- Valid file → row count + preview, then confirm.
- Invalid file → line-level errors (English/Tamil); nothing saved.
- Upload audit-logged with file SHA-256.
- Batch district = officer's district unless a `district` column is given (required for admin uploads).
- Officer batch naming a different district: rejected whole, line-level error, audit-logged. Admin may name any district.
### O3. Run matching, get a ranked review queue — P0
- Each listing gets status: **Matched / Needs review / No match**.
- Queue sorted by priority (licence mismatch → no candidate → ambiguous; ties: lower score first).
- Each item shows score and feature breakdown.
### O4. Decide on a case — P0
- Options: Confirm match · Reject match · Mark suspected-unlicensed (reason required) · Dismiss.
- Decision stores who/when; audit-logged.
- Confirmed pairs are not re-flagged on later runs.
### O5. Evidence page — P0 (cut-order item 2: may be reduced to a plain printable view)
- Shows listing snapshot, candidate registry entries, scores, decision, SHA-256 of snapshot.
- Always carries: *"Supporting evidence for officer review, not a finding."*
### O6. Admin: upload registry, view audit log — P1
- Registry upload follows the same validation as O2.
- Audit log read-only, filterable by user and date.

## Tourist
### T1. Check a stay — P0
- Input: licence number, or name + locality (English or Tamil). Optional district dropdown, default all.
- Four outcomes: **Matched · Details differ or expired · Several similar (add licence number or district) · Not found**.
- "Not found" always shows the neutral disclaimer.
- Only public fields shown: name, locality, category, validity. Never owner name/phone.
- Rate-limited; no IP/identifier stored.
### T2. Language switch (English/Tamil) — P0 for tourist flow
- Toggle on every page; choice persists; URL prefix `/en/` `/ta/`.

## Foundations (P1 unless noted)
| ID | Foundation | Acceptance |
|---|---|---|
| F1 | Synthetic data + ground truth (P0) | Reproducible from seed; dev and test sets use different seeds and noise templates |
| F2 | Matching evaluation (P0) | `make eval` reports metrics; CI gate fails below floor |
| F3 | Roles and permissions | admin / officer roles; district scoping; permission tests |
| F4 | Audit log | Append-only (DB trigger); entries for login, upload, run, decision, evidence, registry upload |
| F5 | CI/CD | ruff, pytest, pip-audit, gitleaks, eval gate; auto-deploy on `main` |
| F6 | Backups | Nightly dump to object storage; one restore test performed and documented |
| F7 | Observability | `/healthz`, structured logs with request IDs, uptime ping; Sentry (cut-order item 4) |
| F8 | Privacy basics | Purpose notice, data minimisation, retention rule documented, synthetic-only banner |
| F9 | Accessibility basics | Keyboard operable, labelled fields, AA contrast, 44px targets |
| F10 | Empty/error states | Defined for every screen (see `docs/ui-and-accessibility.md`) |
| F11 | Deployment | Dockerised; live URL; warm-up procedure for demo |

## Stretch (only if buffer allows)
- **T3. Tourist report** with consent notice → enters officer queue with source "tourist report".
