# Data and Matching Pipeline

Labels: **[V]** verified, **[E]** estimated, **[A]** assumed. All numeric weights/thresholds below are **starting values [A]**, to be tuned on the dev set only.

## 1. Data schemas
**Registry CSV** (admin upload): `licence_no, name, address_en, address_ta, locality, pincode, lat, lng, category, valid_from, valid_to, status, district`
**Listings CSV** (officer upload): `platform, ref_url, title, locality_text, pincode, lat, lng, claimed_licence_no, notes, district (optional)`
Required: registry → `licence_no, name, locality, district, valid_to`; listings → `platform, title, locality_text`. Listing `district`: defaults to the uploading officer's district for the whole batch; the column is optional for officers and **required for admin uploads** (D19). An officer batch with a `district` that differs from their own is rejected. Missing optional fields are allowed.
Real platforms often obscure exact coordinates; treat `lat/lng` as approximate [A].

## 2. Sources
| Source | MVP? | Risk |
|---|---|---|
| Synthetic registry CSV | Yes | None (synthetic) |
| Officer-uploaded listings CSV | Yes | Officer must have the right to use the data [A] |
| Tourist report | Stretch | Consent, abuse/spam |
| Public listings scraping | No | Platform terms, legal |
| WhatsApp helpline reports | Mock only | Approval, privacy |
| Real registry feed | No | Access unconfirmed [V from brief] |

## 3. Ingestion
Validate schema → reject bad rows with line-level errors (all-or-nothing) → hash rows for dedupe → keep raw row in `raw jsonb` → record batch SHA-256 → audit-log.

## 4. Normalisation
1. Unicode NFC, lowercase, strip punctuation.
2. Expand abbreviations (rd, st, nagar, etc.).
3. Resolve locality aliases through the gazetteer first (e.g., Udhagamandalam ↔ Ooty). Lookup key is `(district, alias)`; never resolve an alias across districts.
4. Transliterate remaining Tamil script to Latin [A: quality for place names is imperfect].
5. Extract pincode.
6. Remove generic words (homestay, villa, cottage, resort, inn) before name comparison.

## 5. Candidate generation
Same district AND (same pincode OR same locality OR within 2 km [A]). An exact licence-number hit is always a candidate. The district rule also applies near district borders; cross-district listings are not handled (D20).

## 6. Scoring (explainable, 0–1)
| Feature | Initial weight [A] |
|---|---|
| Licence number (exact / expired / absent) | 0.30 |
| Name similarity (rapidfuzz token-set) | 0.25 |
| Address-token similarity | 0.20 |
| Distance decay | 0.15 |
| Pincode match | 0.05 |
| Category compatibility | 0.05 |
Feature values are stored in `match_candidates.features`. Thresholds `T_low`, `T_high` are set on the dev set; record them in `match_runs.thresholds`.

## 7. Status bands
| Condition | Status |
|---|---|
| Claimed licence valid; name and locality consistent | **Matched** (auto, audit-logged) |
| Score ≥ T_high, no licence claimed | **Matched** (optional review) |
| Claimed licence missing, expired or inconsistent | **Needs review — high priority** |
| T_low ≤ score < T_high | **Needs review** |
| No candidate ≥ T_low | **No match — needs review** |
Queue priority: licence mismatch → no candidate → ambiguous; ties by lower score first.

## 8. Human review and evidence
Side-by-side listing vs top-3 candidates with feature breakdown. Decisions per `essentialfeatures.md` O4. Evidence page per O5. Confirmed pairs are suppressed from future flags.

## 9. False-positive handling
1. System never says "unlicensed"; only an officer sets `suspected_unlicensed` with a reason.
2. Confirmed-pair memory.
3. Neutral tourist wording.
4. Officer rejections stored as labelled data for future tuning.
5. Roadmap: host notification and appeal path.

## 10. Evaluation
See `testing-and-evaluation.md` §3 and `synthetic-data-spec.md`.
**Caveat (must appear in the concept note and video):** results on synthetic data show the method works; they do not predict real-world accuracy. Dev and test sets share districts and gazetteer, so test is not fully independent (D22).
