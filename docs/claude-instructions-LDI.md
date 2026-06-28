# Claude Instructions — 3D Photo Synthesis Engine (LDI / rendering work)
# Extracted from project retrospective on 2026-06-28
# Ready to paste into CLAUDE.md. Rules are CONDITIONAL — each fires only in the
# situation named in its trigger. If a turn doesn't touch that situation, ignore the rule.

---

## Rendering / visual changes

- **When you change anything that renders to the screen** (shaders, viewers, parallax/LDI/mesh): do NOT claim it "works" or a "visual gate passed" from passing tests or a backend curl alone — those only prove the data path. Ask the user to confirm in the browser, because backend correctness ≠ visual correctness. `[from: user preferences / pitfalls]`
- **When an on-screen result looks wrong and the cause is conceptual** (not a typo): WebSearch/WebFetch the canonical/industry method and write a point-by-point "industry vs current" comparison BEFORE editing — don't guess-iterate on a wrong model. Iterating on a wrong mental model cost two rounds here (cardboard-cutout). `[from: effective workflows]`
- **When writing a three.js ShaderMaterial that samples multiple textures**: unroll into named uniforms (uColor0/uColor1…); do NOT use sampler2D arrays with variable indices or dynamic loop bounds — they fail to compile on WebGL/GLSL ES 1.00 and three.js then renders a SILENT blank. Always attach `renderer.debug.onShaderError` so compile failures surface instead of blanking. `[from: pitfalls]`
- **When implementing depth-based parallax/LDI**: use CONTINUOUS per-pixel depth UV displacement (`offset = uMouse*(0.5-depth)*intensity*falloff`), the same math as the existing parallax shader. Do NOT translate discrete layers rigidly — rigid layer translation produces a cardboard-cutout detachment. LDI's layers exist only to supply pre-filled content in the disocclusion band, not to be moved as rigid planes. `[from: technical decisions / pitfalls]`

---

## Architecture / dependencies (this project)

- **When adding any heavy/ML dependency** (torch, LaMa, depth models, inpainters): make it optional-install + lazy import + graceful NoOp fallback (endpoint returns 422 when unavailable). Never add it to base `requirements.txt`. Mirror the `backend/depth_estimator.py` provider pattern (`get_/set_*` singleton). `[from: constraints]`
- **When a component's quality is the suspected weak link but you need a working baseline**: put it behind a Provider/injection point (like `AbstractLDIBuilder` + `get_/set_ldi_builder`) so it can be swapped later without rewriting the pipeline. `[from: technical decisions]`
- **Do not modify** `/synthesize`, `/parallax`, or `frontend/src/{parallax,viewer}.ts` when adding new modes — keep existing paths byte-for-byte and keep the existing test suite green. `[from: constraints]`
- **When you edit the FastAPI backend while a dev server is running**: restart it (or rely on `--reload`) and confirm the live server serves the new payload (curl a new field) before asking the user to test. Keep ONE uvicorn instance; orphaned `--reload` processes squat on :8000. `[from: pitfalls]`

---

## Project-specific definitions

- **FB 3D Photo** in this project means small-angle parallax (NOT free-orbit 3D). The only remaining problem is disocclusion holes. `[from: constraints]`
- **LDI** = layer along depth cliffs + pre-fill the background layer; rendering is still continuous displacement. It is NOT "move layers like sprites." `[from: constraints]`
- **Architecture ceiling**: single-image depth-warp + hole-fill can only do MILD deformation; occluded content cannot be truly recovered. To beat parallax you must upgrade the inpainter or the 3D representation — not the shader. `[from: constraints]`
- **Known bottleneck**: large disocclusion holes (e.g. a whole bed) come out smeary with the classical C1 inpainter. The highest-ROI next step is swapping LDIBuilder's inpainter for pretrained LaMa/diffusion (optional-install, fallback to C1). `[from: pitfalls]`

---

## Working rhythm

- **When pausing or hitting a Gate failure**: write an honest root-cause + retrospective; state plainly what was right, what is a ceiling, and what to try next. Do not hand-wave "fixed" or pretend everything was solved. `[from: user preferences]`
- **When committing meaningful work**: feature branch + PR + Conventional Commits; let the user decide the merge. `[from: user preferences]`
- **When evaluating any hole-fill / inpainting approach**: judge it on its output for a LARGE hole (whole-object occlusion), not a small-hole demo. `[from: reusable principles]`

---

## Reusable principles (carry to other projects)

- Visual/rendering features need a human-in-the-loop visual gate; automated tests only certify the data path. `[from: reusable principles]`
- When output "looks wrong," check the authoritative/industry reference before iterating. `[from: reusable principles]`
- Put the suspected-weakest component behind a swappable interface so you can replace it without a rewrite. `[from: reusable principles]`
