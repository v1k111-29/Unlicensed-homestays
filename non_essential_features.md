# Non-Essential Features ("Not Now" list) — Verified Stays

Nothing here is built for the demo. Each item has a reason and a revisit trigger. Move an item out of this file only via a decision in `docs/decisions.md`.

| Feature | Why not now | Revisit when |
|---|---|---|
| Scraping or platform APIs | Platform terms/legal risk [A]; not needed for the cross-check | Data-sharing agreement or legal clearance exists |
| Photo similarity | Extra effort and a second source of false positives | Real labelled data and legal clearance for images |
| WhatsApp intake (real) | Needs WhatsApp Business API approval; cannot be promised within the challenge build. A mock screen only | Pilot approved |
| Real registry integration | Access unconfirmed | Access confirmed in writing |
| Automatic "unlicensed" flag | Violates rule 1 (human decides) | Never without legal and policy sign-off |
| ML classifier / embeddings | No real labels; synthetic labels make evaluation circular | ≥ several hundred real officer decisions |
| Licensed geocoder / bulk geocoding | Free public geocoder policy prohibits bulk use [A] | Budget decision |
| 2FA | Out of build scope | Post-challenge Phase 1 |
| PDF evidence export | HTML print view is enough for the demo | Months 2–3 |
| Monitoring dashboard | Health check + uptime ping + Sentry suffice | Pilot |
| SMS / OTP | Cost and time | Pilot |
| Cross-district listings (listing whose true entry is in another district) | Out of Tier A scope; batch district = officer's district | Multi-district rollout |
| Multi-district admin hierarchy | Single-level scoping suffices | Multi-district rollout |
| Host notification / appeals workflow | Policy design needed with administration | Pilot |
| Payments / subscriptions | Business model unvalidated | After buyer validated |
| Native mobile app | Responsive web suffices | Demand evidence |
| Bulk tourist analytics | Privacy exposure, no need | Policy decision |
| Third language support | Out of scope | Request from stakeholders |

## Scope-creep rule
If a new idea appears during the build, add it here with a reason, then continue. Do not build it.
