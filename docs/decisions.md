# Decision Log — Verified Stays

Format: chosen · rejected · why · status. Labels: **[V]** verified, **[E]** estimated, **[A]** assumed. Add new entries at the bottom; never rewrite history — supersede instead.

| # | Decision | Chosen | Rejected | Why | Status |
|---|---|---|---|---|---|
| D1 | Scope tier | Tier A: one thin end-to-end slice | B (matching core + UI only), C (pitch-first) | Chosen by you. Solo build capacity is tight; cut order defined | Final |
| D2 | Registry data | Synthetic CSV, labelled synthetic | Real data | Access unconfirmed [V from brief]; avoids DPDP exposure | Final |
| D3 | Listing data | Officer CSV upload + tourist-typed details | Scraping; fetching pasted URLs | Platform terms [A]; court direction does not require scraping | Final |
| D4 | Backend | Django 5 + PostgreSQL, Python matching | FastAPI; Next.js + API; Supabase | Django gives auth, permissions, i18n, migrations, CSRF built-in, saving effort solo [E]. Python has strong fuzzy/transliteration libraries | Final |
| D5 | UI approach | Server-rendered templates + light HTMX | React SPA | One deployable, fewer build steps, easier accessibility | Final |
| D6 | Auth | Django built-in auth, argon2 | Hand-rolled auth; managed auth service | Well-tested, no extra service or lock-in | Final |
| D7 | Matching method | Rule-weighted explainable scoring | ML classifier; embeddings | No real labels; synthetic labels would make evaluation circular; officers need explanations | Final |
| D8 | Geocoding | Hand-built locality gazetteer + supplied lat/lng | Bulk use of a free public geocoder | Usage policy likely prohibits bulk use [A — verify] | Final |
| D9 | System authority | Prioritises for human review; never decides | Auto-flagging unlicensed | Court context; Amsterdam precedent (prioritise reports for human review) [V from brief]; limits false-positive harm | Final |
| D10 | Hosting | Render free web + Neon free Postgres, Docker | VPS; Fly.io | Free [A — verify limits]; free tiers by default (Q1) | Pending budget |
| D11 | Tourist wording | Four neutral outcomes; mandatory disclaimer on "Not found" | "Licensed / Unlicensed" binary | A wrong "unlicensed" label could harm a legal host | Final |
| D12 | Evaluation design | Dev set for tuning; test set with different seed + noise templates, run once | Single set for tune and test | Avoids overfitting and circular claims | Final |
| D13 | WhatsApp | Mock screen only | Real integration | Needs API approval; cannot be promised within the challenge build | Final |
| D14 | Photo similarity | Out of MVP | Include | Effort + extra false-positive source | Final |
| D15 | Tamil translation | Machine translation flagged "needs review"; native review if possible | Skipping Tamil; paid translation | Matches your "default" answer; reviewer still unnamed | Open (reviewer) |
| D16 | Business model | Assumed: district/state subscription after free pilot; tourists free; no price stated | Stating a price | You asked me to assume; no basis for a number [A] | Assumed |
| D17 | Documentation file names | Used your names: `implementationsplan.md`, `essentialfeatures.md`, `non_essential_features.md` | Standardised names (e.g., IMPLEMENTATION_PLAN.md) | You wrote them this way; renaming is trivial | Final |
| D18 | District scope | 8 districts: Nilgiris dense (~60 registry, demo slice) + Coimbatore, Madurai, Dindigul, Kanyakumari, Thanjavur, Ramanathapuram, Chennai (~30 each) | All 38 districts | More volume, gazetteer and Tamil work with no demo gain [E] | Final |
| D19 | Listing district | Uploading officer's district is the batch default; optional `district` column; required for admin uploads | District inferred from locality; required column for all | Simple, matches scoping; avoids gazetteer-dependent routing | Final |
| D20 | Cross-district listings | Not built; parked in `non_essential_features.md`. No cross-district truth type in ground truth | Build now | Out of Tier A scope | Final |
| D21 | Admin scope | Admin sees all districts; no admin hierarchy | District-level admins | Hierarchy stays in non-essential list | Final |
| D22 | Dev/test split | Same districts; different seeds, noise templates and fresh property names for test; gazetteer shared. Limitation stated in the caveat | Hold out districts | Held-out districts would need a second gazetteer [E] | Final |
| D23 | Tourist district filter | Optional district dropdown, default all. "Several similar" asks for licence number or district | No filter | Reduces ambiguity with 8 districts | Final |
| D24 | Tamil aliases | Nilgiris full; 2–3 localities per other district. Machine-generated, flagged "needs review". Gazetteer keyed by (district, alias) | Full Tamil coverage for all districts | No native reviewer (Q3) | Final |
| D25 | Cut order item 3 | Keep officer scoping; cut by reducing districts with data to Nilgiris + 2 | Reduce scoping to a single district | Scoping is cheap and test-driven; data is the costly part | Final |
| D26 | CLAUDE.md | Imports `@AGENTS.md`; keeps only Claude-specific notes | Duplicate content | Avoids drift | Final |
| D27 | Environment | Use existing `.venv` (Python 3.11.9 [V]); never create another | New venv | User instruction | Final |
| D28 | Python version | 3.11 everywhere (local `.venv`, CI, Dockerfile, pyproject); Django pinned `>=5.2,<6` | 3.12; recreate venv | User instruction. Django 6 needs 3.12+ [V]; Django 5.2 supports 3.10+ [V] | Final |
| D29 | Command runner | stdlib-only `tasks.py` is the single source; thin `Makefile` delegates to `python tasks.py <target>` | Install GNU make; Makefile-only | `make` not installed on Windows; no new dependency | Final |
| D30 | Cross-district upload rule | Officer batch whose `district` differs from own is rejected whole (line-level error) and audit-logged; admin may name any district; permission test in M7 | Silently override the column | Prevents bypassing district scoping | Final |
| D31 | Extra dependencies (AGENTS.md §11) | Approved: `psycopg[binary]`, `argon2-cffi`, `pytest-django`. Env vars via plain `os.environ` | `python-dotenv`, `dj-database-url` | Smallest set that meets D4/D6 and the test plan | Final |
| D32 | Git and remote | `git init` on `main`; remote `origin` = https://github.com/v1k111-29/Unlicensed-homestays (exists, public, empty [V via `git ls-remote`]). CI is unverified until a push runs it | — | `gh` not installed; no push without approval | Final |
