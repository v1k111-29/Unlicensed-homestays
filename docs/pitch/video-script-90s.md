# 90-Second Video Script (DRAFT)

> **Draft (M12).** UI screens for the queue, case, evidence and tourist check (M8-M9) and Tamil strings (M10) are still being finished, so shots are described, not captured. Re-time after the first rehearsal recording.
> Format (Q2 default): screen recording + English voice-over. Recorded on a **warm** server (see `recording-checklist.md`).
> Pace: ~150 words per minute → **at most 225 words** for 90 s. This script has **203 spoken words** (counted per scene below; no scene exceeds 2.5 words per second), leaving ~9 s for pauses and transitions [E].
> Data: seeded synthetic Nilgiris demo data — dev registry + `data/synthetic/out/dev/demo_listings.csv` (25 listings), matched against data set `synthetic-dev` (validity date 2026-04-01, D54/D68).

## Wording rules for this video (AGENTS.md rules 1, 2, 3, 10)
- Never say "illegal", "fake" or "unlicensed" about a stay in the voice-over or captions. The system **prioritises listings for human review**; the officer decides.
- The tourist "Not found" disclaimer is **shown on screen, not read aloud**; the voice-over paraphrases it neutrally.
- The officer decision label "Mark suspected unlicensed" may be visible on the officer case page (officer-only text, the real UI label); do not zoom on it or narrate it.
- On screen for the whole video (corner caption, added in the edit): **"Demonstration data — fictional."** (The app's own banner says "Demonstration build. All data shown is synthetic."; keep it visible too.)
- No accuracy claim. Do not show the evaluation table or any accuracy figure in the video; the concept note carries them with caveats.

## Timed script

| # | Time | Words (VO) | Voice-over (English) | Shot |
|---|---|---|---|---|
| 1 | 0:00–0:10 | 20 | Tamil Nadu aims to register every homestay, and officers have been directed to cross-check online listings against the licence registry. | Title card "Verified Stays" (2 s) → `[SCREENSHOT: officer dashboard, Nilgiris]` slow pan. Caption: "Demonstration data — fictional." |
| 2 | 0:10–0:25 | 33 | But listings often differ from the registry. Names are misspelled or shortened, one town has several names, and some details are in Tamil. We found no tool built for Indian addresses and Tamil. | Split screen: listing row "Amber Court Cottage, Udhagamandalam" next to registry row "Amber Court Cottage, Ooty"; then gazetteer aliases Ooty / Udhagamandalam / உதகமண்டலம் as text overlay. **Line "We found no tool…" only if Q8 re-check confirms; else cut it (−10 words).** |
| 3a | 0:25–0:34 | 22 | Verified Stays has two sides. A visitor, here in Tamil, checks a licence number and sees the stay is in the registry. | `[SCREENSHOT: tourist check /ta/ — Matched]`. Type `SYN-NLG-49713-B` → result "Found in the registry": Clover Loft Inn, Kotagiri, lodge, valid to 2028-07-10. |
| 3b | 0:34–0:40 | 15 | If a stay is not found, the answer is neutral: the registry may be incomplete. | `[SCREENSHOT: tourist check — Not found]`. Name "Jasmine Meadow Residency", locality "Coonoor" → neutral "Not found" panel; hold 2 s on the disclaimer. |
| 3c | 0:40–0:47 | 17 | An officer signs in and uploads a listings file. Nothing is saved until the preview is confirmed. | Officer `officer_nilgiris` already signed in (cut the login). Upload `demo_listings.csv`, "Match against: synthetic-dev" → preview "25 rows" → Confirm. |
| 3d | 0:47–0:53 | 15 | Matching then ranks every listing. Licence problems come first, then listings with no registry candidate. | Start run → run summary → `[SCREENSHOT: officer review queue]`. Top rows carry "Needs review - high priority (licence details)". |
| 3e | 0:53–1:01 | 17 | Each case shows why: licence, name, address and distance scores. The officer decides and writes a reason. | `[SCREENSHOT: case detail with feature breakdown]` for "Amber Court Cottage" (DEV-L0065). Officer selects a decision, types the reason (see below), submits. |
| 3f | 1:01–1:05 | 9 | The evidence page and audit log record every step. | `[SCREENSHOT: evidence page]` (1.5 s, footer "Supporting evidence for officer review, not a finding." visible) → `[SCREENSHOT: admin audit log]` (1.5 s). |
| 4 | 1:05–1:20 | 34 | The system never decides about a stay. It only orders the review queue; officers make every decision, with reasons. Tourist answers stay neutral, no visitor IP addresses are stored, and every action is logged. | Three text cards over dimmed screens: "Prioritises for human review — never decides" · "Neutral answers for visitors; no IP stored" · "Append-only audit log". |
| 5 | 1:20–1:30 | 21 | Everything shown uses fictional data and says nothing about real-world accuracy. Next: a pilot in one district, with real registry access. | End card: "Verified Stays · Prototype on synthetic data · Results do not predict real-world accuracy · Ask: registry access + one pilot district". [HUMAN: contact line / team name] |
| | **Total** | **203** | | |

Scene 1 and scene 2 claims are from the challenge brief [V from brief]; scene 2's "no tool" line is **unverified until Q8 is re-checked**. If cut, the total drops to 193 words; use the spare 4 s as a longer hold on the queue in 3d.

## Shot list (screen recording, 1366×768 or 1920×1080 at 125% zoom)

| Shot | Screen / URL [A until M8-M9 routes are final] | Action | Expected on screen [E: from an engine run on the demo slice; confirm in rehearsal] |
|---|---|---|---|
| S1 | `/dashboard/` as `officer_nilgiris` | Static, slow pan | District "Nilgiris", synthetic banner |
| S2 | Two CSV rows or the case page candidate table | Static | Listing "Amber Court Cottage", Udhagamandalam ↔ registry "Amber Court Cottage", Ooty |
| S3 | `/ta/check` (Tamil) | Type licence `SYN-NLG-49713-B`, submit | Matched: Clover Loft Inn, Kotagiri, lodge, valid 2023-10-06 to 2028-07-10 [V: dev registry row]. Which registry the tourist page reads is decided in M9 (Q32) |
| S4 | `/ta/check` or `/en/check` | Name "Jasmine Meadow Residency", locality "Coonoor", submit | Not found + disclaimer. [V: no such registry entry; the nearest name, "Jasmine Ridge Cottage", is in Ooty.] Confirm it does not return "Several similar" |
| S5 | `/officer/uploads/` | Choose `data/synthetic/out/dev/demo_listings.csv`; Match against `synthetic-dev`; preview; Confirm | Preview with 25 rows, then saved message |
| S6 | `/officer/runs/` → Start → `/officer/runs/{id}/` | Start run | Summary: 13 Matched, 12 Needs review (4 high priority licence, 5 no match, 3 needs review) [V: pure engine run on the demo slice with `m5-tuned-1`, as_of 2026-04-01; screen must agree] |
| S7 | `/officer/queue` | Scroll gently | First four rows (priority 1): Cardamom Ridge Guest House (licence not in registry), Coral Hollow Cottage (licence not in registry), Ivory Terrace Homestay (licence not valid), Amber Court Cottage (licence not valid) |
| S8 | `/officer/cases/{id}` for DEV-L0065 | Show feature breakdown; choose a decision; type reason; submit | Candidate SYN-NLG-92353-Q "Amber Court Cottage", Ooty, status expired, valid to 2026-03-11; locality alias resolved |
| S9 | `/officer/cases/{id}/evidence` | Static | Snapshot, candidates, scores, decision, SHA-256, "not a finding" footer |
| S10 | `/admin/audit` as admin (separate browser profile, already signed in) | Filter to today | Rows for upload, match run, decision, evidence |
| S11 | Title/end cards | Edit only | Texts as in scenes 4-5 |

**Decision in S8.** Rehearse with the human: which decision the demo shows. The demo plan (`demo-and-pitch.md`, step 5) asks for "Mark suspected unlicensed" with a reason. Suggested fictional reason text: *"Claimed licence SYN-NLG-92353-Q shows as expired on 2026-03-11 in the registry. Refer for field verification."* The voice-over stays "The officer decides and writes a reason." (Q33)

## Fallbacks
- If the queue/case UI (M8) is not ready: record S1, S5, S6 only and show `[SCREENSHOT: ...]` mock-ups clearly labelled "Design preview" — do not present mock-ups as working software.
- If the hosted server is cold or slow: record locally on the same seeded data (R7) and say nothing about hosting in the voice-over.
- If Tamil strings (M10) are not reviewed: still show Tamil in S3, with the caption "Tamil text: machine translation, under review" (Q3).
