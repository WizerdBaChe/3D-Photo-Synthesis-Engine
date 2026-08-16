# 開發者與維護者指南 (DEV_README)

**版本：** Web v2.0 · **架構：** FastAPI 後端 + Vite/TS/Three.js 前端
**專案狀態：** 已結案 2026-08-16（見 [CLAUDE.md](CLAUDE.md) 頂端；不再新增功能）

> 使用者導向的說明請見 [README.md](README.md)。本檔為架構、API、測試、擴充與部署的工程文件。

---

## 1. 架構總覽

三條路徑並存，**預設是最輕的那條**。後端無狀態、無 GUI、無 Open3D、無子進程。

```text
┌──────────────────────────────┐                              ┌────────────────────────────┐
│  前端 frontend/               │   POST /parallax  ────────▶  │  後端 backend/ (FastAPI)    │
│  Vite + TS + Three.js         │   ◀──── {rgb,depth} PNG      │                            │
│                               │                              │  rgbd_loader  解碼/正規化/  │
│  parallax.ts  視差（預設）     │   POST /ldi       ────────▶  │               對齊/語意判定  │
│  ldi.ts       LDI 分層         │   ◀──── {rgb,depth,bg,      │  depth_estimator（NoOp）    │
│  viewer.ts    mesh + GLTF      │          layers[]}           │  src/core/ldi  LDIBuilder   │
│                               │                              │  Orchestrator  合成管線      │
│  （渲染全在瀏覽器 WebGL）      │   POST /synthesize ───────▶  │  gltf_export   .glb 序列化   │
│                               │   ◀──── model/gltf-binary    │  （純 NumPy，無 GUI）       │
└──────────────────────────────┘                              └────────────────────────────┘
                                                                          │ 複用
                                                              ┌────────────────────────────┐
                                                              │  src/core/ 核心計算層        │
                                                              │  GeometryProcessor           │
                                                              │  DepthDiscontinuityPolicy    │
                                                              │  DepthAwareInpainter (C1)    │
                                                              │  LDIBuilder + Provider       │
                                                              │  契約 DTO（MeshData/LDIScene）│
                                                              └────────────────────────────┘
```

**設計重點**：渲染與視角互動全在前端 WebGL。新模式一律「新端點 + 新前端檔案」，
既有路徑一行不動——LDI 整條路線在品質上失敗時，視差模式一個位元都沒被弄髒。

## 2. 三條合成管線

### 2.1 `/parallax`（預設，最輕）

```text
RGB (+ 選填 Depth)
   ▼ rgbd_loader.load_rgbd_from_bytes    解碼、depth 語意判定(auto)、正規化 [0,1]、對齊
   ▼ （無 depth 時）DepthEstimator        預設 NoOp → 422
{width, height, rgb, depth}  兩張 base64 PNG（約 1.9 MB）
   ▼ 前端 ParallaxViewer                 正交相機 + quad + 位移 shader
offset = uMouse * (0.5 - depth) * uIntensity * 邊界衰減
```

### 2.2 `/ldi`（實驗，品質未達目標）

```text
RGB + Depth
   ▼ 同上載入
   ▼ LDIBuilder（src/core/ldi.py）        depth 分位數切帶分層；背景層破洞用 C1 預填
{rgb, depth, bg, layers[]}
   ▼ 前端 LDIViewer                       仍是連續位移；取樣落進破洞時改取預填背景
```

### 2.3 `/synthesize`（mesh 匯出，Phase 1/2 的成果）

```text
RGB + Depth
   ▼ rgbd_loader                          同上
   ▼ DepthDiscontinuityPolicy.compute_mask  絕對深度差為主 + Sobel refinement（可關）
   ▼ DepthAwareInpainter.fill             C1：DIBR 只取背景排前景；失敗退 TeleaInpainter
   ▼ GeometryProcessor.unproject_to_points 反投影（glTF 右手系：+Y 上、+Z 朝觀者）
   ▼ GeometryProcessor.build_topology      向量化建面 + 斷崖剔除 + 3D 邊長剔除(Step 5b)
   ▼ gltf_export.mesh_to_glb
.glb（約 30 MB）
```

