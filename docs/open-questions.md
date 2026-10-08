# Open Questions (do not guess these)

| # | Question | Needed by | Default if unanswered | Owner |
|---|---|---|---|---|
| Q1 | Budget and hosting confirmation (free tier OK? any spend? India region required?) | Stage 5 (deploy) | Free tiers, region unconstrained | You |
| Q2 | Video: who records, tools, voice-over language | Stage 6 | Screen recording + voice-over, English | You |
| Q3 | Tamil reviewer (native speaker) | Stage 5 | Machine translation flagged "needs review" | You |
| Q4 | Demo district | Stage 1 (data gazetteer) | **Answered:** Nilgiris; 8 districts total (D18) | You |
| Q5 | Repository licence | Before publishing | None (private) | You |
| Q6 | Retention rule for any stored data | Before any pilot | Synthetic only; n/a for demo | You + legal |
| Q7 | Business-model validation (who buys, price) | Post-challenge | Assumed; no price stated | You |
| Q8 | Re-verify "no Indian/Tamil tool exists" claim before the pitch | Stage 6 | Cited as "none found" per brief | Me (search) / you |
| Q9 | Free-tier limits and terms for Render, Neon, object storage | At signup | Treated as [A] | You |
| Q10 | Python version and package pins | Stage 1 | **Answered:** 3.11 everywhere (D28); versions pinned at scaffold | Me |
| Q11 | Which AI coding tool/agent will you use (affects how `AGENTS.md` is loaded)? | Stage 1 | **Answered:** Claude Code; `CLAUDE.md` imports `@AGENTS.md` (D26) | You |
| Q13 | Local PostgreSQL: not installed [V]. Install natively or use Docker? | Stage 1 (M2) | **Answered:** native PostgreSQL via `DATABASE_URL`; Docker not required (D39). Install steps in `docs/progress.md` (M2) | You |
| Q14 | Docker: not installed [V]. Dockerfile written, unbuilt. Install before M11? | Stage 5 (M11) | Build in CI only | You |
| Q15 | Matching scope with two synthetic sets in one DB: should M4 match a listings batch against the registry batch of the same `dataset` only, or against "the current registry"? | M4 | Same `dataset` for synthetic sets; for real uploads, the latest registry batch (D40) | Me / you |
| Q16 | Real platform exports may carry extra columns. Keep rejecting unknown columns (D41), or ignore them in M7 with a warning? | M7 | Reject (safer for privacy) | You |
| Q17 | Registry re-upload semantics (O6): does a new registry upload replace the previous one or add to it? | M7 | Replace: latest registry batch is current; older batches kept for history | You |
| Q12 | Command runner for `AGENTS.md` §7 (`make` not installed locally) | Stage 1 (M0) | **Answered:** stdlib `tasks.py` + thin Makefile (D29) | You |
