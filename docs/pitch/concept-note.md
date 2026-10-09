# Verified Stays — Concept Note (DRAFT)

> **Draft status (M12, Stage 6).** Modules M8-M11 (officer queue, case and evidence screens, tourist check, Tamil strings, deployment preparation) are merged on `main` with CI green [V]. Nothing is deployed yet and the video is not recorded. `[SCREENSHOT: ...]` marks where an image goes once screenshots are taken. Every number below is copied from the repository's recorded results; nothing is estimated unless labelled.
> Labels: **[V]** verified (in this repository, or stated in the challenge brief where marked "from brief"), **[E]** estimated, **[A]** assumed. A full list is in section 10.
> **All data in this prototype is synthetic (fictional). No result in this note predicts real-world accuracy.**

Prepared for the Tamil Nadu Tourism Innovation Challenge 2026. Built by one developer.

---

## 1. Problem and evidence

- Tamil Nadu has a policy aim of registering every homestay and lodge [V from brief].
- District officers have been directed to cross-check listings on booking sites against the licence registry [V from brief: court direction]. The brief also mentions sealed homestays and reporting via WhatsApp [V from brief]. *[HUMAN: insert the exact citation/wording from the brief here; this draft does not restate details it cannot check (Q47).]*
- Matching a listing to a registry entry is hard to do by hand: listing titles are abbreviated, misspelled or reordered; one place has several names (Ooty / Udhagamandalam / உதகமண்டலம்); some details are written in Tamil; pincodes and coordinates are often missing or approximate [A: based on the synthetic noise model, `docs/synthetic-data-spec.md`; not measured on real listings].
- Existing tools found for this task target Western short-let ordinances; none was found for Indian addresses or Tamil text [V from brief; **not re-checked — Q8**].

No figures on the number of unregistered stays, officer time spent, or market size are given here: we have none that are verified.

## 2. Users and what changes for them

| User | Today [A] | With Verified Stays |
|---|---|---|
| District officer | Reads listings one by one and searches the registry by hand | Uploads a listings file and gets a ranked review queue with the reason for each position; decides each case and gets a printable evidence page |
| District / state admin | No shared record of who checked what | Uploads the registry; every upload, run and decision is kept in an append-only audit log in the database (no screen to read it yet; roadmap) |
| Tourist | Cannot easily tell whether a stay is in the registry | Checks a stay by licence number, or name + locality, in English or Tamil; gets a neutral answer |

## 3. Solution

Verified Stays is a web tool with two sides:

1. **Officer side.** Prioritises listings for human review by matching them to the licence registry. It never decides that a stay is unlicensed (section 5).
2. **Tourist side.** A public check that says whether a stay appears in the registry, using only public fields (name, locality, category, validity).

Officer-supplied data only: no scraping and no automated fetching of booking-site pages. A listing URL is stored as a reference string only.

`[SCREENSHOT: tourist check — "Found in the registry", Tamil interface]` `[SCREENSHOT: officer review queue]`

## 4. How it works

1. **Upload.** An officer uploads a listings CSV (platform, title, locality, optional pincode, coordinates and claimed licence number). The file is checked first: line-level errors, nothing saved until the officer confirms the preview; files are limited to 2 MB / 5,000 rows; the file's SHA-256 is audit-logged [V: M7]. An officer can only upload for their own district, enforced on the server [V: M6/M7 permission tests].
2. **Normalise.** Names and addresses are cleaned, abbreviations expanded, locality aliases resolved through a district-keyed gazetteer (Udhagamandalam → Ooty), Tamil script transliterated, pincodes extracted, and generic words (homestay, lodge, cottage...) removed before name comparison [V: M3].
3. **Find candidates.** Only registry entries in the same district that share a pincode or locality, or lie within 2 km, are compared; an exact licence-number hit is always a candidate [V: M4].
4. **Score and explain.** Each candidate gets a 0–1 score from six features — licence number, name similarity, address similarity, distance, pincode, category — and each feature value is stored so the officer can see why [V: M4; weights tuned on the dev set only in M5].
5. **Band and rank.** Each listing is placed in one band: *Matched*, *Needs review — high priority (licence details)*, *No match — needs review*, or *Needs review*. The queue puts licence mismatches first, then listings with no candidate, then ambiguous ones [V: M4].
6. **Decide.** On the case page the officer chooses: confirm match, reject match, mark suspected unlicensed (written reason required), or dismiss. Confirmed pairs are not flagged again on later runs [V: M4 engine tests]. The case screen is built [V: M8].
7. **Evidence and audit.** An evidence page shows the listing snapshot, candidates, scores, decision and a SHA-256 of the snapshot, and always says *"Supporting evidence for officer review, not a finding."* [V: M8]. Every state change writes an audit entry, stored append-only in the database; there is no screen for reading the audit log yet (roadmap) [V: M6, M8].

