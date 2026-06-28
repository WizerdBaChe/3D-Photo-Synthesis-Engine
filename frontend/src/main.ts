import "./style.css";
import { Viewer } from "./viewer";
import { ParallaxViewer } from "./parallax";
import { LDIViewer } from "./ldi";
import { synthesize, parallax, ldi } from "./api";

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
const ldiOnly = document.querySelector<HTMLDivElement>(".ldi-only");
const loadSampleBtn = $<HTMLButtonElement>("loadSample");
const orbitMode = $<HTMLInputElement>("orbitMode");
const numLayers = $<HTMLInputElement>("numLayers");
const layerOut = $<HTMLOutputElement>("layerOut");

// 三個檢視器並存：預設視差（輕量）、LDI 分層補洞、mesh 進階匯出。
const viewport = $<HTMLElement>("viewport");
const parallaxViewer = new ParallaxViewer(viewport);
let meshViewer: Viewer | null = null;   // 延遲建立（避免多個 WebGL canvas 同時佔資源）
let ldiViewer: LDIViewer | null = null; // 同上，延遲建立

type Mode = "parallax" | "ldi" | "mesh";

function currentMode(): Mode {
  const checked = document.querySelector<HTMLInputElement>('input[name="mode"]:checked');
  return (checked?.value as Mode) ?? "parallax";
}

/** 依目前模式只顯示對應檢視器的 canvas，其餘隱藏（避免疊放互蓋，#2）。 */
function applyViewerVisibility(): void {
  const mode = currentMode();
  parallaxViewer.setVisible(mode === "parallax");
  ldiViewer?.setVisible(mode === "ldi");
  meshViewer?.setVisible(mode === "mesh");
}

/** 清空視口已載入內容、回到空狀態（模式切換 / 重新合成前呼叫，#3）。 */
function resetViewport(): void {
  parallaxViewer.clear();
  ldiViewer?.clear();
  meshViewer?.clear();
  emptyState.hidden = false;
}

// --- 狀態顯示輔助 ---
function setStatus(msg: string, kind: "" | "loading" | "ok" | "error" = ""): void {
  statusText.textContent = msg;
  statusEl.className = `status ${kind === "loading" ? "" : kind}`;
  spinner.hidden = kind !== "loading";
}

function refreshButton(): void {
  // RGB 必填；depth 在視差 / LDI 模式選填（可自動估算）、mesh 模式必填。
  const hasRgb = !!rgbInput.files?.length;
  const hasDepth = !!depthInput.files?.length;
  const mode = currentMode();
  btn.disabled = !(hasRgb && (mode === "parallax" || mode === "ldi" || hasDepth));
}

// --- 進階參數即時顯示 ---
intensity.addEventListener("input", () => {
  intOut.value = intensity.value;
  intensity.setAttribute("aria-valuetext", intensity.value);
  parallaxViewer.setIntensity(Number(intensity.value));
  ldiViewer?.setIntensity(Number(intensity.value));
});
edgeFalloff.addEventListener("input", () => {
  edgeOut.value = Number(edgeFalloff.value).toFixed(1);
  edgeFalloff.setAttribute("aria-valuetext", edgeOut.value);
  parallaxViewer.setEdgeFalloff(Number(edgeFalloff.value));
  ldiViewer?.setEdgeFalloff(Number(edgeFalloff.value));
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
numLayers.addEventListener("input", () => {
  layerOut.value = numLayers.value;
  numLayers.setAttribute("aria-valuetext", numLayers.value);
});

// --- 模式切換：顯示/隱藏各模式專屬參數、切換檢視器、清掉舊結果 ---
document.querySelectorAll<HTMLInputElement>('input[name="mode"]').forEach((r) => {
  r.addEventListener("change", () => {
    const mode = currentMode();
    if (meshOnly) meshOnly.hidden = mode !== "mesh";
    if (ldiOnly) ldiOnly.hidden = mode !== "ldi";
    // #3：切換模式時刷掉上一個模式的結果，回到空狀態並提示需重新合成。
    resetViewport();
    applyViewerVisibility();
    setStatus("已切換模式，請按「合成 3D 照片」重新產生。");
    refreshButton();
  });
});

// 自由旋轉視角切換（mesh-only）：套用到 mesh 檢視器（若已建立）。
orbitMode.addEventListener("change", () => {
  meshViewer?.setOrbitMode(orbitMode.checked);
});

rgbInput.addEventListener("change", refreshButton);
depthInput.addEventListener("change", refreshButton);

// --- 快速測試：載入內建測試範例圖（#4）---
async function urlToFile(url: string, filename: string, mime: string): Promise<File> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`無法載入範例圖 ${filename}（HTTP ${res.status}）`);
  const blob = await res.blob();
  return new File([blob], filename, { type: mime });
}

