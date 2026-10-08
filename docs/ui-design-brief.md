# UI Design Brief: Verified Stays

Binding visual and interaction rules for every screen. Implementation: `src/static/css/app.css` (the only stylesheet). Screens, flows and copy intent stay in `docs/ui-and-accessibility.md`; this file decides how they look and behave.
Labels: **[V]** verified, **[E]** estimated, **[A]** assumed.

## 1. Audience and tone
| Audience | Context | What the UI must do |
|---|---|---|
| District officer / admin | Desktop or laptop at a desk, long sessions, many cases in a row, may print evidence | Dense, scannable tables; predictable layout; every number explained; no decoration between the officer and the data |
| Tourist | Phone, often outdoors, may read Tamil, one question ("is this stay in the registry?") | One form, one answer, plain words, large targets; never alarming |

Tone: a government records tool. Calm, factual, specific. It reads like a well-run public register, not a start-up landing page. The product never judges a stay; it reports what the registry contains and what an officer should check next (AGENTS.md rules 1-2).

## 2. Anti-patterns (do not ship any of these)
1. Gradient backgrounds, "hero blobs", mesh or noise textures.
2. Emoji used as icons or decoration, in any language.
3. Glassmorphism, backdrop blur, translucent panels.
4. Pastel card grids with large radius (`rounded-2xl/3xl`) and soft drop shadows. Cards are not the default container; tables, definition lists and sections are.
5. Purple/indigo/violet "default framework" palettes, neon accents, dark-mode-first styling.
6. Centered marketing hero with a big headline, subheadline and two CTAs. Pages start with an `h1` aligned left and the task.
7. Fake or decorative statistics ("10,000 stays verified", "99% accuracy"). Any number shown is real for this data set and labelled synthetic where it is (rules 3 and 10).
8. Decorative illustration, stock photos, mascots, abstract SVG art.
9. Badge overuse: one status badge per row at most. Do not badge counts, roles, dates or categories; plain text does that.
10. Filler copy: "Seamlessly", "Empower", "Unlock", "Welcome to the future of...", lorem ipsum, placeholder names. Every sentence states a fact or an instruction.
11. Animations beyond the HTMX loading indicator; parallax; hover-only content; tooltips as the only place for information.
12. Icon fonts or icon CDNs. Shapes needed for status are drawn in CSS (see section 7).
13. Colour as the only carrier of meaning (status, errors, required fields, selected row).
14. Fixed widths or heights on anything that holds text (Tamil runs longer).

