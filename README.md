# Verified Stays

Helps Tamil Nadu district administrations prioritise possibly unlicensed homestays and lodges for human review, and lets tourists check whether a stay appears in the licence registry. English and Tamil.

**Status:** prototype for the Tamil Nadu Tourism Innovation Challenge 2026. Runs on **synthetic data only**. Results on synthetic data demonstrate the method, not real-world accuracy.

## What it does
- **Officer:** upload listings CSV → run matching → review a prioritised queue → record a decision → print an evidence page.
- **Tourist:** enter a licence number or name + locality → get one of four neutral outcomes.
- **Admin:** upload the registry, view the audit log.

## What it does not do
It never declares a stay unlicensed. It does not scrape booking platforms. It does not use real personal data. See `non_essential_features.md`.

## Documentation map
See `AGENTS.md` §2. Start with `implementationsplan.md`.

## Quick start
> Planned; confirm after scaffolding.
```
make setup && make seed && make migrate && make run
```

## Licence and data notice
Licence: **TBD** (see `docs/open-questions.md`). All data in this repository is synthetic and fictional.
