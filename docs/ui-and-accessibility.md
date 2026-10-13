# UI and Accessibility Plan

## Users
- **Officer:** works at a desk, reviews many cases, needs clarity and speed.
- **Tourist:** often on a phone, may switch to Tamil, wants a quick, understandable answer.

## Screens
Tourist: Check (home) · Result · About/disclaimer · Report (stretch).
Officer: Login · Dashboard · Upload · Queue · Case detail · Evidence.
Admin: Registry upload · Audit log (read-only, D93) · Accounts (list, create, one-time password, disable/enable, D92).

## Flows
- Tourist: Check → Result (4 outcomes) → optional Report.
- Officer: Upload → preview/confirm → Run matching → Queue → Case → Decide → Evidence.

## Design tokens
Defined in `docs/ui-design-brief.md` (binding) and implemented in `src/static/css/app.css` (D70). Summary: system font stack with Tamil fallbacks (Noto Sans Tamil / Nirmala UI, installed fonts only); base 16px; line-height 1.5 (Latin), 1.7 (Tamil); 4px spacing steps; radius 4px; one accent colour and neutral greys; status = text + shape + colour; WCAG 2.1 AA contrast verified by a test.

## Accessibility checklist
- Semantic HTML; one `h1` per page; landmarks.
- Visible focus; full keyboard operation; no hover-only content.
- Every field labelled; errors linked via `aria-describedby`.
- Touch targets ≥ 44px; no fixed-width layouts.
- Screen-reader smoke test on the tourist flow (NVDA or VoiceOver). **Not done yet** (see Verification status).
- `lang` attribute set per page (`en` / `ta`).

## English/Tamil handling
- URLs (D77): English has no prefix (`/check/`), Tamil is under `/ta/` (`/ta/check/`); `/en/...` redirects to the unprefixed page (Q39). `/` is the tourist check for visitors and the dashboard once signed in (D79).
- Toggle on every page: a "Language" `nav` in the header with plain links "English" / "தமிழ்" (`lang`, `hreflang`, current one `aria-current="true"`). No JavaScript, no cookie. The choice persists through the URL: every link and form on a Tamil page stays under `/ta/`. A browser set to Tamil is not redirected automatically (Q40).
- Strings via gettext; catalog `src/locale/ta/LC_MESSAGES/django.po` (+ compiled `.mo`), maintained with `python tasks.py messages` (pure Python, D78; `messages --check` reports stale or missing entries).
- **All Tamil is machine translation by the coding agent and needs review by a native speaker** (Q3, Q38). Marked in the .po header (`X-Review-Status`). The "Not found" disclaimer's Tamil text is pinned by a test so it cannot drift silently.
- Tourist text in Tamil avoids words for illegal / fake / unlicensed (சட்டவிரோத, போலி, உரிமமற்ற, உரிமம் இல்லாத, அனுமதியற்ற, ...) except in the mandated disclaimer; tested on the catalog and on the rendered Tamil pages.
- Stored data displayed as stored; transliteration shown as secondary text. District names in the tourist district list show the stored Tamil name first on Tamil pages, the English name in brackets.
- Tamil text runs longer: no fixed widths anywhere (brief §2, §14); `:lang(ta)` uses the Tamil system-font stack and line height 1.7 (no web fonts).

## Verification status (M10)
Verified [V] by automated tests without a browser (`tests/test_m10_i18n_a11y.py`, `tests/a11y_check.py`), on the tourist check (form, four outcomes, form errors), login (form, failed login, expired form), dashboard (empty and with data, officer and admin), upload listings (empty, line errors, preview), upload registry, matching runs (empty and with data), run summary, review queue (rows, empty, no filter match), case (normal, refused decision 400, stale form 409), evidence (empty, created), 403, 404 and 500, each in English and Tamil:
- `lang` attribute follows the language; skip link is the first focusable element and targets `main#main`; landmarks (header, named navs, data-notice `aside`, main, footer); one `h1` and no skipped heading levels; unique ids and resolving `aria-*`/`label for` references; every control labelled, invalid fields carry `aria-invalid` + `aria-describedby`; radio groups in `fieldset` + `legend`; buttons, links and scrollable regions have names; tables have a caption or `aria-labelledby` and scoped headers; no positive `tabindex`; no inline styles or width attributes; status badges carry text; empty and error states present.
- Every msgid in the code has a Tamil translation; no English UI sentence from the catalog appears on a Tamil page; placeholders survive translation; tourist pages set no cookie in either language.
- Colour contrast of every token pair (D70, `tests/test_ui_stylesheet.py`).

Admin screens (after M12): audit log (rows, empty filter result, invalid filter), accounts list, create form, refused create, one-time password page after create and reset, refused self-disable, in English and Tamil, with the same static checks [V].

Not verified [A]:
- No real browser was used: visible focus ring, actual tab order through the rendered layout, 200% zoom / reflow and Tamil wrapping at 360px width are designed for (brief §6, §14) but not observed.
- D94 redesign: every core screen was rendered in headless Chrome at 1280px and 360px (public pages and the dashboard, queue, case and login also in Tamil) and the full-page screenshots were saved locally in `docs/screenshots/` (synthetic data; git-ignored, not in the repo). Tamil wrapping at 360px was observed there [V, by eye]; wide officer tables scroll horizontally inside their labelled region at 360px. Still not observed: keyboard focus order and focus visibility in a real browser, 200% zoom, screen-reader output, Safari/Firefox (the form-mode chips need CSS `:has()`; without it both field groups show).
- No screen-reader test (NVDA / VoiceOver / TalkBack) has been done; the checklist item above stays open.
- No automated rule engine (axe-core etc.) was run; the static checks cover structure only.
- Tamil wording and terminology are unreviewed (Q38).
- Tamil date formats come from Django's own Tamil locale (month abbreviations); not reviewed.

## Tourist outcomes (copy intent)
| State | Intent |
|---|---|
| Matched | "Found in the registry" + public fields + validity |
| Details differ or expired | Show what differs; suggest checking with the host/district office |
| Several similar | Ask for the licence number |
| Not found | Mandatory disclaimer: does not mean illegal; registry may be incomplete |
Never use "illegal", "fake" or "unlicensed" in tourist text.

## Empty and error states
| Situation | Message intent |
|---|---|
| Empty queue | "No cases need review" + upload prompt |
| Bad CSV | Line-level errors; nothing saved |
| Server error | Plain message + retry + error ID (`500.html`, ID also in the log; D79) |
| Rate-limited | "Please wait and try again" |
| No registry loaded | Admin prompt to upload |
| Session expired | Redirect to login with notice |
| Expired form (CSRF) | "The form has expired" + what to do (`403_csrf.html`) |
| Access denied / not found | Plain message + link to the start page (`403.html`, `404.html`) |
| Decision conflict | 409 on the case page: what changed and who decided (D72) |
| Empty search / no runs / no uploads | `.empty-state` sentence + next action (queue, runs, uploads, case, evidence) |