Matching is deterministic: same inputs and same parameter version give the same output; the version is stored on every run [V: M4 tests].

`[SCREENSHOT: case detail with feature breakdown]` `[SCREENSHOT: evidence page]`

## 5. Human-in-the-loop safeguards

- **The system never declares a stay unlicensed.** It only orders the review queue. Only an officer can record "suspected unlicensed", and the database refuses that decision without a written reason [V: DB check, M2].
- **Explainable scores.** Every score comes with its feature breakdown; no bare "confidence" percentage.
- **Neutral tourist wording.** "Not found" always carries: *"This does not mean the stay is illegal. The registry may be incomplete."* Tourist pages never show bands, scores or officer reasons; a stay in the registry is shown as "Found in the registry" [V: M9 tests].
- **Confirmed-pair memory** stops the same listing being re-flagged after an officer confirms it [V: M4 engine].
- **District scoping on the server** for every officer query; permission tests cover each data model [V: M6].
- **Append-only audit log** stored in the database: the application refuses updates and deletes, and PostgreSQL triggers block UPDATE, DELETE and TRUNCATE [V: code and tests; trigger tests run in CI on PostgreSQL]. There is no audit-log screen yet; reading it needs database access (roadmap).
- **Officer decisions are kept** as labelled data for future tuning (roadmap), not used to retrain anything automatically.

## 6. Privacy and ethics

- **Synthetic data only.** Every property name, licence number and address in the prototype is invented; locality names and pincodes are real places only; no owners, phone numbers or emails exist. Synthetic names are checked against a blocklist and spot-checked [V: M1; spot-check still needs a human pass]. Some invented names use ordinary words that are also brand names (e.g. Kingfisher, Orchid); whether to replace them is open (Q48).
- **Tourists:** a check stores only the result type and a timestamp. No address or identifier is stored in the database or logs; a short-lived in-memory counter (keyed by a hash of the address, per server process) limits repeated checks [V: M9, D88]. Login throttling keeps a keyed hash of the client address in a short-lived database cache, never the address itself, and backups leave that cache out [V: M6, D88].
- **Officers:** passwords hashed with argon2; idle sessions expire after 30 minutes; 5 failed logins throttle the account and address [V: M6].
- **Data protection (DPDP Act 2023):** obligations for a real-data pilot are **not yet reviewed by a lawyer** [A]. A retention rule must be agreed before any pilot (Q6).
- **No scraping** of booking platforms (platform terms) [A: legal position not reviewed].

## 7. Prototype status and evaluation on synthetic data

**Status [V, update before submission]:** matching engine, evaluation harness, accounts/roles/district scoping/audit log, listings/registry upload with matching runs, review queue, case and evidence screens, tourist check and Tamil interface strings (machine translation, unreviewed) are built, tested and merged on `main`; CI (including PostgreSQL) is green. Deployment is prepared but **nothing is deployed**: hosting accounts are pending. No audit-log screen exists. The video is not recorded.

**Data.** A seeded generator produces fictional registries and listings for 8 districts with known ground truth: a dev set (162 registry entries, 300 listings; used for tuning) and a test set (108 entries, 200 listings; different seed, fresh property names and different noise types; run once after tuning, never used for any choice) [V: M1, M5]. Listing types: clean, noisy, wrong or expired licence, no registry counterpart, and "hard negatives" (similar-looking but different stays).

**Results, parameter version `m5-tuned-1`** [V, synthetic only — `docs/testing-and-evaluation.md` §3.2, `docs/eval-test-run.json`]:

