# Demo, Video and Concept Note Plan

> Video logistics (who records, tools, voice-over language) are deferred — see `open-questions.md`.

## Demo dataset
Curated slice (~25 listings) in one district, covering every status. Fictional property names; real locality names allowed. Demo district: **open**.

## Demo script
1. Tourist checks a licensed stay in Tamil → "Found in the registry".
2. Tourist checks a non-existent stay → neutral "Not found".
3. Officer logs in, uploads listings CSV.
4. Matching runs; prioritised queue appears.
5. Officer opens a case, sees feature breakdown, marks suspected-unlicensed with a reason.
6. Officer opens evidence page.
7. (Cut: there is no audit-log screen; the audit log is stored append-only in the database and is named in the safeguards scene instead. Admin screen is roadmap.)

## 90-second video outline [E timing]
| Time | Content |
|---|---|
| 0:00–0:10 | Problem: court direction to cross-check booking sites; sealed homestays; WhatsApp reporting [V from brief] |
| 0:10–0:25 | Gap: existing tools target Western ordinances, none found for Indian addresses/Tamil [V from brief; not re-checked] |
| 0:25–0:65 | Live demo (script above), tightly cut |
| 0:65–0:80 | Safeguards: human review, neutral wording, append-only audit log (named, not shown) |
| 0:80–0:90 | Scalability + next step (pilot district, registry access) |
Must include on screen: "Demonstration data — fictional."

## Concept note outline (~2 pages)
1. Problem and evidence
2. Users and what changes for them
3. Solution and how it works
4. Prototype status and evaluation (with synthetic-data caveat)
5. Safeguards (false positives, DPDP)
6. Business model [A] and scalability
7. Roadmap and asks (registry access, pilot district)

## Judging-criteria map [V criteria from brief]
| Criterion | Where addressed |
|---|---|
| Relevance | Problem section; court direction; policy target of 100% registration |
| Tourism impact | Tourist check; trust and safety for visitors |
| Prototype readiness within a year | Live prototype; roadmap |
| Business model/scalability | Assumed model; districts as units; registry-CSV plug-in |
