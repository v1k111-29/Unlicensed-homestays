# Synthetic Data Specification

Purpose: create a reproducible registry + listings + ground truth for development, evaluation and demo. **Everything is fictional.** Locality names may be real; property names, licence numbers, owners and contacts must not correspond to real businesses or people.

## Sizes and districts [E]
8 districts (D18). Nilgiris is the demo district and is dense; the others are lighter.
| District | Registry entries |
|---|---|
| Nilgiris | ~60 |
| Coimbatore, Madurai, Dindigul, Kanyakumari, Thanjavur, Ramanathapuram, Chennai | ~30 each |
- Totals: registry ~300, listings ~500. Demo slice: ~25 listings in Nilgiris.
- Every registry entry and listing carries a `district`. Registry `lat/lng` are generated near locality centroids per district.

## Generation rules
- Seeded (`--seed`), deterministic. Dev and test sets use the **same districts**, with **different seeds, different noise templates and fresh property names for test** (D22).
- Hard negatives need density: same locality, same district, different property.
- Names from word lists; run a check that no generated name equals a known real business [A: manual spot-check].
- Licence numbers use an invented format (document it; do not mimic a real government format) [A].
- No phone numbers, emails or personal names for owners (omit the field).
- Gazetteer: hand-built, shared by dev and test, keyed by `(district, alias)`. The same alias may exist in two districts. Nilgiris: full English + Tamil aliases. Other districts: 2–3 localities with Tamil aliases, machine-generated and flagged "needs review" (D24). Locality names may be real; nothing else may be.

## Listing types (with ground truth label)
| Type | Description | Expected status |
|---|---|---|
| Clean match | Same name/address as registry | Matched |
| Noisy match | Typos, Tamil script, abbreviations, reordered tokens, dropped words | Matched or Needs review (never No match silently) |
| Wrong/expired licence | Claimed licence invalid or expired | Needs review (high) |
| No counterpart | No registry entry exists | Needs review / No match (must reach queue) |
| Hard negative | Same street/locality, different property | Not matched to the wrong entry |

## Noise templates
Dev: typos, abbreviation swaps, token reorder. Test (different): Tamil-script variants, dropped locality, alternative spellings, merged words.
**Limitation (state in the caveat):** dev and test share districts and gazetteer, so the test set is not fully independent.

## Outputs
`registry.csv`, `listings.csv`, `ground_truth.csv (listing_id, true_registry_id|null, type)`. Listing types are unchanged; there is no cross-district type (D20). In the generated files, `district` is filled for the registry and for each listing batch.

## Labelling in the product
UI banner: "Demonstration data — fictional." Concept note and video must say the same.
