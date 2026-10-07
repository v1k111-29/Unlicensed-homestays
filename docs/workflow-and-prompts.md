# Workflow and Prompts — how to use these documents

Labels: **[V]** verified, **[E]** estimated, **[A]** assumed. This guide is tool-agnostic. Which AI coding tool you use is not decided (see `open-questions.md` Q11). If your tool does not read `AGENTS.md` automatically, paste it at the start of each session.

## 1. What each document is for
| Document | Use it to… | When |
|---|---|---|
| `AGENTS.md` | Give the agent rules, stack and definition of done | Every session (auto-read or pasted) |
| `implementationsplan.md` | Know the current stage, its done-criteria, cut order | Start/end of each stage |
| `essentialfeatures.md` | Get acceptance criteria for a module | Start of each module |
| `non_essential_features.md` | Park new ideas; stop scope creep | Whenever an idea appears |
| `docs/decisions.md` | Record chosen/rejected/why | After any significant choice |
| `docs/architecture.md`, `data-and-matching.md`, `security-and-privacy.md`, `ui-and-accessibility.md`, `synthetic-data-spec.md`, `testing-and-evaluation.md` | Detailed specs the agent reads for the relevant module only | Per module |
| `docs/open-questions.md` | Things the agent must ask, not guess | When blocked |
| `docs/risk-register.md` | Check risks at checkpoints | After Stage 3, after Stage 5 |
| `docs/demo-and-pitch.md` | Script, video, note | Stage 6 onward |
| `docs/progress.md` | Handoff log between sessions | End of every session |

## 2. One-time setup (before the kickoff)
1. Create the repo; copy this folder in; commit.
2. If your tool needs a different filename for agent rules, create it and point it at `AGENTS.md` (for Claude Code, a `CLAUDE.md` containing `@AGENTS.md` should work [A — verify in its docs]).
3. Answer or accept defaults for `open-questions.md` Q4 (demo district) before Module M1.

## 3. Kickoff prompt (paste once, at the start of session 1)
```
You are a senior product engineer working with me on "Verified Stays", built solo by me
targeting a demo-ready build, 90s video and concept note.

Step 1 — Read, in this order: AGENTS.md, implementationsplan.md, essentialfeatures.md,
non_essential_features.md, docs/decisions.md, docs/open-questions.md.
Do not read other docs yet; read each only when a module needs it.

Step 2 — Reply with: (a) a 10-line summary of the project and the hard rules in your own words,
(b) anything in the documents that is contradictory, ambiguous or that you disagree with
(say why; do not flatter), (c) questions you need answered before coding.
Do not write code in this step. Do not assume anything that is not in the documents.

Step 3 — Wait for my answers. Then propose the plan for Module M0 only (see
docs/workflow-and-prompts.md §5) and wait for my approval before implementing.

Working rules for the whole project:
- One module per session. Stay inside the module's scope.
- Log significant decisions in docs/decisions.md (chosen / rejected / why).
- New ideas go to non_essential_features.md; do not build them.
- If you are unsure, ask. Label claims verified / estimated / assumed.
- End every session by updating docs/progress.md.
```

## 4. The loop for every module (≈ 4 steps)
1. **Plan:** agent reads the module's docs, restates acceptance criteria, lists files it will touch and tests it will write. You approve or correct.
2. **Build:** agent implements only that scope, with tests. It runs `make test` / `make lint` itself.
3. **Verify:** you run the module's "done when" check (§5), read the diff, try the feature by hand. Run a separate review pass (§6) if the module touches auth, audit or matching.
4. **Close:** agent appends to `docs/progress.md`, adds any decisions to `docs/decisions.md`, you commit. Start a **fresh session** for the next module (smaller context, fewer mistakes [E]).

## 5. Modules
Stages map to `implementationsplan.md` §2.

