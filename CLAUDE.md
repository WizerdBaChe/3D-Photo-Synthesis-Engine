# CLAUDE.md — 3D Photo Synthesis Engine (Web v2.0)

Project: FastAPI backend + Vite/TS/Three.js frontend. Goal = Facebook 3D Photo
**small-angle parallax** viewing (NOT free-orbit 3D). Three coexisting viewer modes:
視差模式 (parallax, default, lightweight), LDI 分層補洞 (layered hole-fill), Mesh 模式 (.glb export).

These are **conditional** rules — each fires only in the situation named in its trigger.
If a turn doesn't touch that situation, ignore the rule (don't pre-empt it).

---

## Rendering / visual changes

- **When you change anything that renders to the screen** (shaders, viewers, parallax/LDI/mesh, any WebGL/canvas output): do NOT claim it "works" or that a "visual gate passed" from passing tests or a backend curl alone — those only prove the data path. Ask the user to confirm in the browser, because backend correctness ≠ visual correctness.
- **When an on-screen result looks wrong and the cause is conceptual** (not a typo): WebSearch/WebFetch the canonical/industry method and write a point-by-point "industry vs current" comparison BEFORE editing — don't guess-iterate on a wrong model.
- **When writing a three.js ShaderMaterial that samples multiple textures**: unroll into named uniforms (uColor0/uColor1…); do NOT use sampler2D arrays with variable indices or dynamic loop bounds — they fail to compile on WebGL/GLSL ES 1.00 and three.js then renders a SILENT blank. Always attach `renderer.debug.onShaderError` so compile failures surface instead of blanking.
- **When implementing depth-based parallax/LDI**: use CONTINUOUS per-pixel depth UV displacement (`offset = uMouse*(0.5-depth)*intensity*falloff`), the same math as the existing parallax shader. Do NOT translate discrete layers rigidly — that produces a cardboard-cutout detachment. LDI layers exist only to supply pre-filled content in the disocclusion band, not to be moved as rigid planes.

## Architecture / dependencies

- **When adding any heavy/ML dependency** (torch, LaMa, depth models, inpainters): make it optional-install + lazy import + graceful NoOp fallback (endpoint returns 422 when unavailable). Never add it to base `requirements.txt`. Mirror the `backend/depth_estimator.py` provider pattern (`get_/set_*` singleton).
- **When a component's quality is the suspected weak link but you need a working baseline**: put it behind a Provider/injection point (like `AbstractLDIBuilder` + `get_/set_ldi_builder`) so it can be swapped later without rewriting the pipeline.
- **Do not modify** `/synthesize`, `/parallax`, or `frontend/src/{parallax,viewer}.ts` when adding new modes — keep existing paths byte-for-byte and keep the existing test suite green.
- **When you edit the FastAPI backend while a dev server is running**: restart it (or rely on `--reload`) and confirm the live server serves the new payload (curl a new field) before asking the user to test. Keep ONE uvicorn instance; orphaned `--reload` processes squat on :8000.

## Project-specific definitions

- **FB 3D Photo** here means small-angle parallax (NOT free-orbit 3D). The only remaining problem is disocclusion holes.
- **LDI** = layer along depth cliffs + pre-fill the background layer; rendering is still continuous displacement. It is NOT "move layers like sprites."
- **Architecture ceiling**: single-image depth-warp + hole-fill can only do MILD deformation; occluded content cannot be truly recovered. To beat parallax you must upgrade the inpainter or the 3D representation — not the shader.
- **Known bottleneck**: large disocclusion holes (e.g. a whole bed) come out smeary with the classical C1 inpainter. Highest-ROI next step = swap LDIBuilder's inpainter for pretrained LaMa/diffusion (optional-install, fallback to C1).

## Working rhythm

- **When pausing or hitting a Gate failure**: write an honest root-cause + retrospective; state plainly what was right, what is a ceiling, what to try next. Do not hand-wave "fixed."
- **When committing meaningful work**: feature branch + PR + Conventional Commits; let the user decide the merge.
- **When evaluating any hole-fill / inpainting approach**: judge it on its output for a LARGE hole (whole-object occlusion), not a small-hole demo.

---

_Source: docs/retrospective-LDI-2026-06-28.md (full Chinese retrospective). Extracted 2026-06-28._