## 3. Type
Font stacks use installed system fonts only. No web-font download and no font CDN [V: `app.css` has no `@import` or remote `url()`; tested].
- `--font-sans`: `system-ui, -apple-system, "Segoe UI", Roboto, "Noto Sans", "Noto Sans Tamil", "Nirmala UI", "Latha", "Tamil Sangam MN", ...`. Browsers fall back per glyph, so Tamil text inside English pages renders with Nirmala UI (Windows), Noto Sans Tamil (Android/Linux) or Tamil Sangam MN (Apple) [A: depends on the device's installed fonts].
- `--font-tamil`: Tamil fonts first; applied by `:lang(ta)`. Mark Tamil fragments with `lang="ta"` (whole page via `<html lang>`; inline data such as `district.name_ta` via `<span lang="ta">`).
- `--font-mono`: licence numbers, SHA-256 hashes, parameter versions. Wraps anywhere.

| Token | Size | Use |
|---|---|---|
| `--text-sm` | 0.875rem (14px) | Hints, footer, badges, notice bar |
| `--text-base` | 1rem (16px) | Body, form controls (never below 16px on inputs: stops iOS zoom) |
| table body | 0.9375rem (15px) | Officer tables only |
| `--text-md` | 1.125rem | `h3`, brand |
| `--text-lg` | 1.375rem | `h2`, tourist result title, `h1` on phones |
| `--text-xl` | 1.75rem | `h1` |

Line height 1.5 (Latin), 1.7 for `:lang(ta)`, 1.25 for headings. Weights: 400 and 600; 700 only for the brand and alert titles. Paragraph measure capped at 70ch. Numbers in tables use tabular figures.

## 4. Spacing, shape, layout
- Spacing tokens on a 4px grid: `--space-1` 4px, `-2` 8, `-3` 12, `-4` 16, `-6` 24, `-8` 32, `-12` 48. No other values in components.
- `--radius`: 4px everywhere. No shadows except the focus ring.
- Touch targets: `--target` 44px minimum height for buttons, inputs, nav links, pagination, choice rows.
- Layout shell (`base.html`): skip link, header with 4px accent top rule, synthetic-data notice bar, `main.wrap`, footer. Officer pages use the full `.wrap` (max 80rem). Tourist pages and the login form use `.wrap--narrow` (40rem) inside it. Everything is fluid; nothing has a fixed width.
- Page heading: `.page-head` (left-aligned `h1`, optional actions on the right, optional `.lede` line below). One `h1` per page.
- Breakpoint: one, at 40rem. Below it, definition lists stack and action buttons go full width.

## 5. Colour
Neutral greys plus one institutional accent (dark civic blue `#1d4f7c`). Semantic tones (danger, warning, success, neutral) exist only for status and messages; they never decorate. Light theme only for the demo [A].

| Token | Hex | Role |
|---|---|---|
| `--color-text` | #1a1d21 | Body text |
| `--color-text-muted` | #4d5562 | Secondary text, hints, `dt` |
| `--color-bg` | #ffffff | Page |
| `--color-surface` | #f4f5f7 | Notice bar, row hover, disclaimer |
| `--color-surface-2` | #e8eaee | Table header |
| `--color-border` | #c4c9d1 | Dividers only (1.66:1; never the only edge of a control) |
| `--color-border-strong` | #6b7280 | Input and secondary-button edges |
| `--color-accent` / `-hover` | #1d4f7c / #163d61 | Links, primary button, header rule |
| `--color-accent-subtle` | #e7eef5 | Info alert, selected row, messages |
| `--color-focus` | #b35c00 | Focus ring (amber: distinct from the accent and from every status tone) |
| `--color-danger` / `-bg` | #9b2318 / #fbeceb | Errors; high-priority band |
| `--color-warning` / `-bg` | #7f4600 / #fcf2e2 | Review bands; "details differ" |
| `--color-success` / `-bg` | #1b6535 / #e7f3eb | Matched bands; "found" |
| `--color-neutral` / `-bg` | #4d5562 / #eef0f3 | Optional-review band; "not found" |

### 5.1 Contrast pairs (WCAG 2.1 AA)
`text` = normal-size text, needs 4.5:1 (SC 1.4.3). `ui` = control boundary or focus indicator, needs 3:1 (SC 1.4.11). Ratios computed with the WCAG relative-luminance formula; `tests/test_ui_stylesheet.py` parses this table and recomputes every row from `app.css` [V]. Add a row whenever a new foreground/background combination is introduced.

| Foreground | Background | Kind | Ratio | Where |
|---|---|---|---|---|
| `--color-text` | `--color-bg` | text | 16.91 | Body |
| `--color-text` | `--color-surface` | text | 15.50 | Notice bar, hovered row |
| `--color-text` | `--color-surface-2` | text | 14.04 | Table header |
| `--color-text` | `--color-accent-subtle` | text | 14.45 | Info alert, selected row |
| `--color-text` | `--color-danger-bg` | text | 14.74 | Error alert |
| `--color-text` | `--color-warning-bg` | text | 15.25 | Warning alert |
| `--color-text` | `--color-success-bg` | text | 14.83 | Success alert |
| `--color-text-muted` | `--color-bg` | text | 7.52 | Hints |
| `--color-text-muted` | `--color-surface` | text | 6.90 | Notice bar, footer |
| `--color-text-muted` | `--color-surface-2` | text | 6.25 | Table header secondary text |
| `--color-text-muted` | `--color-accent-subtle` | text | 6.43 | Muted text in a selected row |
| `--color-accent` | `--color-bg` | text | 8.53 | Links |
| `--color-accent` | `--color-surface` | text | 7.82 | Links in hovered rows |
| `--color-accent` | `--color-accent-subtle` | text | 7.29 | Links in a selected row; secondary-button hover |
| `--color-accent-hover` | `--color-accent-subtle` | text | 9.58 | Secondary-button hover text |
| `--color-on-accent` | `--color-accent` | text | 8.53 | Primary button |
| `--color-on-accent` | `--color-accent-hover` | text | 11.20 | Primary button hover |
| `--color-danger` | `--color-danger-bg` | text | 6.91 | High-priority badge |
| `--color-danger` | `--color-bg` | text | 7.93 | Field error text |
| `--color-warning` | `--color-warning-bg` | text | 6.82 | Review badges; "details differ" title |
| `--color-warning` | `--color-bg` | text | 7.56 | "Details differ" title |
| `--color-success` | `--color-success-bg` | text | 6.22 | Matched badges |
| `--color-success` | `--color-bg` | text | 7.10 | "Found" title |
| `--color-neutral` | `--color-neutral-bg` | text | 6.59 | Optional-review badge |
| `--color-border-strong` | `--color-bg` | ui | 4.83 | Input edges |
| `--color-border-strong` | `--color-surface` | ui | 4.43 | Input edges on surface |
| `--color-border-strong` | `--color-accent-subtle` | ui | 4.13 | Controls inside a selected row |
| `--color-focus` | `--color-bg` | ui | 4.72 | Focus ring |
| `--color-focus` | `--color-surface` | ui | 4.33 | Focus ring on surface |
| `--color-focus` | `--color-accent-subtle` | ui | 4.04 | Focus ring in a selected row |

Disabled buttons use `opacity: 0.6` and are exempt (SC 1.4.3 excludes inactive components); prefer not rendering a disabled button at all.

## 6. Focus and keyboard
- `:focus-visible` = 3px solid `--color-focus`, 2px offset, on every interactive element. Never `outline: none` without a replacement.
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

## 10. Tourist result states (T1)
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

## 15. What M8 and M9 must reuse
- Extend `base.html`; use blocks `title`, `content`, `extra_head`, `nav`, `main_class`. Do not add stylesheets or inline `style` attributes; add components to `app.css` with tokens and, for any new colour pair, a row in section 5.1.
- Components: `.page-head`, `.table-wrap` + `.table` (+ `.num`, `.table--compact`), `.pagination`, `.facts`, `.field` / `.field-hint` / `.field-error`, `.button` / `.button--secondary` / `.button-link`, `.actions`, `.alert--{error,warning,success,info}`, `.badge.badge--<band>`, `.result.result--{found,differs,several,not-found}`, `.disclaimer`, `.empty-state`, `.evidence-statement`, `.htmx-indicator`, `.mono`, `.visually-hidden`, `.print-only` / `.no-print`, `.plain` (unbulleted list), `.messages` (Django messages; `.message-{error,warning,success}` tint by level, text prefix carries the meaning).
- Added by M8 (officer pages): `.breadcrumb`, `.link-list`, `.status-line`, `.filters`, `.band-summary`, `.case-grid`, `.candidate` (`.is-current`), `.decision-form`. Added by M9 (tourist check): `.search-form` (`.or`), `.result-list`, `.next-step`. Tokens only; one rule block per selector (deduplicated at the `integration-2` merge).
