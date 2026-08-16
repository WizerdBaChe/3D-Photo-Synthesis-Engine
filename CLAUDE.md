# CLAUDE.md — 3D Photo Synthesis Engine (Web v2.0)

> # ⛔ READ [`STATUS.md`](STATUS.md) FIRST — AND UPDATE IT BEFORE YOU FINISH.
> `STATUS.md` is this repo's highest-priority record: what is true *today*, what
> is unverified, and what will bite you. This file tells you the RULES;
> `STATUS.md` tells you the STATE. **Any change to this repo is unfinished until
> `STATUS.md` reflects it and its changelog has a new row — in the same PR, not
> later.** A stale `STATUS.md` is worse than none, because everything downstream
> trusts it.

> **Retrospective (project close-out, 2026-08-16):**
> `~/.claude/outputs/retrospectives/retrospective-3D-photo-engine-2026-08-16.md` (full guide) ·
> `~/.claude/outputs/retrospectives/claude-instructions-3D-photo-engine.md` (rule source of this file) ·
> `~/.claude/outputs/retrospectives/global-rule-candidates-3D-photo-engine-2026-08-16.md` (proposed, not executed).
> In-repo records: `references/3D-photo-engine-phase-log.md` (6 checkpoints + closing) ·
> `docs/LDI_retrospective.md` · `docs/ADR.md` (desktop v1.0 decisions; DD-008…DD-011 are dead).

Project: FastAPI backend + Vite/TS/Three.js frontend. Goal = Facebook 3D Photo
**small-angle parallax** viewing (NOT free-orbit 3D). Three coexisting viewer modes:
視差模式 (parallax, default, lightweight), LDI 分層補洞 (layered hole-fill), Mesh 模式 (.glb export).

**ops-relaxation: L1** (standing ruling — Opus-tier main loop runs at L1 in every
project; do not re-ask, just state identity and level).

**STATUS: CLOSED 2026-08-16 — do not propose feature work.** Parallax mode shipped and
passed acceptance; LDI failed its visual gate and is not being restarted; mesh/`.glb` is a
retained advanced option. The remaining value is the engine skeleton and the retrospective,
not the roadmap.

These are **conditional** rules — each fires only in the situation named in its trigger.
If a turn doesn't touch that situation, ignore the rule (don't pre-empt it).

---

## Rendering / visual changes

- **When you change anything that renders to the screen** (shaders, viewers, parallax/LDI/mesh, any WebGL/canvas output): do NOT claim it "works" or that a "visual gate passed" from passing tests or a backend curl alone — those only prove the data path. Ask the user to confirm in the browser, because backend correctness ≠ visual correctness. This repo hit that trap three rounds in a row.
- **When an on-screen result looks wrong and the cause is conceptual** (not a typo): WebSearch/WebFetch the canonical/industry method and write a point-by-point "industry vs current" comparison BEFORE editing — don't guess-iterate on a wrong model.
- **When writing a three.js ShaderMaterial that samples multiple textures**: unroll into named uniforms (uColor0/uColor1…); do NOT use sampler2D arrays with variable indices or dynamic loop bounds — they fail to compile on WebGL/GLSL ES 1.00 and three.js then renders a SILENT blank. Attach `renderer.debug.onShaderError` at renderer-construction time, not after something breaks; `parallax.ts` and `ldi.ts` both have it. **The global `~/.claude/rules/shader-failure-modes.md` cannot load on this repo** — its globs are `**/*.{glsl,frag,vert,vs,fs}` and `shaders/**`, and every shader here lives in a `.ts` template literal, so this line is the only carrier.
- **When implementing depth-based parallax/LDI**: use CONTINUOUS per-pixel depth UV displacement (`offset = uMouse*(0.5-depth)*intensity*falloff`), the same math as the existing parallax shader. Do NOT translate discrete layers rigidly — that produces a cardboard-cutout detachment. LDI layers exist only to supply pre-filled content in the disocclusion band, not to be moved as rigid planes.

## Architecture / dependencies

