# STATUS.md — read this before anything else, update it before you finish

**This file is the entry point for every session on this repository.** It is the
highest-priority record of current state. Two obligations, both non-optional:

1. **Read it first.** Before reading code, before planning, before editing.
   It tells you what is true today; the other documents tell you what happened.
2. **Update it last.** Any change to this repo — code, docs, records, git state
   — is not finished until this file reflects it and the changelog has a new row.
   A change that leaves this file stale has made the repo *worse*, because
   everything downstream now trusts a lie.

> Honest note on the mechanism: this is a **hand-maintained** control. It decays
> silently unless the rule above is followed, and nothing enforces it. That is
> why the pointer to this file is the first line of `CLAUDE.md` and `AGENTS.md`
> (which agents load automatically) rather than only living here — a file that
> only asks to be read is not a control. If you ever find this file contradicting
> the repo, **trust the repo, fix this file, and say so in the changelog.**

---

## 1. Current state — 2026-08-16

| | |
|---|---|
| **Project status** | **CLOSED 2026-08-16.** Do not propose or start feature work. |
| **Verdict** | Failure-leaning. The parallax viewer shipped, but it is the industry baseline reimplemented; the one problem the project existed to solve — disocclusion holes — was never solved, and the close-out concluded it was **unsolvable under the stated constraints**. |
| **Current as of** | **PR #10.** Verify in one line: `gh pr list --state merged --limit 1` — if it shows a **higher** number, this file was not updated with that change. Treat the whole file as suspect, check it against the repo, and fix it. |
| **Branches** | `main` only, local and remote. |
| **Working tree** | Clean. **3.0 MB**, 95 tracked files (of which `.git` is 1.5 MB). |

> The `main` tip SHA is deliberately **not** recorded here. A merge commit's SHA
> cannot be known until after the merge, so any tip written into this file is
> stale the moment it lands — a field guaranteed to rot is worse than no field.
> A **PR number is knowable before merging**, which is why "current as of" uses
> one: the PR that carries a change writes its own number into that row. Read the
> tip live with `git log --oneline -1` when you need it.
>
> The point of the verify command above is not that this file never goes stale —
> it will, the first time someone forgets. The point is that going stale becomes
> **detectable in one command** instead of invisible.
| **Runnable right now?** | **No.** `.venv/` and `frontend/node_modules/` were deleted in the 2026-08-16 cleanup. Run `.\engine.bat install` first. |

### What shipped and works

**視差模式 (parallax)** — `POST /parallax` + `frontend/src/parallax.ts`. Plane +
continuous per-pixel depth UV displacement. User verdict: 「相當成功，路線正確」.
This is the default mode and the only path that met its goal.

### What failed

**LDI 分層補洞** — `POST /ldi` + `frontend/src/ldi.ts`. The pipeline works and the
tests are green, but the by-eye gate failed three rounds. The close-out's finding
is that **the gate was unpassable by construction**: at ±6° the disocclusion band
is a few pixels wide, and LDI shares the parallax path's displacement math, so
even a perfect inpainter could not have looked "noticeably better". Not being
restarted.

### What is retained but secondary

**Mesh 模式** — `POST /synthesize` + `frontend/src/viewer.ts`, exports `.glb`.
Phase 1–2's work, demoted to an advanced export option in Phase 3.

---

## 2. The one thing that is NOT verified

`frontend/src/parallax.ts` gained a `renderer.debug.onShaderError` callback in
PR #5 (commit `0f186e8`). It is on the rendering path and **nobody has looked at
the picture.**

- The success path is unchanged by that commit, and `npm run build` was green.
- What is unproven is the thing the change exists for: **that a shader compile
  failure actually surfaces instead of blanking.**
- The check is step 8 of the manual-acceptance checklist at the end of
  `~/.claude/outputs/retrospectives/retrospective-3D-photo-engine-2026-08-16.md`
  — a negative control: deliberately break a line in `FRAG`, reload, confirm
  `[ParallaxViewer] shader 編譯失敗` appears in the console, then revert.
- Running it now costs an `.\engine.bat install` first. The user deleted the
  environment knowing this.

**Do not describe this change as verified.** If you run the check, record the
result here.

---

## 3. Where everything is

| You want | Go to |
|---|---|
| **Rules for working in this repo** | `CLAUDE.md` (project root). `AGENTS.md` is a pointer to it, not a copy — keep it that way. |
| Full lessons, root-cause analysis, clean path, acceptance checklist | `~/.claude/outputs/retrospectives/retrospective-3D-photo-engine-2026-08-16.md` |
| The rule set those lessons distilled into, with `[dest]` tags | `~/.claude/outputs/retrospectives/claude-instructions-3D-photo-engine.md` |
| Global-rule candidates — **proposed, never executed** | `~/.claude/outputs/retrospectives/global-rule-candidates-3D-photo-engine-2026-08-16.md` |
| Phase-by-phase history (10 checkpoints, last one is the close-out) | `references/3D-photo-engine-phase-log.md` |
| Why LDI stage A was paused | `docs/LDI_retrospective.md` |
| Desktop-v1.0 decisions (DD-001…007 still apply; DD-008…011 are dead) | `docs/ADR.md` |
| Architecture, all three endpoints, API params, known limits | `DEV_README.md` |
| User-facing instructions | `README.md` |
| 3DGS spike harness + why it was a no-go | `archive/spike-3dgs/` (start at `ARCHIVE-NOTE.md`) |
| What the 2026-08-16 cleanup deleted and how to restore it | `archive/2026-08-16-cleanup/CLEANUP-REPORT.md` |

