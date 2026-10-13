# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@AGENTS.md

## Claude-specific notes

- Repo state: M0–M12, admin screens (D92-D93) and UI redesign (D94) merged on `main`; deploy accounts (Render, Neon, R2) and the restore test are pending human setup (`docs/deploy-runbook.md`, `docs/backup-restore.md`). One branch per change. Local PostgreSQL may be absent: DB tests then skip; CI runs them with `REQUIRE_DB=1`. The git-ignored `.env` may point `DATABASE_URL` at a Neon dev database: `tasks.py test` then creates `test_neondb`, and Neon keeps a session open after teardown, so drop `test_neondb` before the next run. A full Neon run takes 12-15 minutes; SQLite scratch settings (not committed) take under a minute. Git repo on `main`, remote `origin` = github.com/v1k111-29/Unlicensed-homestays. Work flow: 7 stages, modules M0–M12 (`implementationsplan.md` §2, `docs/workflow-and-prompts.md` §5). One module per session. Docs use no dates or hour budgets.
- UI screenshots go to `docs/screenshots/` (git-ignored, local only).
- Update `docs/progress.md` (newest entry on top) after each work session.
- Platform: Windows. Shell tools: PowerShell and Git Bash.
- Environment: use existing `.venv` at repo root. Never create another. Interpreter: `.venv\Scripts\python.exe` (Git Bash: `.venv/Scripts/python.exe`). Do not rely on `activate`.
- Python is 3.11.9 everywhere (venv, CI, Dockerfile, pyproject). Pin Django `<6` (Django 6 needs 3.12+).
- `make` is not installed here. Run commands as `python tasks.py <target>` (stdlib-only; single source of commands). `Makefile` only delegates to it, for Linux CI and Docker. Never put logic in the Makefile.
- Keep this file free of content duplicated from `AGENTS.md`.
