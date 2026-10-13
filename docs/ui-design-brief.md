# UI Design Brief: Verified Stays

Binding visual and interaction rules for every screen (D70, revised by D94: public-service portal look). Implementation: `src/static/css/app.css` (the only stylesheet). Screens, flows and copy intent stay in `docs/ui-and-accessibility.md`; this file decides how they look and behave.
Labels: **[V]** verified, **[E]** estimated, **[A]** assumed.

## 1. Audience and tone
| Audience | Context | What the UI must do |
|---|---|---|
| District officer / admin | Desktop or laptop at a desk, long sessions, many cases in a row, may print evidence | Dense, scannable tables; predictable layout; every number explained; no decoration between the officer and the data |
| Tourist | Phone, often outdoors, may read Tamil, one question ("is this stay in the registry?") | One form, one answer, plain words, large targets; never alarming |

Tone: a calm, modern public-service portal. Factual and specific; warm but never promotional. The public pages may welcome the visitor (hero, steps, real counts); the officer pages stay dense and data-first. The product must not look like an official government site: no emblem, seal or state branding, and the footer says it is not an official service. The product never judges a stay; it reports what the registry contains and what an officer should check next (AGENTS.md rules 1-2).

## 2. Anti-patterns (do not ship any of these)
1. Gradient blobs, mesh or noise backgrounds, glow effects. (A flat tonal band with the project's own line texture, `static/img/kolam.svg`, is the only background art.)
2. Emoji used as icons or decoration, in any language.
3. Glassmorphism: frosted translucent cards or stacked blur. Only the sticky header is slightly translucent (light blur, near-opaque fallback).
4. Large-radius pastel card grids for data. Officer data lives in tables and definition lists; panels and tiles (12px radius, restrained shadow) group content, they do not replace tables.
5. Purple/indigo/violet "default framework" palettes, neon accents, dark-mode-first styling.
6. Marketing heroes with two competing CTAs or a headline with no task. The one hero (tourist check) puts the form itself in the hero; officer pages start with a left-aligned `h1`.
7. Fake or decorative statistics, fake "live" indicators, testimonials. Any number shown is queried from this data set and labelled synthetic (rules 3 and 10); the stats strip is hidden when the data is missing.
8. Stock photos, AI-generated imagery, mascots, third-party illustrations. Icons are the hand-written inline SVG set (`templates/icons/_icon.html`); the brand mark (`templates/icons/_mark.html`) is drawn for this project and is not an emblem.
9. Badge overuse: one status badge per row at most. Do not badge counts, roles, dates or categories; plain text does that.
10. Filler copy: "Seamlessly", "Empower", "Unlock", "Welcome to the future of...", lorem ipsum, placeholder names. Every sentence states a fact or an instruction.
11. Animations beyond the HTMX loading indicator; parallax; hover-only content; tooltips as the only place for information.
12. Icon fonts, icon CDNs, web-font CDNs. Shapes needed for status are drawn in CSS (see section 7).
13. Colour as the only carrier of meaning (status, errors, required fields, selected row, checked chip).
14. Fixed widths or heights on anything that holds text (Tamil runs longer). Inline SVG carries no `width`/`height` attributes; CSS sizes it.

## 3. Type
Font stacks use installed system fonts only. No web-font download and no font CDN [V: `app.css` has no `@import` or remote `url()`; tested]. D94 considered self-hosting an OFL humanist sans (e.g. Plus Jakarta Sans) plus Noto Sans Tamil and kept the system stack: no download, no extra bytes per page, and Windows, Android and Apple ship good humanist sans and Tamil faces.
- `--font-sans`: `"Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Roboto, "Noto Sans", "Noto Sans Tamil", "Nirmala UI", "Latha", "Tamil Sangam MN", ...`. `--font-display` uses the display cut of the same family for headings. Browsers fall back per glyph, so Tamil inside English pages renders with Nirmala UI (Windows), Noto Sans Tamil (Android/Linux) or Tamil Sangam MN (Apple) [A: depends on the device's installed fonts].
- `--font-tamil`: Tamil fonts first; applied by `:lang(ta)` (headings too). Mark Tamil fragments with `lang="ta"` (whole page via `<html lang>`; inline data such as `district.name_ta` and the Tamil brand line via `lang="ta"`).
- `--font-mono`: licence numbers, SHA-256 hashes, parameter versions. Wraps anywhere.

| Token | Size | Use |
|---|---|---|
| `--text-xs` | 0.8125rem (13px) | Tamil brand line only |
| `--text-sm` | 0.875rem (14px) | Hints, footer, badges, top bar, tile text |
| `--text-base` | 1rem (16px) | Body, form controls (never below 16px on inputs: stops iOS zoom) |
| table body | 0.9375rem (15px) | Officer tables only |
| `--text-md` | 1.125rem | `h3`, brand, ledes |
| `--text-lg` | 1.375rem | `h2`, tourist result title, `h1` on phones |
| `--text-xl` | 1.75rem | `h1`, tile and stats numbers |
| `--text-2xl` | clamp(1.875rem ... 2.75rem) | Hero `h1` only (Tamil hero: up to 2.25rem) |

Line height 1.55 (Latin), 1.75 for `:lang(ta)`, 1.25 for headings (1.4 for Tamil headings, 1.35 for the Tamil hero). Weights: 400, 600/650; 700 only for the brand, hero, numbers and alert titles. Paragraph measure capped at 70ch. Numbers use tabular figures.

## 4. Spacing, shape, layout
- Spacing tokens on a 4px grid: `--space-1` 4px, `-2` 8, `-3` 12, `-4` 16, `-5` 20, `-6` 24, `-8` 32, `-10` 40, `-12` 48, `-16` 64. No other values in components.
- Radius: `--radius` 12px (panels, tiles, alerts, tables, results), `--radius-sm` 8px (buttons, inputs), `--radius-pill` (chips, badges). Shadows: `--shadow-1` (resting surfaces) and `--shadow-2` (form card, result, hovered tile) only.
- Touch targets: `--target` 44px minimum height for buttons, inputs, nav links, chips, pagination, choice rows, language links.
- Layout shell (`base.html`): skip link; top bar (`.topbar`: synthetic-data notice `aside` + language switch); sticky header (`.site-header`: brand mark + English name with the Tamil name stacked below, then the officer nav and account, or "Officer sign in" as a quiet link plus one filled "Check a stay" button); `main`; dark footer (mission line, link groups "Check a stay" / "For officers" / "About this prototype", synthetic-data line, "Not an official government service"). `main` carries `.wrap` by default (max 76rem); the tourist page sets `{% block main_class %}main--full{% endblock %}` and wraps its own sections so the hero band runs full width.
- Page heading: `.page-head` (left-aligned `h1`, optional `.eyebrow` above, optional `.lede` line below). One `h1` per page.
- Breakpoint: one, at 40rem. Below it, definition lists stack, action buttons go full width, the officer nav becomes a horizontally scrollable row under the brand, and panels use 16px padding.

## 5. Colour
Warm neutrals, one deep maroon accent (`#7b1e2e`) and a warm gold used sparingly (eyebrow labels, step numbers, the notice icon; never for status). The values are this project's own. Semantic tones (danger, warning, success, neutral) exist only for status and messages; they never decorate. The danger tone moved towards orange-red (`#a52a12`) so it reads apart from the maroon accent; status never relies on hue anyway (text + shape). Focus is blue, distinct from the accent and every status tone. Light theme only [A]: no dark theme was added (D94), so no unchecked colour pair ships.

| Token | Hex | Role |
|---|---|---|
| `--color-text` | #1f1a17 | Body text |
| `--color-text-muted` | #5b524b | Secondary text, hints, `dt` |
| `--color-bg` | #faf7f2 | Page (warm off-white) |
| `--color-panel` | #ffffff | Raised surfaces: form card, tiles, tables, results |
| `--color-surface` | #f3ede4 | Hero band, top bar, row hover, disclaimer |
| `--color-surface-2` | #ebe3d7 | Table header |
| `--color-border` | #ddd3c5 | Dividers only (never the only edge of a control) |
| `--color-border-strong` | #857a70 | Input, chip and secondary-button edges |
| `--color-accent` / `-hover` | #7b1e2e / #5f1523 | Links, primary button, hero accent line, checked chip |
| `--color-accent-subtle` | #f7ebec | Info alert, selected row, messages, tile icon well |
| `--color-gold` | #b8862b | Decorative rings and lines only, never text |
| `--color-gold-text` / `-subtle` | #7a5413 / #f8f0de | Eyebrow labels, step numbers |
| `--color-focus` | #1d5fae | Focus ring |
| `--color-danger` / `-bg` | #a52a12 / #fcece8 | Errors; high-priority band |
| `--color-warning` / `-bg` | #7f4600 / #fcf2e2 | Review bands; "details differ" |
| `--color-success` / `-bg` | #1b6535 / #e7f3eb | Matched bands; "found" |
| `--color-neutral` / `-bg` | #4f5560 / #eef0f2 | Optional-review band; "not found" (never red) |
| `--color-footer-bg` | #2b1f1c | Footer band |
| `--color-on-footer`, `-muted`; `--color-footer-link` | #f6efe6, #cfc2b4; #f1d9a6 | Footer text and links |
| `--color-focus-on-dark` | #9cc8ff | Focus ring inside the footer |

### 5.1 Contrast pairs (WCAG 2.1 AA)
`text` = normal-size text, needs 4.5:1 (SC 1.4.3). `ui` = control boundary or focus indicator, needs 3:1 (SC 1.4.11). Ratios computed with the WCAG relative-luminance formula; `tests/test_ui_stylesheet.py` parses this table and recomputes every row from `app.css` [V]. Add a row whenever a new foreground/background combination is introduced. Hero text sits on a 90%-opaque `--color-surface` plate over the texture, so the `surface` rows apply [E: the texture strokes are lighter than the text colours by a wide margin].

| Foreground | Background | Kind | Ratio | Where |
|---|---|---|---|---|
| `--color-text` | `--color-bg` | text | 16.13 | Body on the page |
| `--color-text` | `--color-panel` | text | 17.24 | Body on panels, tiles, tables, result |
| `--color-text` | `--color-surface` | text | 14.81 | Hero band, notice bar, hovered row, disclaimer |
| `--color-text` | `--color-surface-2` | text | 13.54 | Table header |
| `--color-text` | `--color-accent-subtle` | text | 14.81 | Info alert, selected row, checked chip area |
| `--color-text` | `--color-gold-subtle` | text | 15.19 | Step number area |
| `--color-text` | `--color-danger-bg` | text | 15.02 | Error alert |
| `--color-text` | `--color-warning-bg` | text | 15.54 | Warning alert |
| `--color-text` | `--color-success-bg` | text | 15.12 | Success alert |
| `--color-text-muted` | `--color-bg` | text | 7.14 | Hints, lede |
| `--color-text-muted` | `--color-panel` | text | 7.63 | Hints and tile text on panels |
| `--color-text-muted` | `--color-surface` | text | 6.55 | Notice bar, hero note |
| `--color-text-muted` | `--color-surface-2` | text | 5.99 | Table header secondary text |
| `--color-text-muted` | `--color-accent-subtle` | text | 6.56 | Muted text in a selected row |
| `--color-accent` | `--color-bg` | text | 9.51 | Links, hero accent line |
| `--color-accent` | `--color-panel` | text | 10.16 | Links on panels; secondary button; stats numbers |
| `--color-accent` | `--color-surface` | text | 8.73 | Links in hovered rows, hero band |
| `--color-accent` | `--color-accent-subtle` | text | 8.73 | Checked chip, selected row links, secondary-button hover |
| `--color-accent-hover` | `--color-accent-subtle` | text | 11.15 | Secondary-button hover text |
| `--color-on-accent` | `--color-accent` | text | 10.16 | Primary button |
| `--color-on-accent` | `--color-accent-hover` | text | 12.98 | Primary button hover |
| `--color-gold-text` | `--color-bg` | text | 6.33 | Eyebrow labels |
| `--color-gold-text` | `--color-surface` | text | 5.81 | Notice-bar icon, eyebrow in hero |
| `--color-gold-text` | `--color-gold-subtle` | text | 5.96 | Step numbers |
| `--color-danger` | `--color-danger-bg` | text | 6.23 | High-priority badge |
| `--color-danger` | `--color-panel` | text | 7.14 | Field error text |
| `--color-danger` | `--color-bg` | text | 6.68 | Field error text on page |
| `--color-warning` | `--color-warning-bg` | text | 6.82 | Review badges; "details differ" title |
| `--color-warning` | `--color-panel` | text | 7.56 | "Details differ" title |
| `--color-success` | `--color-success-bg` | text | 6.22 | Matched badges |
| `--color-success` | `--color-panel` | text | 7.10 | "Found" title |
| `--color-neutral` | `--color-neutral-bg` | text | 6.56 | Optional-review badge |
| `--color-on-footer` | `--color-footer-bg` | text | 13.99 | Footer headings |
| `--color-on-footer-muted` | `--color-footer-bg` | text | 9.14 | Footer text |
| `--color-footer-link` | `--color-footer-bg` | text | 11.57 | Footer links |
| `--color-border-strong` | `--color-bg` | ui | 3.92 | Input and chip edges on the page |
| `--color-border-strong` | `--color-panel` | ui | 4.19 | Input and chip edges on panels |
| `--color-border-strong` | `--color-surface` | ui | 3.60 | Input edges on surface |
| `--color-border-strong` | `--color-accent-subtle` | ui | 3.60 | Controls inside a selected row |
| `--color-accent` | `--color-panel` | ui | 10.16 | Checked chip edge, current band chip edge |
| `--color-focus` | `--color-bg` | ui | 5.95 | Focus ring |
| `--color-focus` | `--color-panel` | ui | 6.36 | Focus ring on panels |
| `--color-focus` | `--color-surface` | ui | 5.47 | Focus ring on surface |
| `--color-focus` | `--color-accent-subtle` | ui | 5.47 | Focus ring in a selected row |
| `--color-focus-on-dark` | `--color-footer-bg` | ui | 9.21 | Focus ring in the footer |

Disabled buttons use `opacity: 0.6` and are exempt (SC 1.4.3 excludes inactive components); prefer not rendering a disabled button at all. The gold step ring is decorative (the step number is text with its own pair) and is not listed.

## 6. Focus and keyboard
- `:focus-visible` = 3px solid `--color-focus`, 2px offset, on every interactive element (footer: `--color-focus-on-dark`). Never `outline: none` without a replacement. Chips: the visually hidden radio's focus ring is drawn on its label. Tiles: the title link's ring is drawn around the whole tile.
- Skip link is the first focusable element; `main` has `tabindex="-1"` so the skip link and HTMX focus moves land there.
- Tab order follows visual order. No positive `tabindex`. Every action is a real `<a>` or `<button>`; never a clickable `<div>` or `<tr>`. A queue row links via the listing name cell.
- Wide tables: wrap in `<div class="table-wrap" tabindex="0" role="region" aria-labelledby="...">` so keyboard users can scroll them.

## 7. Status: the six match bands (officer only)
Labels come from `matching.models.MatchResult.Band` (gettext, defined in Python). Templates render `{{ result.get_band_display }}`; they never retype the label. The status is always text + shape + colour; the shape is a CSS `::before` and carries no extra meaning beyond the text.

```html
<span class="badge badge--{{ result.band }}">{{ result.get_band_display }}</span>
```

| Band key | Label (source of truth: model) | Tone | Shape | Queue priority |
|---|---|---|---|---|
| `review_licence` | Needs review - high priority (licence details) | danger | solid triangle | 1 |
| `no_candidate` | No match - needs review | warning | hollow square | 2 |
| `review_score` | Needs review | warning | solid diamond | 3 |
| `matched_score` | Matched (optional review) | neutral | hollow circle | 4 |
| `matched_licence` | Matched (licence and details agree) | success | solid circle | 5 |
| `matched_confirmed` | Matched (confirmed by an officer) | success | circle with ring | 6 |

Rules: one badge per row, in the status column. Never show a band to tourists. Never create a band, badge or label containing "illegal", "fake" or "unlicensed". The officer decision `suspected_unlicensed` is shown as plain text from `Review.get_decision_display` (officer screens only), not as a badge.

## 8. Officer tables and queue density
- Markup: `<table class="table">` with `<caption>` (visible or `.visually-hidden`), `<th scope="col">`, `<th scope="row">` for the listing name. Header row is sticky.
- Density: 8px/12px cell padding, 15px text; `.table--compact` (4px/8px) only for the candidate feature breakdown. Aim for at least 15 queue rows visible at 1366x768 [E].
- Column order for the queue: priority/status badge, listing name (link to case), locality, claimed licence (mono), top candidate, score (`.num`, 2 decimals), reasons (plain text, comma-separated). No row actions in the queue; decisions happen on the case page.
- Numbers right-aligned (`.num`), tabular figures. Scores always with their feature breakdown on the case page; never a bare percentage "confidence".
- Hover changes background only; the current row uses `aria-current="true"` or `.is-current` plus the accent-subtle background.
- Pagination: `<nav class="pagination" aria-label="...">`, "Previous" / "Next" as text links, current page with `aria-current="page"`, plus "Page X of Y". 50 rows per page [A].
- Filters sit above the table in a `<form method="get">`; they work without JavaScript and survive in the URL.

## 9. Forms
- Every control has a visible `<label>` above it. No placeholder-as-label. Hints in `.field-hint` above the control, linked with `aria-describedby`.
- Errors: summary `.alert.alert--error` with `role="alert"` at the top of the form, listing each error as a link to its field; field-level `.field-error` below the control (prefixed with "!" so it is not colour alone), `aria-invalid="true"` on the control (thicker red border), `aria-describedby` pointing at the error id.
- Primary action: one `.button` per form, left-aligned at the end inside `.actions`. Secondary actions `.button--secondary`. Cancel is a link.
- Decision form (O4): radio group in a `<fieldset>` with `<legend>`, each option a `.choice` row; reason `<textarea>` is required for "Mark suspected unlicensed" and the requirement is stated in text before submit, not only after a failed submit.
- Uploads (O2): native `<input type="file">`; line-level errors in a `.table` inside the error alert (line, column, message).
- Tourist form (T1): licence number or name + locality, optional district `<select>` defaulting to all. `inputmode`/`autocomplete="off"` where sensible; no field is required by the browser (server decides which combination is sufficient).

## 10. Tourist page and result states (T1)
Page order: hero band (`.hero`: eyebrow, two-line `h1` with the second line in the accent colour, one lede sentence, synthetic-data note; the form card `#check` beside it on wide screens, below on phones) -> result (`#result`; the form `action` ends in `#result`) -> statistics strip (`.stats`, only when `tourist.service.registry_summary()` returns counts: registry entries and districts of the registry tourists search, plus the number of UI languages) -> "How it works" stepper (`.steps`, four numbered steps) -> "About this check" (two `.note-card`s; privacy text unchanged).

Mode chips: a `fieldset.chips` with two radios (`mode-licence`, `mode-name`) styled as chips. Where CSS `:has()` works, the chosen chip hides the other field group; elsewhere both groups show with the "or" divider. No JavaScript. The view picks the checked chip (`mode`: name when only name/locality were sent), so a field with an error is never hidden. The form does not read `mode`. Known limit: a value typed into the hidden group is still sent; the licence number wins, as before.

One `.result` panel per answer, with an `h2.result__title` and only public fields (name, locality, category, validity) in a `.facts` list. The title carries the meaning; the shape and colour repeat it.

| Outcome | Class | Shape | Content |
|---|---|---|---|
| Matched | `.result--found` | check mark | "Found in the registry" + public fields + validity dates |
| Details differ or expired | `.result--differs` | triangle | Which field differs (as text), suggestion to check with the host or the district tourism office |
| Several similar | `.result--several` | three bars | Short list of up to N public entries; ask for the licence number or district; the form stays above, pre-filled |
| Not found | `.result--not-found` | hollow circle (neutral, never red) | "Not found in the registry" + the mandatory disclaimer in `.disclaimer` |

Mandatory disclaimer, verbatim (AGENTS.md rule 2), shown on every "Not found":

> This does not mean the stay is illegal. The registry may be incomplete.

It must be defined once in Python with gettext (e.g. a constant in the tourist module) and passed to the template. Reason: `tests/test_m6_hardening.py` bans "illegal", "fake" and "unlicensed" in every template, and this disclaimer is the only permitted tourist-facing use of one of those words. Not found is grey/neutral, never the danger tone. Do not show bands, scores or officer reasons to tourists.

## 11. Empty, error and loading states
Copy intent per screen is in `docs/ui-and-accessibility.md`. Visual rules:
- Empty: `.empty-state` (dashed border, no illustration): one sentence saying why it is empty, one link to the next action. Example: "No cases need review." + "Upload listings".
- Errors: `.alert--error` with `role="alert"`; server errors show a plain sentence, a retry link and the request/error ID in `.mono`.
- Info and success: `.alert--info` / `.alert--success` or Django messages (`.messages`, `role="status"`).
- Rate limit: `.alert--error` titled "Please wait and try again."
- Loading: only for HTMX requests (section 13). Full-page navigations show nothing extra.

## 12. Evidence page and print
The evidence page (O5) is designed for A4 print first.
- Top: `.evidence-statement` with "Supporting evidence for officer review, not a finding." (exact O5 wording, gettext) before any data. The synthetic-data notice bar also prints.
- Sections in order: listing snapshot (`.facts`), candidate registry entries (`.table`), feature scores (`.table--compact`), decision (who, when, reason), snapshot SHA-256 (`.mono`), parameter version, generated-at timestamp.
- Print rules in `app.css`: 15mm margins, nav/buttons/forms/pagination/`.no-print` hidden, `.print-only` shown, black on white, badges and alerts become black outlines (text kept, so status survives monochrome printing), table headers repeat per page, rows and sections avoid page breaks, hashes wrap.
- Provide a "Print" `.button` (`window.print()` is acceptable as progressive enhancement; the page also prints from the browser menu).

## 13. HTMX conventions
HTMX is an enhancement; every form and link works as a full page request first.
- Vendored static file under `src/static/` (no CDN; adding it is the M8/M9 owner's dependency step, AGENTS.md §11). Loaded through `{% block extra_head %}` with `defer`.
- CSRF: `<body hx-headers='{"X-CSRFToken": "{{ csrf_token }}"}'>` or the form's own token; never exempt views.
- Views return a partial template when `request.headers.get("HX-Request")` is set and the full page otherwise; same view, same permission and scoping guards, same audit calls.
- Targets: swap a region with a stable `id` (`hx-target="#queue"`, `hx-swap="outerHTML"`); the region is an `aria-live="polite"` container only if its update is the answer to the user's action (tourist result, decision saved).
- Indicator: `<span class="htmx-indicator" id="...">{% translate "Loading" %}</span>` with `hx-indicator`. Buttons that must not be pressed twice carry `data-busy-disable` and `hx-disabled-elt="this"`.
- After a swap that replaces the main answer, move focus to its heading (`tabindex="-1"` on the heading).
- Errors from HTMX requests render the same `.alert--error` partial; never swallow a 4xx/5xx silently.
- URLs: use `hx-push-url="true"` for filters and pagination so back/forward and bookmarks work.

## 14. Tamil and text length
- No fixed widths on text containers, buttons, badges or table columns; allow wrapping (`overflow-wrap: break-word` on headings, `anywhere` for data cells).
- Test each screen with the longest Tamil string at 360px width before merging [A: Tamil strings are often 30-60% longer than English, E].
- Never build sentences by concatenating translated fragments; use `blocktranslate` with placeholders.
- Data is displayed as stored; a transliteration is secondary text in `.muted`.

## 15. What later work must reuse
- Added by D94: `.topbar`, `.brand__mark` / `.brand__names` / `.brand__en` / `.brand__ta`, `.nav-main`, `.nav-account`, `.link-quiet`, `.footer-grid` / `.footer-group` / `.footer-base`, `.icon` (+ `templates/icons/_icon.html`), `.eyebrow`, `.panel`, `.section` / `.section-head`, `.button--large` / `.button--block`, `.hero` / `.hero__grid` / `.hero__text` / `.hero__accent` / `.hero__note`, `.check-card`, `.chips` / `.chip-input` / `.chip`, `.mode-panel--licence` / `--name`, `.result-area`, `.stats`, `.steps`, `.about-check` / `.note-card`, `.tiles` / `.tile` (`__icon`, `__title`, `__count`, `__go`), `.metric-list`, `.profile-card`, `.auth-grid` / `.auth-card` / `.auth-aside`, `.status-page`.
- Extend `base.html`; use blocks `title`, `content`, `extra_head`, `nav`, `main_class`. Do not add stylesheets or inline `style` attributes; add components to `app.css` with tokens and, for any new colour pair, a row in section 5.1.
- Components: `.page-head`, `.table-wrap` + `.table` (+ `.num`, `.table--compact`), `.pagination`, `.facts`, `.field` / `.field-hint` / `.field-error`, `.button` / `.button--secondary` / `.button-link`, `.actions`, `.alert--{error,warning,success,info}`, `.badge.badge--<band>`, `.result.result--{found,differs,several,not-found}`, `.disclaimer`, `.empty-state`, `.evidence-statement`, `.htmx-indicator`, `.mono`, `.visually-hidden`, `.print-only` / `.no-print`, `.plain` (unbulleted list), `.messages` (Django messages; `.message-{error,warning,success}` tint by level, text prefix carries the meaning).
- Added by M8 (officer pages): `.breadcrumb`, `.link-list`, `.status-line`, `.filters`, `.band-summary`, `.case-grid`, `.candidate` (`.is-current`), `.decision-form`. Added by M9 (tourist check): `.search-form` (`.or`), `.result-list`, `.next-step`. Added by M10: `.lang-switch` (header language links; current one `aria-current="true"`, bold + thick underline, not colour alone); the synthetic-data notice bar is an `<aside class="notice-bar" aria-label="...">` landmark. Tokens only; one rule block per selector (deduplicated at the `integration-2` merge).
