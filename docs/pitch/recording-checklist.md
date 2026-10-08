# Recording Checklist — 90-second video (DRAFT)

> Use with `video-script-90s.md`. Draft written before M8-M11 are finished: commands marked [A] must be re-checked against the final build. Q2 default: screen recording + English voice-over; recording tool not chosen yet.

## 1. Build and data (day before)
- [ ] The build to record has M8 (queue, case, evidence), M9 (tourist check), M10 (Tamil) and M11 (deploy) merged, CI green on `main`. Note the commit hash here: `________`.
- [ ] Database is fresh for the take (see section 6 on retakes): `python tasks.py migrate` then `python tasks.py load` → six "OK" lines (dev 162/300/300, test 108/200/200).
- [ ] The tourist check returns **Matched** for licence `SYN-NLG-49713-B` (Clover Loft Inn, Kotagiri) and **Not found** for "Jasmine Meadow Residency", Coonoor (not "Several similar"). If not, pick other demo stays and update the script (Q32).
- [ ] Demo listings file copied to a neutral folder (e.g. `C:\demo\demo_listings.csv`) so the file picker does not show a personal Windows user path. Source: `data/synthetic/out/dev/demo_listings.csv` (25 Nilgiris rows).

## 2. Demo accounts (synthetic people only)
Create with the audited command; passwords come from an environment variable, never the command line or chat:
```
# PowerShell, current session only; do not write the passwords to .env or any committed file
$env:DEMO_OFFICER_PW = "<choose>"; $env:DEMO_ADMIN_PW = "<choose>"
.venv\Scripts\python.exe src\manage.py create_account officer_nilgiris --role officer --district Nilgiris --password-env DEMO_OFFICER_PW
.venv\Scripts\python.exe src\manage.py create_account demo_admin --role admin --password-env DEMO_ADMIN_PW
```
- [ ] Both accounts created (output `created officer 'officer_nilgiris'` / `created admin 'demo_admin'`). Admins take no `--district`.
- [ ] On the hosted server, run the same commands in the host's shell with the production `DATABASE_URL` [A: depends on host, M11].
- [ ] Remember: 5 failed logins lock the account and address for 15 minutes. Type carefully; keep the passwords in a password manager.

## 3. Warm server (30 minutes before)
- [ ] Open `/healthz` and wait for a success response (free tiers may sleep when idle [A, Q9]).
- [ ] Load every page in the demo path once: `/ta/check`, `/en/check`, `/login/`, `/dashboard/`, `/officer/uploads/`, `/officer/runs/`, `/officer/queue`, a case page, an evidence page, `/admin/audit` [A: final routes from M8-M9].
- [ ] Uptime ping is running so the server does not sleep between rehearsal and take.
- [ ] Do the rehearsal run on a **separate** database or before the reset in section 6 (an upload of the same file is refused the second time).
- [ ] Sign in **just before** recording: idle sessions expire after 30 minutes.
- [ ] Fallback (R7): if the server stays slow, record locally (`python tasks.py run`) on the same seeded data.

## 4. Browser
- [ ] Clean browser profile (or guest window): no extensions, no bookmarks bar, no saved-password or autofill pop-ups, no history suggestions in the address bar.
- [ ] Two profiles/windows: officer (`officer_nilgiris`) and admin (`demo_admin`, for the audit log), each already signed in. A third, signed-out window for the tourist check.
- [ ] Window 1920×1080 (or 1366×768); browser zoom 125% so text is readable in the video; check that Tamil text does not clip at that zoom.
- [ ] Tourist window opened at the `/ta/` URL prefix; officer windows in English.
- [ ] Cookie or consent prompts handled beforehand (none expected on our own app).
- [ ] Tourist check rate limit: rehearsal checks count against it; leave time for it to reset before the take [A: limit set in M9].

## 5. Computer and audio
- [ ] Windows Focus / Do not disturb on; notifications off.
- [ ] Close email, chat, OneDrive/Dropbox, update pop-ups, the terminal with `.env` or `DATABASE_URL`, and any window showing real names.
- [ ] Taskbar hidden or cropped out; system sounds muted.
- [ ] Microphone tested; voice-over recorded separately from the screen capture is fine (easier retakes).
- [ ] Recording tool and settings noted: `________` (Q2), 30 fps, cursor highlight on.

## 6. Retakes
- [ ] Re-uploading the same `demo_listings.csv` is refused (duplicate SHA-256), and decisions and audit rows cannot be undone. For a clean retake, recreate the database (drop and recreate it, then `migrate` + `load` + section 2) [A: on the hosted database, follow the host's reset steps]. The audit log cannot be truncated by design; do not try to work around that.
- [ ] Never "fix" a take by editing data in the database.

## 7. On-screen content checks (during the take)
- [ ] Synthetic banner "Demonstration build. All data shown is synthetic." visible on every app screen.
- [ ] Caption "Demonstration data — fictional." added in the edit for the whole video.
- [ ] Run summary shows 25 listings: 13 Matched, 12 Needs review (4 high priority licence details, 5 no match, 3 needs review) [V: engine run on the demo slice with `m5-tuned-1`, validity date 2026-04-01; the screen must agree, else stop and investigate].
- [ ] Queue starts with the four licence-detail cases (Cardamom Ridge Guest House, Coral Hollow Cottage, Ivory Terrace Homestay, Amber Court Cottage).
- [ ] The tourist "Not found" panel shows the full disclaimer and is grey/neutral, not red.
- [ ] The evidence page shows "Supporting evidence for officer review, not a finding."
- [ ] No terminal, `.env`, password, or personal file path appears in any frame.

## 8. After recording
- [ ] Final cut is 90 seconds or less; voice-over matches the script; no "illegal", "fake" or "unlicensed" spoken or captioned about a stay.
- [ ] The Q8 line ("We found no tool...") is in only if Q8 was re-checked; otherwise cut.
- [ ] End card includes "Results do not predict real-world accuracy."
- [ ] Export (format per submission rules — [HUMAN: check the brief]); keep the raw capture and the voice-over file.
- [ ] Watch once on a phone with sound off: is the story clear from the captions alone?
- [ ] Record in `docs/progress.md`: commit hash recorded, date-free note of what was shown, any deviation from the script.