> 斷崖遮罩**一律在修補後的 depth 上重算**；`frame.mask` 只保留「破洞修補」語意。
> 兩者混用是 Phase 1 修掉的 bug。

## 3. 檔案結構

```text
3D_Photo_Synthesis_Engine/
├── backend/                   # FastAPI 後端
│   ├── app.py                 #   /、/synthesize、/parallax、/ldi + _acquire_color_depth
│   ├── rgbd_loader.py         #   解碼 / depth 語意判定 / 正規化 / 內參估算
│   ├── depth_estimator.py     #   DepthEstimator 抽象 + NoOp + get/set provider（無模型）
│   └── gltf_export.py         #   MeshData → .glb
│
├── src/                       # 平台無關核心（後端複用，無 Open3D 依賴）
│   ├── core/
│   │   ├── contracts.py       #   RGBDFrame, CameraIntrinsics, MeshData, LDILayer, LDIScene
│   │   ├── policies.py        #   EdgeDetectionPolicy + SobelEdgeDetector(legacy)
│   │   │                      #   + DepthDiscontinuityPolicy（預設）
│   │   ├── geometry.py        #   GeometryProcessor（反投影 + 建面 + 邊長剔除）
│   │   ├── inpainting.py      #   AbstractInpainter, TeleaInpainter,
│   │   │                      #   DepthAwareInpainter(C1, 現行 primary), LaMaInpainter(佔位)
│   │   └── ldi.py             #   AbstractLDIBuilder + LDIBuilder + get/set_ldi_builder
│   └── app/
│       └── orchestrator.py    #   合成管線協調（含 OOM 降級），回傳 MeshData
│
├── frontend/                  # Vite + TS + Three.js
│   ├── index.html
│   ├── public/samples/        #   內建測試圖 RGB_TEST.jpg + DEPTH_TEST.png
│   └── src/
│       ├── main.ts            #   模式切換 parallax|ldi|mesh、UI 綁定、viewport 管理
│       ├── api.ts             #   synthesize() / parallax() / ldi()
│       ├── parallax.ts        #   ParallaxViewer（預設模式）
│       ├── ldi.ts             #   LDIViewer（多層取樣）
│       └── viewer.ts          #   mesh viewer（GLTFLoader，可選 OrbitControls）
│
├── scripts/inspect_pipeline.py  # 診斷 CLI：dump 中間產物（不在端點加 debug 分支）
├── tests/                     # pytest（unit + integration），100 passed
├── references/                # 本專案的 phase log 與各 Phase 詳細紀錄
├── docs/                      # ADR + LDI 檢討報告
├── archive/                   # 已封存的桌面版（PySide6 + Open3D）— 見 archive/README.md
├── requirements.txt
└── engine.bat                 # 前後端總控腳本
```

> `spike/`（3DGS 探索，結論 no-go）在 `.gitignore` 中，不進版本控制。

## 4. 開發環境 — `engine.bat`

| 指令 | 功能 |
|------|------|
| `engine.bat install` | 建立 `.venv` + 裝後端依賴 + 前端 `npm install` |
| `engine.bat repair` | 檢查/修復環境（系統 Python、.venv 依賴、核心 import、node_modules） |
| `engine.bat run` | 開發模式：分別開啟「後端」「前端」兩個獨立 console |
| `engine.bat backend` | 只啟動後端（FastAPI :8000） |
| `engine.bat frontend` | 只啟動前端（Vite :5173） |
| `engine.bat test` | 後端 pytest + 前端 build typecheck |
| `engine.bat clean` | 刪除 `.venv` / `node_modules` / `dist` |