Records live **in-repo** under `references/`, not in `~/.claude/references/`.

---

## 4. Landmines — know these before touching anything

- **`max_edge_ratio=30`** (the `/synthesize` default) was calibrated on **one**
  image. Other depth scales may over-cull and punch holes at real boundaries.
- **The `depth_convention=auto` heuristic** (`skew_hint > 0` and
  `high_frac < 0.35`) was also calibrated on a small sample, and was written
  **inverted** on the first attempt. A depth that looks reversed is this, until
  proven otherwise.
- **The frontend has no unit-test framework.** `parallax.ts` / `ldi.ts` /
  `viewer.ts` are guarded only by `tsc` + `vite build`. A green build says the
  types line up, not that the picture is right.
- **`~/.claude/rules/shader-failure-modes.md` cannot load on this repo** — its
  globs want `.glsl/.frag/.vert` and every shader here is a `.ts` template
  literal. `CLAUDE.md` is the only carrier of that rule. Do not assume the global
  rule has you covered.
- **Architecture ceiling**: single-image depth-warp + hole-fill can only do mild
  deformation. To beat parallax you must change the inpainter or the 3D
  representation — never the shader.

---

## 5. Verification status

| Check | Result | When | How to reproduce |
|---|---|---|---|
| Backend test suite | **100 passed** | 2026-08-16, before the env was deleted | `.\engine.bat install` then `.venv\Scripts\python -m pytest tests/unit tests/integration -q` |
| Frontend typecheck + build | **green** | 2026-08-16, same | `cd frontend && npm run build` |
| Every path named in the retrospective documents | 50/50 resolve | 2026-08-16 | — |
| Rendering behaviour of the `onShaderError` change | **NOT VERIFIED** | — | §2 above |

These numbers were true when written and **cannot be re-checked without an
install**. Treat them as dated evidence, not as a live status light.

---

## 6. If you are about to change something

1. Read this file (you are here) and `CLAUDE.md`.
2. `.\engine.bat install` if you need to run or test anything.
3. Follow `CLAUDE.md`'s rules — they are conditional, each fires only in its own
   situation.
4. Feature branch + PR + Conventional Commits; **the user decides the merge.**
5. Before you call it done, in the **same PR**, not later:
   - set §1's **"current as of"** row to **your own PR's number** (you know it
     before you merge — that is the whole reason the field is a PR number and
     not a commit SHA);
   - update §1, §2 and §5 if what they describe changed;
   - add a changelog row in §7.

   Skipping the first bullet is how this file goes stale. PR #9 skipped it and
   left the row reading #8; that is what §1's verify command is there to catch.

---

## 7. Changelog

Newest first. One row per landed change. Keep it short; detail belongs in the
commit message and the documents in §3.

| Date | PR | What changed |
|---|---|---|
| 2026-08-16 | #10 | Made staleness **detectable**: §1's row is now "current as of \<this PR's number\>" with a one-line verify command, and §6 step 5 makes writing that number a required part of every PR. #9 had left the row reading #8 — the same failure one level up, caught by the same method. |
| 2026-08-16 | #9 | Dropped the `main`-tip field from §1 — it was stale the instant PR #8 merged, which is what a self-invalidating field does. Replaced with a PR number. Added this row and the #8 row, which #8 could not contain. |
| 2026-08-16 | #8 | **This file created**, plus the pointers that make it work: `CLAUDE.md` and `AGENTS.md` now open with read-first / update-last, `README` and `DEV_README` carry human pointers. |
| 2026-08-16 | #7 | Post-close-out cleanup: 348 MB → 3.0 MB. `.venv`, `node_modules`, the 49 MB 3DGS residue and all regenerable caches deleted; three records the deletion would have falsified were corrected in the same commit. |
| 2026-08-16 | #6 | Rescued the 3DGS spike records off `spike/phase4-3dgs` (two phase-log checkpoints, `future_improvements.md` §三, the spike harness) before deleting that branch. They had no remote copy and the phase log already cited them. |
| 2026-08-16 | #5 | **Project close-out.** Retrospective rules merged into `CLAUDE.md`; `parallax.ts` got `onShaderError`; `AGENTS.md` became a pointer; `README`/`DEV_README` refreshed; the "PR #4 OPEN" claim corrected in two records; closing checkpoint appended to the phase log. |
| 2026-06-28 | #4 | LDI layered hole-fill, stage A. Merged, then paused: the by-eye gate failed. |