| ID | Module | Stage | Read (besides AGENTS.md) | Deliver | Done when |
|---|---|---|---|---|---|
| M0 | Scaffold, tooling, CI | 1 | architecture.md §6, testing §2 | Folders, Dockerfile, ruff/pytest, `Makefile`, green CI, decisions copied | CI green on an empty test; `make test` works |
| M1 | Synthetic data generator | 1 | synthetic-data-spec.md | `generator.py`, gazetteer, dev/test sets, ground truth | Same seed → identical files; types and noise as specified; no real names |
| M2 | Schema + loaders | 1 | architecture.md §3 | Models, migrations, CSV loaders | Migrates; loads M1 output; row counts match |
| M3 | Normalisation + gazetteer use | 2 | data-and-matching.md §4 | Normaliser incl. Tamil handling | Unit tests for each step; Tamil/English alias test passes |
| M4 | Candidates + scoring + bands | 2 | data-and-matching.md §5–7 | Matching engine with stored features, versioned params | Deterministic; features stored; bands implemented |
| M5 | Eval harness + tuning | 2–3 | testing-and-evaluation.md §3 | `make eval`, CI floor, tuned thresholds | Dev metrics printed; test set run **once**; floors set |
| M6 | Auth, roles, scoping, audit | 3 | security-and-privacy.md | Login, roles, district helper, append-only audit | Permission + audit tests pass |
| M7 | Upload + run endpoints | 3 | essentialfeatures.md O2, O3 | Preview/confirm upload, run matching | Bad CSV saves nothing; run produces results; audited; permission test: officer batch naming another district is rejected whole and audit-logged |
| M8 | Queue, case, decisions, evidence | 4 | essentialfeatures.md O3–O5 | Officer UI flow | Full officer flow works on seeded data; confirmed pairs suppressed |
| M9 | Tourist check | 4 | essentialfeatures.md T1, ui-and-accessibility.md | Four outcomes, neutral wording, rate limit | Disclaimer on "Not found"; no IP stored; public fields only |
| M10 | i18n, accessibility, states | 5 | ui-and-accessibility.md | Tamil/English, empty/error states | Keyboard pass; no missing keys on core screens |
| M11 | Deploy, backup, observability | 5 | security §6, architecture.md | Live URL, nightly dump, `/healthz`, uptime ping | Restore tested once; demo runs on live URL |
| M12 | Concept note + video | 6 | demo-and-pitch.md | Note, script, video | Eval numbers + caveats in note; video ≤ 90s |

### Dependencies and what can run in parallel
```
M0 → M1 ∥ M2 → M3 → M4 → M5
        M2 → M6 → M7 → M8
                  M4 ─┘      M9 (needs M2, M4)
M8, M9 → M10 → M11 → M12 (note drafting can start after M5)
```
Parallel pairs that touch different folders: **M1 ∥ M2**, **M3 ∥ M6**, **M8 ∥ M9**, **note draft ∥ M10/M11**.
Caution [E]: you are the review bottleneck as a solo developer. Run **at most two** agents at once, each on its own branch, and merge one at a time.

## 6. Module prompt template (copy, fill the brackets)
```
Module [M#] — [name].
Read: AGENTS.md, essentialfeatures.md [IDs], and [docs listed in §5 for this module].
Scope: [one paragraph from the Deliver column].
Out of scope: everything else; park new ideas in non_essential_features.md.
Acceptance: [criteria copied from essentialfeatures.md] and the "Done when" in
docs/workflow-and-prompts.md §5.
Process: first reply with your plan (files to touch, tests to write, any question). Wait for
my "go". Then implement, run tests and lint, and report results.
Constraints: follow the hard rules in AGENTS.md §3; do not add dependencies without asking.
Finish: update docs/progress.md and docs/decisions.md if needed. Do not start the next module.
```

## 7. Review prompt (use after M4–M6 and M8, ideally in a fresh session)
```
Review the diff for Module [M#] against AGENTS.md §3 hard rules, essentialfeatures.md [IDs]
and security-and-privacy.md. List: (1) rule violations, (2) missing tests, (3) places where
district scoping or audit logging could be bypassed, (4) wording that could be misread as a
finding of illegality. Be critical; do not praise. Do not change code; report only.
```

## 8. Handoff / session close prompt
```
Update docs/progress.md with: what was done, what is partially done, decisions made (and add
them to docs/decisions.md), problems found, and the exact next step. Check the stage's
"definition of done" in implementationsplan.md and say which items are met, unmet, or at risk.
If at risk, say which cut-order item you would apply.
```

## 9. Checkpoints (from the plan)
- **After Stage 2:** matching works on dev data, else stop adding features.
- **After Stage 3:** go/no-go on scope; apply the cut order if behind.
- **After Stage 5:** live URL exists; feature freeze.

## 10. Rules of thumb
- If an agent proposes something not in the documents, it goes to `decisions.md` as a proposal or to `non_essential_features.md`. It is not built silently.
- If documents conflict, the order of authority is: `AGENTS.md` hard rules → `decisions.md` → feature files → other docs. Fix the conflict in the lower document.
- Never let one session span several modules.