無參數執行會顯示互動選單。Swagger：http://127.0.0.1:8000/docs。

> **改後端一定要重啟**（或靠 `--reload`），並 curl 驗新欄位再請人測。
> 維持**單一** uvicorn 實例——孤兒 `--reload` 程序會佔住 :8000，
> 而且 PID 被砍掉後 `Get-NetTCPConnection` 還會顯示它在 listening。

### 手動指令

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt           # Linux/mac: .venv/bin/pip
.venv/Scripts/python -m uvicorn backend.app:app --reload

cd frontend && npm install && npm run dev
```

## 5. API

三個端點共用 multipart 上傳與 `depth_convention` 深度語意判定。

### `POST /parallax` — 預設輕量路徑

| 參數 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `rgb` | file | — | RGB 彩色圖（PNG/JPG）|
| `depth` | file | **選填** | 深度圖；未提供時呼叫 `DepthEstimator`（預設 NoOp → 422）|
| `max_pixels` | query int | 2,000,000 | 影像像素上限，0 = 停用 |
| `depth_convention` | query str | `auto` | `auto` \| `disparity` \| `metric` |

**回應**：`{width, height, rgb, depth}`，`rgb`/`depth` 為 `data:image/png;base64`。

### `POST /ldi` — 分層補洞（實驗）

參數同 `/parallax`，另加 `num_layers`（query int，預設 2，範圍 2–3）；`depth` 為必填。
**回應**：`{rgb, depth, bg, layers[]}`，`layers` 由近到遠，最遠層 alpha 全 255。

### `POST /synthesize` — mesh 匯出

| 參數 | 型別 | 預設 | 說明 |
|------|------|------|------|
| `rgb` / `depth` | file | — | 皆必填 |
| `percentile` | query float | 95.0 | legacy Sobel 斷邊百分位（僅 `edge_policy=sobel` 時有意義）|
| `fov_deg` | query float | 60.0 | 水平 FOV |
| `depth_near` / `depth_far` | query float | 1.0 / 4.0 | 視差強度近/遠平面（須 far > near）|
| `max_pixels` | query int | 500,000 | 網格頂點上限（H×W），0 = 停用 |
| `depth_convention` | query str | `auto` | 同上 |
| `edge_policy` | query str | `discontinuity` | `discontinuity`（預設）\| `sobel`（legacy）|
| `max_edge_ratio` | query float | 30.0 | 3D 邊長剔除門檻（×中位邊長）；設很大值等於關閉 |

**回應**：`model/gltf-binary`，標頭含 `X-Vertex-Count` / `X-Face-Count`。
**錯誤**：壞影像 / 缺欄位 / `depth_far <= depth_near` / 無 depth 且估算器未啟用 → `422`；管線例外 → `500`。

### `GET /`
健康檢查，回傳 `{"status":"ok", ...}`。

## 6. 測試

```bash
engine.bat test                                # 後端 pytest + 前端 build（一次跑完）
# 或手動：
.venv/Scripts/python -m pytest tests/unit tests/integration -q   # 100 passed
cd frontend && npm run build                   # 前端 typecheck + build
```

測試分層：
- **unit**（`tests/unit/`）：反投影數學、深度語意與 auto 啟發式、建面、邊長剔除、
  Telea 與 C1 修補、LDI 分層。
- **integration**（`tests/integration/`）：Orchestrator OOM 降級、三個端點
  （含 `.glb` 結構驗證、`/parallax` 的 NoOp 422、`/ldi` 的層數與 alpha 檢查）。

> **前端沒有單元測試框架**：`parallax.ts` / `ldi.ts` / `viewer.ts` 只有 `tsc` + `vite build`
> 把關。綠色的 build 只證明型別對得上，不證明畫面是對的——渲染改動一律需要人眼驗收。

### 診斷工具

```bash
.venv/Scripts/python scripts/inspect_pipeline.py --rgb samples/RGB_TEST.jpg \
    --depth samples/DEPTH_TEST.png --max-edge-ratio 30
