// 後端 API 呼叫封裝。
// 開發時走 Vite proxy 的 /api；部署時可用 VITE_API_BASE 指向實際後端網域。
const API_BASE = import.meta.env.VITE_API_BASE ?? "/api";

export interface SynthesizeParams {
  rgb: File;
  depth: File;
  percentile?: number;
  depthNear?: number;
  depthFar?: number;
  maxPixels?: number;
}

export interface SynthesizeResult {
  glb: ArrayBuffer;
  vertexCount: number;
  faceCount: number;
}

/** 上傳 RGB+Depth，回傳合成後的 .glb 二進位與網格統計。 */
export async function synthesize(p: SynthesizeParams): Promise<SynthesizeResult> {
  const form = new FormData();
  form.append("rgb", p.rgb);
  form.append("depth", p.depth);

  const q = new URLSearchParams();
  if (p.percentile !== undefined) q.set("percentile", String(p.percentile));
  if (p.depthNear !== undefined) q.set("depth_near", String(p.depthNear));
  if (p.depthFar !== undefined) q.set("depth_far", String(p.depthFar));
  if (p.maxPixels !== undefined) q.set("max_pixels", String(p.maxPixels));

  const res = await fetch(`${API_BASE}/synthesize?${q.toString()}`, {
    method: "POST",
    body: form,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      detail = j.detail ?? detail;
    } catch {
      /* 非 JSON 錯誤，沿用狀態碼 */
    }
    throw new Error(detail);
  }

  return {
    glb: await res.arrayBuffer(),
    vertexCount: Number(res.headers.get("X-Vertex-Count") ?? 0),
    faceCount: Number(res.headers.get("X-Face-Count") ?? 0),
  };
}

export interface ParallaxParams {
  rgb: File;
  depth?: File;          // 選填：缺少時後端嘗試自動估算（目前未啟用 → 422）
}

export interface ParallaxResult {
  width: number;
  height: number;
  rgbUrl: string;        // data:image/png;base64,...
  depthUrl: string;
}

/** 輕量視差路徑：上傳 RGB(+選填 depth)，回正規化 RGB/depth 兩張圖供著色器位移。 */
export async function parallax(p: ParallaxParams): Promise<ParallaxResult> {
  const form = new FormData();
  form.append("rgb", p.rgb);
  if (p.depth) form.append("depth", p.depth);

  const res = await fetch(`${API_BASE}/parallax`, { method: "POST", body: form });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      detail = j.detail ?? detail;
    } catch {
      /* 非 JSON 錯誤，沿用狀態碼 */
    }
    throw new Error(detail);
  }

  const j = await res.json();
  return {
    width: j.width,
    height: j.height,
    rgbUrl: j.rgb,
    depthUrl: j.depth,
  };
}

export interface LDIParams {
  rgb: File;
  depth?: File;          // 選填：缺少時後端嘗試自動估算（目前未啟用 → 422）
  numLayers?: number;    // 2~3，預設 2
}

export interface LDILayer {
  color: string;         // data:image/png;base64,...
  depth: string;
  alpha: string;
  depthMin: number;
  depthMax: number;
}

export interface LDIResult {
  width: number;
  height: number;
  numLayers: number;
  rgbUrl: string;        // 原圖 RGB（連續位移用）
  depthUrl: string;      // 原圖正規化 depth
  bgUrl: string;         // 預填背景底層（disocclusion 取代用）
  layers: LDILayer[];    // 由近到遠（標準化 / .ldi 用）
}

/** LDI 分層補洞路徑：上傳 RGB(+選填 depth)，回多層 RGBA+depth 供多層 shader 視差。 */
export async function ldi(p: LDIParams): Promise<LDIResult> {
  const form = new FormData();
  form.append("rgb", p.rgb);
  if (p.depth) form.append("depth", p.depth);

  const q = new URLSearchParams();
  if (p.numLayers !== undefined) q.set("num_layers", String(p.numLayers));

  const res = await fetch(`${API_BASE}/ldi?${q.toString()}`, {
    method: "POST",
    body: form,
  });

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      detail = j.detail ?? detail;
    } catch {
      /* 非 JSON 錯誤，沿用狀態碼 */
    }
    throw new Error(detail);
  }

  const j = await res.json();
  return {
    width: j.width,
    height: j.height,
    numLayers: j.num_layers,
    rgbUrl: j.rgb,
    depthUrl: j.depth,
    bgUrl: j.bg,
    layers: (j.layers as any[]).map((l) => ({
      color: l.color,
      depth: l.depth,
      alpha: l.alpha,
      depthMin: l.depth_min,
      depthMax: l.depth_max,
    })),
  };
}