- **When adding any heavy/ML dependency** (torch, LaMa, depth models, inpainters): make it optional-install + lazy import + graceful NoOp fallback (endpoint returns 422 when unavailable). Never add it to base `requirements.txt`. Mirror the `backend/depth_estimator.py` provider pattern (`get_/set_*` singleton).
- **When a component's quality is the suspected weak link but you need a working baseline**: put it behind a Provider/injection point (like `AbstractLDIBuilder` + `get_/set_ldi_builder`) so it can be swapped later without rewriting the pipeline — **but only when the component is ALREADY distrusted and its replacement is ALREADY named.** "Some future implementation might exist" is not a reason; one interface with one implementation is the right shape until a second is real.
- **Do not modify** `/synthesize`, `/parallax`, or `frontend/src/{parallax,viewer}.ts` when adding new modes — keep existing paths byte-for-byte and keep the existing test suite green. *Documented exception:* the 2026-08-16 close-out added ~10 lines to `parallax.ts` for `onShaderError`, under an explicit user ruling, because two rules in this file collided.
- **When you edit the FastAPI backend while a dev server is running**: restart it (or rely on `--reload`) and confirm the live server serves the new payload (curl a new field) before asking the user to test. Keep ONE uvicorn instance; orphaned `--reload` processes squat on :8000.

## Known-fragile values — do not trust without re-calibration

- **`max_edge_ratio=30`** (the `/synthesize` default) was calibrated on ONE image (the sample room shot). Other depth scales or compositions may over-cull and punch holes at genuine depth boundaries.
- **The `depth_convention=auto` heuristic** (`skew_hint > 0` and `high_frac < 0.35`) was calibrated on a small sample and was written INVERTED on the first attempt. Treat a wrong-looking depth as a convention misdetection before anything else.
- **The frontend has no unit-test framework.** `parallax.ts` / `ldi.ts` / `viewer.ts` are guarded only by `tsc` + `vite build`; a green build says the types line up, not that the picture is right.

## Project-specific definitions

- **FB 3D Photo** here means small-angle parallax (NOT free-orbit 3D). The only remaining problem is disocclusion holes.
- **LDI** = layer along depth cliffs + pre-fill the background layer; rendering is still continuous displacement. It is NOT "move layers like sprites."
- **disocclusion** = the hole revealed when foreground slides away, containing content the original photo never captured. At small angles it is a band a few pixels wide — which is why LDI could never look "noticeably better" than parallax.
- **Architecture ceiling**: single-image depth-warp + hole-fill can only do MILD deformation; occluded content cannot be truly recovered. To beat parallax you must upgrade the inpainter or the 3D representation — not the shader.
- **Known bottleneck**: large disocclusion holes (e.g. a whole bed) come out smeary with the classical C1 inpainter. Highest-ROI restart step = swap LDIBuilder's inpainter for pretrained LaMa/diffusion (optional-install, fallback to C1) — but estimate the improvement ceiling first (see Working rhythm).
- **Records live in-repo**: `references/3D-photo-engine-*.md`, NOT in `~/.claude/references/`. `AGENTS.md` is a one-line pointer to this file — keep it that way; do not restore a second copy of these rules.

## Working rhythm

- **When a feature's value is defined as "noticeably better than existing X"**: estimate the improvement CEILING under the stated constraints — as a measurable proportion, in one line — BEFORE building. If the ceiling is within noise, the feature fails at any implementation quality. This is the single lesson that cost this project the most.
- **When the same subsystem is being patched a third time**: the tell is that this fix patches the hole left by the LAST fix. Stop and question the representation, not the patch.
- **When pausing or hitting a Gate failure**: write an honest root-cause + retrospective; state plainly what was right, what is a ceiling, what to try next. Do not hand-wave "fixed."
- **When committing meaningful work**: feature branch + PR + Conventional Commits; let the user decide the merge.
- **When evaluating any hole-fill / inpainting approach**: judge it on its output for a LARGE hole (whole-object occlusion), not a small-hole demo.

---

_Source: `docs/retrospective-LDI-2026-06-28.md` (milestone, 2026-06-28) + the project close-out
retrospective linked at the top of this file (2026-08-16)._
