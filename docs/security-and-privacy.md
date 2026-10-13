# Security and Privacy

> I am not a lawyer. DPDP Act 2023 points below are **[A]** and need legal review before any real-data pilot.

## 1. Roles and permissions
| Capability | Tourist (anon) | Officer | Admin |
|---|---|---|---|
| Tourist check | ✔ | ✔ | ✔ |
| Upload listings | ✘ | ✔ (own district) | ✔ |
| Run matching / decide cases | ✘ | ✔ (own district) | ✔ |
| Upload registry | ✘ | ✘ | ✔ |
| View audit log (`VIEW_AUDIT`) | ✘ | ✘ | ✔ (read-only screen `/admin/audit/`, D93) |
| Manage users (`MANAGE_USERS`) | ✘ | ✘ | ✔ (`/admin/accounts/`: create, disable/enable, reset password; all districts by design, D92) |
District scoping is enforced in a shared queryset helper and covered by permission tests. Account management is admin-wide by design (D92); officers get 403 and a `permission_denied` audit row on both admin screens.

## 2. Authentication and sessions
Django auth, argon2 hashing, secure/HttpOnly/SameSite cookies, CSRF on, login rate-limiting, session expiry. 2FA is on the roadmap.

## 3. Audit log
Events: login (success/fail), upload, registry upload, match run, decision, evidence generation, user changes (`user_created` from the command; `account.create`, `account.disable`, `account.enable`, `account.reset_password` from the admin screen, D92). Fields: actor, action, entity, entity_id, meta, timestamp. Append-only via DB trigger; no code path updates or deletes.

Reading (D93): admins read the log on `/admin/audit/` (newest first, 50 per page, filters: action, actor, entity, date range). The screen has no write control and writes no row on a plain read (a refused officer is still logged). Meta is shown shortened, with secret-looking keys hidden and addresses/e-mails/phones/credentials scrubbed; failed-login entity ids are HMACs and labelled "hashed".

Passwords (D92): accounts get a system-generated one-time password, shown once in the response to the admin's POST (`no-store`), never stored in clear, never in the session, a URL, a log or audit meta. There is no forced change at first sign-in and no self-service password change yet (Q50). Accounts are disabled, never deleted (audit rows name actors by text).

## 4. Privacy
- Demo uses synthetic data only.
- Tourist checks store result type + timestamp only; no IP/identifier.
- Tourist rate limit (D88, revises D75): counted in a per-process in-memory cache keyed by HMAC(SECRET_KEY, address). Neither the address nor its HMAC is written to any table, log or backup. Weaker guarantee: each Gunicorn worker counts separately (2 workers in `render.yaml` → up to 2 × 20 checks per address per 5 minutes) and a restart resets the counters.
- Login address throttle (D58/D65) keeps HMAC(SECRET_KEY, address) in the database cache table `django_cache` for at most 15 minutes. Backups exclude that table's rows (`pg_dump --exclude-table-data=django_cache`, D88), so no address HMAC reaches R2.
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

M11 (D82, D84): CSP `default-src 'none'` with same-origin scripts/styles/images/forms, `frame-ancestors 'none'`, Permissions-Policy, HTTPS redirect, HSTS one year; `ALLOWED_HOSTS` required outside DEBUG. Logs are JSON on stdout with addresses, e-mails, phone numbers and credentials scrubbed; Gunicorn access log off (no client addresses written by the app).

## 6. Backups and recovery
Nightly `pg_dump` via GitHub Actions to object storage [A]; one restore test before submission; document steps and time taken. M11 prepared it (`.github/workflows/backup.yml`, `scripts/restore-test.sh`, `docs/backup-restore.md`, D87); not configured and the restore test is not done (human step).

## 7. Incident basics
If real data is ever loaded: define who is notified, how access is revoked, and how the audit log is used. Not needed for the synthetic demo.
