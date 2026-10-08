# Security and Privacy

> I am not a lawyer. DPDP Act 2023 points below are **[A]** and need legal review before any real-data pilot.

## 1. Roles and permissions
| Capability | Tourist (anon) | Officer | Admin |
|---|---|---|---|
| Tourist check | ✔ | ✔ | ✔ |
| Upload listings | ✘ | ✔ (own district) | ✔ |
| Run matching / decide cases | ✘ | ✔ (own district) | ✔ |
| Upload registry | ✘ | ✘ | ✔ |
| View audit log | ✘ | ✘ | ✔ |
| Manage users | ✘ | ✘ | ✔ |
District scoping is enforced in a shared queryset helper and covered by permission tests.

## 2. Authentication and sessions
Django auth, argon2 hashing, secure/HttpOnly/SameSite cookies, CSRF on, login rate-limiting, session expiry. 2FA is on the roadmap.

## 3. Audit log
Events: login (success/fail), upload, registry upload, match run, decision, evidence generation, user changes. Fields: actor, action, entity, entity_id, meta, timestamp. Append-only via DB trigger; no code path updates or deletes.

## 4. Privacy
- Demo uses synthetic data only.
- Tourist checks store result type + timestamp only; no IP/identifier.
- Public fields only on tourist results (name, locality, category, validity).
- Short purpose notice on the tourist and report pages.
- Retention rule (to document before any pilot): [TBD — see open questions].
- Tourist reports (stretch): consent checkbox, minimal fields, no personal data required.

## 5. Application security
- Security headers (CSP, X-Content-Type-Options, frame protections).
- Input validation on CSV (size limit, encoding, column checks); no formulas executed.
- Rate limits on public endpoints.
- Dependency scanning (`pip-audit`), secret scanning (`gitleaks`).
- Secrets only via environment variables.

M11 (D78, D80): CSP `default-src 'none'` with same-origin scripts/styles/images/forms, `frame-ancestors 'none'`, Permissions-Policy, HTTPS redirect, HSTS one year; `ALLOWED_HOSTS` required outside DEBUG. Logs are JSON on stdout with addresses, e-mails, phone numbers and credentials scrubbed; Gunicorn access log off (no client addresses written by the app).

## 6. Backups and recovery
Nightly `pg_dump` via GitHub Actions to object storage [A]; one restore test before submission; document steps and time taken. M11 prepared it (`.github/workflows/backup.yml`, `scripts/restore-test.sh`, `docs/backup-restore.md`, D83); not configured and the restore test is not done (human step).

## 7. Incident basics
If real data is ever loaded: define who is notified, how access is revoked, and how the audit log is used. Not needed for the synthetic demo.