```

dump 正規化深度、斷崖遮罩疊圖、修補後深度、3D 邊長統計 JSON 到 `debug_out/`。
**刻意不在端點加 debug 分支**——最小資源、與請求路徑解耦、可離線跑。

## 7. 設計沿襲與決策

- 本 Web 架構符合原始 PIM §10 的設計本意（Rendering Engine 可映射為 WebGL/Three.js），非架構漂移。
- 桌面版（PySide6 + Open3D 子進程）已封存於 [archive/](archive/README.md)，
  核心 `src/core/` 被後端直接複用。
- `docs/ADR.md` 的 **DD-001～DD-007**（無狀態分層、NumPy 向量化、策略模式、
  嚴格資料契約、分位數閾值、RGB+Depth 雙修補）在 Web 版**續用且有效**。
  **DD-008～DD-011（VRAM 雙模式、GUI 解耦、PySide6、嵌入式部署）已隨桌面版失效**，
  只作歷史參照。
- 桌面→Web 的遷移修正清單已封存：[archive/docs/重製注意事項.md](archive/docs/重製注意事項.md)。
- LDI 路線的完整檢討：[docs/LDI_retrospective.md](docs/LDI_retrospective.md)。

## 8. 擴充與部署

### 擴充點（OCP，無需改動其他層）
- **新增邊緣策略**：繼承 `EdgeDetectionPolicy`，實作 `compute_mask()`。
- **新增修補策略**：繼承 `AbstractInpainter`，實作 `fill()`。
- **接自動估深**：實作 `DepthEstimator`，`set_depth_estimator()` 注入；端點與前端不動。
- **換更強的分層/補繪**：實作 `AbstractLDIBuilder`，`set_ldi_builder()` 注入。
  **這是本專案最有價值的注入點**——最終結論是「唯一要換的零件是補繪器」。
- 重依賴（torch / LaMa / diffusion）一律**選用安裝 + lazy import + 失敗退回**，
  絕不進 `requirements.txt`。

### 部署
- 後端為標準 ASGI app（`backend.app:app`），可 `uvicorn` / `gunicorn -k uvicorn.workers.UvicornWorker`，
  亦可容器化。
- 前端 `npm run build` 產出 `frontend/dist/`，可放任意靜態主機 / CDN；
  以 `VITE_API_BASE` 指向後端網域。
- 生產環境請收斂 `backend/app.py` 的 CORS `allow_origins` 為實際前端網域。

## 9. 已知限制

- **大面積遮擋補不動**：C1（`DepthAwareInpainter`）對超大洞（整張床級別）會糊成放射狀條紋。
  這是專案的根因瓶頸，也是 LDI 路線失敗的直接原因。
- **架構天花板**：單張 depth map 位移 + 補洞本質只能做小幅變形，被遮擋內容無法真正還原。
  要突破得換補繪器（LaMa/diffusion）或換表示法（3DGS），**不是調 shader**。
- **`max_edge_ratio=30` 只在單一測試圖上校準**，其他深度尺度/構圖未驗證；過度剔除會在
  真實深邊界留洞。
- **`depth_convention=auto` 的門檻**（`high_frac 0.35`、`skew>0`）同樣只有少量樣本，
  且第一版寫反過。深度看起來相反時先懷疑這裡。
- **`LaMaInpainter` 是架構佔位**（`fill()` 拋 `NotImplementedError`）。
- **`DepthEstimator` 是 NoOp**，未接任何模型。
- **相機內參**以 FOV 60° 估算，可由 `/synthesize` 的 `fov_deg` 覆寫；未從 EXIF 讀取。
- **深度圖假設已與彩色圖對齊**（同視角），未處理立體校正。
- **玻璃 / 半透明**區域的 depth 本身不可靠，殘影屬本質限制。
