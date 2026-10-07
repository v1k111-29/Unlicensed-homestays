# UI and Accessibility Plan

## Users
- **Officer:** works at a desk, reviews many cases, needs clarity and speed.
- **Tourist:** often on a phone, may switch to Tamil, wants a quick, understandable answer.

## Screens
Tourist: Check (home) · Result · About/disclaimer · Report (stretch).
Officer: Login · Dashboard · Upload · Queue · Case detail · Evidence.
Admin: Registry upload · Audit log.

## Flows
- Tourist: Check → Result (4 outcomes) → optional Report.
- Officer: Upload → preview/confirm → Run matching → Queue → Case → Decide → Evidence.

## Design tokens [A — adjust during build]
- Fonts: Noto Sans + Noto Sans Tamil; base 16px; line-height 1.5 (Latin), 1.7 (Tamil).
- Spacing scale: 4px steps. Radius 6px. One accent colour; neutral greys.
- Status styles: icon + text + colour (never colour alone).
- Contrast: WCAG 2.1 AA (4.5:1 text).

## Accessibility checklist
- Semantic HTML; one `h1` per page; landmarks.
- Visible focus; full keyboard operation; no hover-only content.
- Every field labelled; errors linked via `aria-describedby`.
- Touch targets ≥ 44px; no fixed-width layouts.
- Screen-reader smoke test on the tourist flow (NVDA or VoiceOver).
- `lang` attribute set per page (`en` / `ta`).

## English/Tamil handling
- URL prefix `/en/` `/ta/`; toggle on every page; preference persisted.
- Strings via gettext; machine translation flagged "needs review" until a native speaker checks.
- Stored data displayed as stored; transliteration shown as secondary text.
- Tamil text runs longer: test wrapping on narrow screens.

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
| Server error | Plain message + retry + error ID |
| Rate-limited | "Please wait and try again" |
| No registry loaded | Admin prompt to upload |
| Session expired | Redirect to login with notice |
