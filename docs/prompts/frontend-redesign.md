# Frontend redesign prompt (reference: public civic-portal style)

Paste the block below as the task prompt for a new agent session. Run it on its own branch cut from `main`.

```
Task: redesign the Verified Stays frontend. The human is not satisfied with the current UI (plain, sparse, too much like an unstyled admin form). Raise it to the quality of a modern public-service portal.

Read first: AGENTS.md (hard rules 1-10), CLAUDE.md, docs/ui-design-brief.md, docs/ui-and-accessibility.md, docs/security-and-privacy.md, docs/decisions.md D70 (design system) and the tourist-wording decisions, essentialfeatures.md (T1, O3-O5), src/static/css/app.css, src/templates/.

Visual reference (look only, do NOT copy): https://nammatn.in/welcome . Study its structure and feel, then design our own. Do not reuse its name, logo, wording, photographs, illustrations, emblem, or colour values. This product must not look like it is that site or any government body.

What to take from the reference (patterns):
- Bilingual identity in the header: English name plus Tamil name stacked, plain language switch (English / தமிழ்) in the top bar, sticky translucent header, quiet "Sign in" link plus one filled primary action.
- Hero with a calm, culturally rooted but tasteful background (a subtle line-art or soft tonal texture you create yourself in SVG or CSS; no stock photos, no AI-generated imagery), a short two-line headline with the second line in the accent colour, one supporting sentence, then the main action immediately: the tourist check form itself in the hero, not behind a button.
- Quick-choice chips under the headline (e.g. "Licence number", "Name and place") that switch the form mode without JavaScript frameworks (use radio-driven CSS or two links).
- A "How it works" section as a numbered vertical or horizontal stepper (3-4 steps), each with a short title and one sentence.
- A calm statistics strip ONLY from real, queryable data (counts of registry entries, districts covered, languages). Never invent numbers. Label synthetic data clearly. Hide the strip if data is missing.
- A grid of module tiles for the officer area (Queue, Uploads, Runs, Evidence) with an icon, title, one line, and an arrow link; counts only if real.
- Rounded, soft-bordered surfaces (radius 10-14px), generous spacing, one deep accent colour (a deep maroon or similar dignified hue is acceptable; pick your own and verify contrast), a warm off-white page background, a secondary warm gold used sparingly for highlights, restrained shadows.
- Typography: a modern humanist sans with a Tamil companion. Self-host the fonts as static files under src/static/fonts (OFL-licensed, e.g. Plus Jakarta Sans or similar, plus Noto Sans Tamil) OR use a system stack; NO external font CDN (CSP forbids it). If fonts must be downloaded, list filename, source and size and ask the human before downloading.
- Footer: short mission line, link groups (Check a stay / For officers / About this prototype), and the synthetic-data notice.
- Light theme required; add a dark theme only if it passes every contrast check.

Hard constraints (non-negotiable):
- Rules from AGENTS.md section 3 stay. Tourist wording stays neutral: "Not found" always carries the exact disclaimer, defined once in Python via gettext; never the words illegal/fake/unlicensed in templates or tourist text; status never by colour alone; neutral colour for "Not found" (never red).
- Never declare a stay unlicensed. Officer-only wording unchanged.
- No fake data, fake testimonials, fake "live" indicators, fake counts, or marketing claims. No claims of real-world accuracy.
- No HTMX and no JS framework or new dependency. Plain server-rendered HTML + CSS; a few lines of vanilla JS only if progressive enhancement and the page works without it; strict CSP (no inline scripts or styles, no external URLs).
- Tamil must fit: no fixed widths, longer strings wrap, Tamil line-height checked, language switch keeps the same page.
- Mobile first (360px), keyboard operable, visible focus, skip link, landmarks, AA contrast (add every new colour pair to the contrast table in docs/ui-design-brief.md; tests read it).
- No gradient blobs, glassmorphism overload, emoji icons, stock illustrations, lorem text, or purple/indigo defaults. Icons: a small hand-written inline SVG set (consistent stroke), decorative icons aria-hidden.
- All strings via gettext; run `python tasks.py messages` and keep Tamil complete (machine translation flagged "needs review").
- Keep every existing view, URL, permission guard, audit call and test passing. Change templates, static files and context only; no business-logic changes.

Scope, in order:
1. Update the design tokens and components in app.css and the brief (docs/ui-design-brief.md) first; commit.
2. Public pages: home/check (hero + form + result states + how-it-works + stats strip + footer), error pages.
3. Officer shell: header/nav, dashboard tiles, then queue, case, uploads, runs, evidence (keep the print stylesheet clean and plain).
4. Login page.
Out of scope: new features, new routes, data model changes, registration/sign-up flows.

Verification (required):
- lint, full tests, `tasks.py messages --check`, the stylesheet/contrast test, the accessibility HTML checker tests, template ban-list test, CSP test must all pass (DB tests: use SQLite scratch settings or the local Neon dev database through start.bat; CI runs PostgreSQL).
- Run the app (start.bat) and look at every page in the built-in browser at 1280px and 360px, English and Tamil; save screenshots under docs/screenshots/ (synthetic data only). Report anything you could not check.
- Record decisions in docs/decisions.md (next free D number) and a progress entry; do not push; commit on a new branch from main.
Final reply: short report with branch, commit, test counts, screenshot list, open questions.
```
