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

## Implementation (M1)
Generator: `data/synthetic/generator.py`, run with `python tasks.py seed` (defaults: dev seed 101, test seed 202). Same seeds give byte-identical files [V: tests].
| File | Content |
|---|---|
| `data/synthetic/localities.csv` | Hand-built: district, locality, pincode, centroid (real places; pincodes and centroids approximate [A]) |
| `data/synthetic/gazetteer.csv` | Hand-built, keyed by `(district, alias)`; `script` latin/tamil; every Tamil alias has `needs_review=1` |
| `data/synthetic/realname_blocklist.txt` | Small list of real business names and common generic names; generated names may not contain them |
| `out/{dev,test}/registry.csv`, `listings.csv`, `ground_truth.csv` | Generated sets (D36) |
| `out/dev/demo_listings.csv` | 25-listing Nilgiris demo slice (subset of dev, all five types) |
| `out/name_spotcheck.csv` | Every generated property name, for manual review against real businesses |
| `out/README_SYNTHETIC.txt` | "Demonstration data - fictional." notice |

- **Sizes [V: generated]:** dev 162 registry / 300 listings; test 108 / 200. Nilgiris 60 registry entries in total.
- **Licence format (D35):** `SYN-<district code>-<5 digits>-<check letter>`. Invented; not modelled on any real scheme.
- **Registry:** status active / expired / suspended (expired ⇔ `valid_to` before the fixed reference date); coordinates within 1.5 km of the locality centroid; `address_ta` uses a hand Tamil street map + Tamil locality alias (needs review). No owner, phone or email fields.
- **Listings:** extra leading `listing_id` column (D35). `platform` is fictional (`platform_a`, `platform_b`, `direct`); `ref_url` uses the reserved `.example` domain. Pincode blank ~20%, coordinates blank ~30%.
- **Types (share):** clean 20%, noisy 35%, wrong_or_expired 12% (expired/suspended licence, unknown well-formed number, malformed check letter, or another property's licence; `true_registry_id` is the real entry), no_counterpart 18%, hard_negative 15% (same locality as a registry entry, shares one name token, within ~300 m).
- **Noise (noisy listings get 1-2 templates; `ground_truth.noise` records them):**
  - Dev: `abbreviation` (e.g. Cottage→Ctg, Nagar→Ngr, Guest House→GH), `reorder` (generic word first or name tokens swapped), `typo` (swap/drop/double/neighbour key).
  - Test: `alt_spelling` (phonetic variants not in the gazetteer, e.g. Kotagiri→Kothagiri), `merged` (two tokens joined), `dropped_locality` (D38), `tamil` (title in Tamil script; locality via gazetteer Tamil alias; D37).
  - All sets use canonical or English gazetteer aliases for `locality_text` on non-clean listings (alias resolution is a normaliser feature, M3).
- **Fresh names:** no name core (name without generic words) used in dev appears in test.
- **Brand-like vocabulary words (D90, Q48):** some generator words are ordinary English words that are also used as brand or business names: *Kingfisher* (a well-known beer and former airline brand), *Orchid* (a hotel brand), *Sapphire*, *Hornbill*, and generic nature words such as *Peacock*, *Lotus*, *Saffron*. Combined with a second word (e.g. "Kingfisher Nest Homestay") they form invented names, but a combination may still match a real small stay [A]. They are **not** blocklisted: *Kingfisher*, *Orchid*, *Sapphire* and *Hornbill* appear in the test set, and any change to the word lists or the blocklist for words in them regenerates both sets (tested: adding `kingfisher` changes every output file), which would invalidate the single recorded test run (`docs/eval-test-run.json`, rule 9). Decision pending (Q48). Brands that share no word with the generator (Hilton, Ibis, Novotel, Sheraton, Trident, Welcomhotel, Westin) were added to the blocklist without changing any output.
- **Limitations:** dev and test share districts, localities and gazetteer (D22). Tamil-script noise uses the same transliteration library as the normaliser, so results on that template are partly circular (D37). The real-name check is a small list, not exhaustive [A]; review `out/name_spotcheck.csv` by hand.

## Labelling in the product
UI banner: "Demonstration data — fictional." Concept note and video must say the same.