| Metric | Dev (300 listings) | Test (200 listings, single run) |
|---|---|---|
| Precision of "Matched" | 1.000 (165/165) | 1.000 (95/95) |
| Recall of true matches | 1.000 (165/165) | 0.864 (95/110) |
| No-counterpart listings reaching the review queue | 1.000 (54/54) | 1.000 (36/36) |
| Hard negatives not matched | 1.000 (45/45) | 1.000 (28/28) |
| Wrong/expired licence in the high-priority band | 1.000 (36/36) | 1.000 (26/26) |
| True entry ranked first among candidates | 1.000 (165/165) | 1.000 (110/110) |
| Share of listings sent to the review queue | 0.450 (135/300) | 0.525 (105/200) |

**How to read these numbers:**
- **They are synthetic.** They show the method behaves as designed on fictional data. They say **nothing** about accuracy on real listings.
- **Dev scoring 1.000 everywhere is a warning sign, not an achievement:** it shows the synthetic dev data is easy for this method. Dev was already at 1.000 before tuning, so dev numbers say little about robustness.
- **The test set is harder and still not independent:** it shares districts and the gazetteer with dev, and its Tamil-script noise is generated and read back with the same transliteration library, so that part is partly circular.
- On the test set, 15 of 110 true pairs were not auto-matched (mostly merged-word noise). All 15 went to the review queue with the true entry ranked first: the cost was extra officer work, not a wrong match [V].
- Half of all listings (0.525 on test) still go to human review. The tool reduces searching, not the need for officer judgement.

## 8. Limitations

- No real registry or real listings have been used; real data will be messier than the synthetic noise model [A].
- Tamil text (gazetteer aliases, transliteration fixes, interface strings) is machine-written and not yet reviewed by a native speaker (Q3, Q18).
- Coordinates on booking platforms are often approximate [A]; the distance feature may help less on real data.
- Listings whose true registry entry is in another district are not handled.
- The test set has now been used; any further parameter change can only be checked on the saturated dev set unless a fresh held-out set is generated (Q26).
- No host notification or appeal path yet; no 2FA; no screen for reading the audit log.
- Free hosting tiers may sleep when idle [A, Q9].
- Built and tested by one developer; no external security review.

## 9. Business model, scalability, roadmap and asks

**Business model [A — not validated, Q7]:** a tool for state or district tourism administrations, deployed per state with districts as the unit of rollout. **No buyer has been identified and no price is stated.**

**Scalability [A]:** the registry and listings are plain CSV contracts, so a real registry export can be plugged in without code changes; districts are independent units for scoping and matching runs; the stack is a single Docker image with PostgreSQL.

**Roadmap [A]:**
- **Phase 1:** confirm registry access; DPDP legal review; native-speaker Tamil review; 2FA; an admin screen for reading the audit log.
- **Phase 2:** pilot in one district with real data; WhatsApp intake via the official API; PDF evidence export; licensed geocoder.
- **Phase 3:** tune matching on real officer decisions; optional photo similarity; multi-district rollout.

**Asks:**
1. Access to the licence registry (or a sample export) for one district, in writing.
2. One pilot district and a named officer contact.
3. A legal review of data handling before any real data is loaded.
4. A native Tamil speaker to review interface text and place names.

## 10. What is verified, estimated, assumed

| Claim | Label | Source |
|---|---|---|
| Policy aim of full registration; court direction to cross-check booking sites; sealed homestays; WhatsApp reporting | [V from brief] | Challenge brief (exact wording to be inserted) |
| No existing tool for Indian addresses/Tamil | [V from brief; not re-checked] | Q8 — must be re-verified before submission |
| Real registry access | Unconfirmed | R1 |
| Matching pipeline, bands, determinism, district scoping, audit guards, upload checks | [V] | Code and automated tests in this repository (CI on PostgreSQL) |
| Evaluation numbers in section 7 | [V, synthetic only] | `docs/testing-and-evaluation.md` §3.2, `docs/eval-test-run.json` |
| Real-world accuracy | **Not claimed** | — |
| Nature of real listing noise; approximate platform coordinates | [A] | Synthetic noise model |
| DPDP obligations | [A] | Needs legal review |
| Business model, buyer, price | [A, unvalidated] | Q7; no price stated |
| Free-tier hosting limits | [A] | Q9 |
| Roadmap phases | [A] | `implementationsplan.md` §7 |
| Effort and timing of the roadmap | Not estimated | — |
