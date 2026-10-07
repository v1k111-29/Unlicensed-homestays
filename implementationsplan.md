# Implementation Plan — Verified Stays (Tier A)

**Approach:** build in ordered stages, one module at a time (M0–M12, see `docs/workflow-and-prompts.md` §5). A stage is done only when its definition of done is met. **Target:** demo-ready build + 90s video + concept note, all complete before submission.
Labels: **[V]** verified, **[E]** estimated, **[A]** assumed.

## 1. Effort buckets [E]
| Bucket | Share of effort |
|---|---|
| Build (code, deploy, foundations) | Largest |
| Concept note | Small |
| Video (script, record, edit) | Medium |
| Buffer + final checks | Small, reserved for slips |

## 2. Flow
| Stage | Modules | Work | Definition of done |
|---|---|---|---|
| **1. Foundation** | M0, M1, M2 | Repo, tooling, CI skeleton, decision log · Synthetic data generator with ground truth · Schema + loaders | CI green · generator reproducible from a seed · schema migrated locally |
| **2. Matching core** | M3, M4, M5 (part) | Normalisation, gazetteer, transliteration · Candidate generation + scoring · Eval harness + unit tests | `make eval` prints metrics · unit tests pass · dev baseline recorded |
| **3. Access + pipeline** | M5 (rest), M6, M7 | Threshold tuning on dev; single test-set run · Auth, roles, district scoping, audit log · Upload + run-matching endpoints | Officer can log in, upload, run, see results · audit entries written · permission tests pass |
| **4. Officer + tourist UI** | M8, M9 | Queue, case detail, decisions · Evidence page · Tourist check page | Full flow works locally on seeded data |
| **5. Polish + deploy** | M10, M11 | Tamil/English · Accessibility + empty/error states · Docker + deploy · Backup workflow + restore test · Sentry + uptime · Seed demo data | Live URL runs full demo · backup restored once |
| **6. Pitch** | M12 | Concept note · Video script · Record and edit video on a warm server | Note drafted with eval numbers + caveats · script timed to 90s · video exported |
| **7. Final checks** | — | Buffer for slips · Fresh-browser run, links, submission package | Everything ready to submit |

## 3. Checkpoints
- **After Stage 2:** matching works on synthetic dev data. If not, stop adding features and fix matching first.
- **After Stage 3 (go/no-go on scope):** if auth + upload + run are not working, apply the cut order below.
- **After Stage 5:** a live URL exists. After this, no new features; only fixes.

## 4. Cut order (apply in this order if behind)
1. Tamil limited to the tourist flow + navigation.
2. Evidence page reduced to a plain printable view.
3. Data reduced to Nilgiris + 2 other districts. Officer scoping stays (cheap, test-driven).
4. Sentry dropped.
5. Tourist reporting (T3) stays cut.
If still behind after step 5: drop to **Tier B** (matching core + clickable UI on seeded data; auth/audit/CI documented, not built) and move effort to the pitch.

## 5. Working rules
- One branch per module; merge to `main` only with green CI.
- Log significant decisions in `docs/decisions.md` when made.
- No new features after Stage 5.
- Do not tune on the test set; run it once.

## 6. First three tasks (Stage 1)
1. **Repo, tooling, CI (M0):** scaffold folders, ruff + pytest + Dockerfile, green CI on an empty test, copy decisions into `docs/decisions.md`.
2. **Synthetic data generator (M1):** seeded generator → registry, listings, ground truth; noise types per `docs/synthetic-data-spec.md`; ~20-locality gazetteer with English + Tamil aliases; separate dev/test seeds.
3. **Schema + loaders (M2):** Django models/migrations for core tables; CSV loaders.

## 7. Post-challenge roadmap [A]
- **Phase 1:** confirm registry access; DPDP legal review; native-speaker Tamil review; 2FA.
- **Phase 2:** pilot in one district with real data; WhatsApp intake via the official API; PDF evidence; licensed geocoder.
- **Phase 3:** tune matching on officer decisions; optional photo similarity; multi-district rollout.

## 8. Items needing your input (see `docs/open-questions.md`)
Budget/hosting confirmation · video logistics · Tamil reviewer · licence for the repo · final choice of demo district.
