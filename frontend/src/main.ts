import "./style.css";
import { Viewer } from "./viewer";
import { ParallaxViewer } from "./parallax";
import { synthesize, parallax } from "./api";

// --- DOM 取得 ---
const $ = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;

const rgbInput = $<HTMLInputElement>("rgb");
const depthInput = $<HTMLInputElement>("depth");
const btn = $<HTMLButtonElement>("synthesize");
const statusEl = $<HTMLParagraphElement>("status");
const statusText = $<HTMLSpanElement>("statusText");
const spinner = $<HTMLSpanElement>("spinner");
const emptyState = $<HTMLDivElement>("emptyState");
const intensity = $<HTMLInputElement>("intensity");
const intOut = $<HTMLOutputElement>("intOut");
const edgeFalloff = $<HTMLInputElement>("edgeFalloff");
const edgeOut = $<HTMLOutputElement>("edgeOut");
const pct = $<HTMLInputElement>("percentile");
const pctOut = $<HTMLOutputElement>("pctOut");
const parallaxRange = $<HTMLInputElement>("parallax");
const parOut = $<HTMLOutputElement>("parOut");
const meshOnly = document.querySelector<HTMLDivElement>(".mesh-only");

// 兩個檢視器並存：預設視差（輕量），mesh 為進階匯出選項。
const viewport = $<HTMLElement>("viewport");
const parallaxViewer = new ParallaxViewer(viewport);
let meshViewer: Viewer | null = null;   // 延遲建立（避免兩個 WebGL canvas 同時佔資源）

function currentMode(): "parallax" | "mesh" {
  const checked = document.querySelector<HTMLInputElement>('input[name="mode"]:checked');
  return (checked?.value as "parallax" | "mesh") ?? "parallax";
}

// --- 狀態顯示輔助 ---
function setStatus(msg: string, kind: "" | "loading" | "ok" | "error" = ""): void {
  statusText.textContent = msg;
  statusEl.className = `status ${kind === "loading" ? "" : kind}`;
  spinner.hidden = kind !== "loading";
}

function refreshButton(): void {
  // RGB 必填；depth 在視差模式選填、mesh 模式必填。
  const hasRgb = !!rgbInput.files?.length;
  const hasDepth = !!depthInput.files?.length;
  btn.disabled = !(hasRgb && (currentMode() === "parallax" || hasDepth));
}

// --- 進階參數即時顯示 ---
intensity.addEventListener("input", () => {
  intOut.value = intensity.value;
  intensity.setAttribute("aria-valuetext", intensity.value);
  parallaxViewer.setIntensity(Number(intensity.value));
});
edgeFalloff.addEventListener("input", () => {
  edgeOut.value = Number(edgeFalloff.value).toFixed(1);
  edgeFalloff.setAttribute("aria-valuetext", edgeOut.value);
  parallaxViewer.setEdgeFalloff(Number(edgeFalloff.value));
});
pct.addEventListener("input", () => {
  pctOut.value = pct.value;
  pct.setAttribute("aria-valuetext", pct.value);
});
parallaxRange.addEventListener("input", () => {
  const text = `1.0 / ${Number(parallaxRange.value).toFixed(1)}`;
  parOut.value = text;
  parallaxRange.setAttribute("aria-valuetext", text);
});

// --- 模式切換：顯示/隱藏 mesh-only 進階參數，並更新按鈕可用性 ---
document.querySelectorAll<HTMLInputElement>('input[name="mode"]').forEach((r) => {
  r.addEventListener("change", () => {
    if (meshOnly) meshOnly.hidden = currentMode() !== "mesh";
    refreshButton();
  });
});

rgbInput.addEventListener("change", refreshButton);
depthInput.addEventListener("change", refreshButton);

// --- 合成 ---
btn.addEventListener("click", async () => {
  const rgb = rgbInput.files?.[0];
  if (!rgb) return;
  const depth = depthInput.files?.[0];

  btn.disabled = true;

  try {
    if (currentMode() === "parallax") {
      setStatus("處理中…", "loading");
      const result = await parallax({ rgb, depth });
      await parallaxViewer.loadParallax(result.rgbUrl, result.depthUrl);
      parallaxViewer.setIntensity(Number(intensity.value));
      emptyState.hidden = true;
      setStatus("✅ 完成：按住拖曳即可看 3D 視差。", "ok");
    } else {
      if (!depth) return;
      setStatus("合成中…（後端計算 3D 網格，大圖可能需數秒）", "loading");
      if (!meshViewer) meshViewer = new Viewer(viewport);
      const result = await synthesize({
        rgb,
        depth,
        percentile: Number(pct.value),
        depthNear: 1.0,
        depthFar: Number(parallaxRange.value),
        maxPixels: 500_000,
      });
      await meshViewer.loadGlb(result.glb);
      emptyState.hidden = true;
      setStatus(
        `✅ 完成：${result.vertexCount} 頂點 / ${result.faceCount} 面（可匯出 .glb）。`,
        "ok",
      );
    }
  } catch (err) {
    setStatus(`❌ 合成失敗：${(err as Error).message}`, "error");
  } finally {
    refreshButton();
  }
});