/** 把 File 塞回 <input type=file>，使後續流程與真實上傳完全一致。 */
function setInputFile(input: HTMLInputElement, file: File): void {
  const dt = new DataTransfer();
  dt.items.add(file);
  input.files = dt.files;
}

loadSampleBtn.addEventListener("click", async () => {
  loadSampleBtn.disabled = true;
  try {
    setStatus("載入測試範例圖…", "loading");
    const [rgbFile, depthFile] = await Promise.all([
      urlToFile("/samples/RGB_TEST.jpg", "RGB_TEST.jpg", "image/jpeg"),
      urlToFile("/samples/DEPTH_TEST.png", "DEPTH_TEST.png", "image/png"),
    ]);
    setInputFile(rgbInput, rgbFile);
    setInputFile(depthInput, depthFile);
    refreshButton();
    setStatus("✅ 已載入測試範例圖，按「合成 3D 照片」即可觀察效果。", "ok");
  } catch (err) {
    setStatus(`❌ ${(err as Error).message}`, "error");
  } finally {
    loadSampleBtn.disabled = false;
  }
});

// --- 合成 ---
btn.addEventListener("click", async () => {
  const rgb = rgbInput.files?.[0];
  if (!rgb) return;
  const depth = depthInput.files?.[0];

  btn.disabled = true;

  try {
    const mode = currentMode();
    if (mode === "parallax") {
      setStatus("處理中…", "loading");
      const result = await parallax({ rgb, depth });
      await parallaxViewer.loadParallax(result.rgbUrl, result.depthUrl);
      parallaxViewer.setIntensity(Number(intensity.value));
      applyViewerVisibility();   // #2：顯示視差 canvas、隱藏其他 canvas
      emptyState.hidden = true;
      setStatus("✅ 完成：按住拖曳即可看 3D 視差。", "ok");
    } else if (mode === "ldi") {
      setStatus("分層補洞中…（後端切層並預填背景，大圖可能需數秒）", "loading");
      if (!ldiViewer) ldiViewer = new LDIViewer(viewport);
      const result = await ldi({ rgb, depth, numLayers: Number(numLayers.value) });
      await ldiViewer.loadLDI(
        result.rgbUrl, result.depthUrl, result.bgUrl,
        result.width, result.height, result.layers,
      );
      ldiViewer.setIntensity(Number(intensity.value));
      ldiViewer.setEdgeFalloff(Number(edgeFalloff.value));
      applyViewerVisibility();   // #2：顯示 LDI canvas、隱藏其他 canvas
      emptyState.hidden = true;
      setStatus(
        `✅ 完成：${result.numLayers} 層，按住拖曳即可看縱深視差（前景滑開露出預填背景）。`,
        "ok",
      );
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
      meshViewer.setOrbitMode(orbitMode.checked);   // 套用目前視角選擇（FB 視差 / 自由旋轉）
      applyViewerVisibility();   // #2：顯示 mesh canvas、隱藏視差 canvas
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
