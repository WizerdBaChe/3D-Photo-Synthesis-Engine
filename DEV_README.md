# 開發者與維護者指南 (DEV_README)

**版本：** Web v2.0 · **架構：** FastAPI 後端 + Vite/TS/Three.js 前端

> 使用者導向的說明請見 [README.md](README.md)。本檔為架構、API、測試、擴充與部署的工程文件。

---

## 1. 架構總覽

```text
┌─────────────────────────┐      HTTP (multipart 上傳 / .glb 下載)      ┌──────────────────────────┐
│  前端 frontend/          │  ───────────────────────────────────────▶  │  後端 backend/ (FastAPI)   │
│  Vite + TS + Three.js    │                                            │                          │
│  ・上傳 RGB + Depth       │   POST /synthesize ─────────────────────▶  │  rgbd_loader (解碼/對齊)   │
│  ・GLTFLoader 載入 .glb   │                                            │  Orchestrator (合成管線)   │
│  ・OrbitControls 旋轉視角 │  ◀───────────────────────────────────────  │  gltf_export (.glb 序列化) │
│  （渲染全在瀏覽器 WebGL） │            model/gltf-binary               │  （純 NumPy，無 GUI）      │
└─────────────────────────┘                                            └──────────────────────────┘
                                                                                    │ 複用
                                                                          ┌──────────────────────────┐
                                                                          │  src/core/ 核心計算層      │
                                                                          │  GeometryProcessor         │
                                                                          │  SobelEdgeDetector         │
                                                                          │  TeleaInpainter            │
                                                                          │  契約 DTO（含 MeshData）   │
                                                                          └──────────────────────────┘
```

**設計重點**：渲染與視角互動全在前端 WebGL，後端只負責「RGB-D → 3D 網格」計算並回傳 `.glb`。
後端無狀態、無 GUI、無 Open3D、無子進程，可水平擴展與容器化。

## 2. 合成管線

```text
RGB 圖 + Depth 圖（前端上傳）
   ▼ rgbd_loader.load_rgbd_from_bytes        解碼、深度正規化 [0,1]、解析度對齊
RGBDFrame (DTO)
   ▼ SobelEdgeDetector.compute_mask          百分位動態閾值 → 斷崖遮罩
   ▼ TeleaInpainter.fill                     RGB+Depth 雙修補（含防尖刺裁切；LaMa OOM 時降級至此）
   ▼ GeometryProcessor.unproject_to_points   反投影（depth_near/far 視差尺度）
   ▼ GeometryProcessor.build_topology        向量化建面 + 斷崖剔除 → MeshData（純 NumPy）
   ▼ gltf_export.mesh_to_glb                 序列化為 .glb
.glb（前端 Three.js GLTFLoader 載入並渲染）
```

## 3. 檔案結構

```text
3D_Photo_Synthesis_Engine/
├── backend/                   # FastAPI 後端
│   ├── app.py                 #   FastAPI app + /synthesize 端點
│   ├── rgbd_loader.py         #   RGB-D 解碼 / 正規化 / 內參估算
│   └── gltf_export.py         #   MeshData → .glb 序列化
│
├── src/                       # 平台無關核心（後端複用，無 Open3D 依賴）
│   ├── core/
│   │   ├── contracts.py       #   RGBDFrame, CameraIntrinsics, MeshData
│   │   ├── policies.py        #   EdgeDetectionPolicy + SobelEdgeDetector
│   │   ├── geometry.py        #   GeometryProcessor（反投影 + 建面，純 NumPy）
│   │   └── inpainting.py      #   AbstractInpainter, TeleaInpainter, LaMaInpainter(佔位)
│   └── app/
│       └── orchestrator.py    #   合成管線協調（含 OOM 降級），回傳 MeshData
│
├── frontend/                  # Vite + TS + Three.js 前端
│   ├── index.html
│   ├── src/{main,viewer,api}.ts
│   └── package.json
│
├── tests/                     # pytest（unit + integration）
│   ├── unit/{test_geometry,test_inpainting_telea}.py
│   └── integration/{test_orchestrator_fallback,test_backend_api}.py
│
├── archive/                   # 已封存的桌面版（PySide6 + Open3D）— 見 archive/README.md
├── requirements.txt
└── engine.bat                 # 前後端總控腳本
```

## 4. 開發環境 — `engine.bat`

| 指令 | 功能 |
|------|------|
| `engine.bat install` | 建立 `.venv` + 裝後端依賴 + 前端 `npm install` |
| `engine.bat repair` | 檢查/修復環境（系統 Python、.venv 依賴、核心 import、前端 node_modules），缺什麼補什麼 |
| `engine.bat run` | 開發模式：分別開啟「後端」「前端」兩個獨立 console（各自顯示錯誤狀態） |
| `engine.bat backend` | 只啟動後端（FastAPI :8000） |
| `engine.bat frontend` | 只啟動前端（Vite :5173） |
| `engine.bat test` | 後端 pytest + 前端 build typecheck |
| `engine.bat clean` | 刪除 `.venv` / `node_modules` / `dist` |

無參數執行會顯示互動選單。後端 API 文件（Swagger）：http://127.0.0.1:8000/docs。

> Python 環境為專案內的 `.venv`（已加入 `.gitignore`）。開發模式下，前端 `/api` 會自動 proxy
> 到後端 `:8000`（見 `frontend/vite.config.ts`）；部署時設 `VITE_API_BASE` 指向實際後端網域。

### 手動指令（跨平台）

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt           # Linux/mac: .venv/bin/pip
.venv/Scripts/python -m uvicorn backend.app:app --reload

cd frontend && npm install && npm run dev
```

## 5. API

### `POST /synthesize`

| 參數 | 型別 | 說明 |
|------|------|------|
| `rgb` | file (multipart) | RGB 彩色圖（PNG/JPG）|
| `depth` | file (multipart) | 深度圖（PNG 8/16bit、TIFF）|
| `percentile` | query float | Sobel 斷邊百分位（預設 95，範圍 0–100）|
| `fov_deg` | query float | 水平 FOV（預設 60）|
| `depth_near` / `depth_far` | query float | 視差強度近/遠平面（預設 1.0 / 4.0；須 far > near）|

**回應**：`model/gltf-binary`（.glb 二進位），標頭含 `X-Vertex-Count` / `X-Face-Count`。
**錯誤**：壞影像 / 缺欄位 / `depth_far <= depth_near` → `422`；管線例外 → `500`。

### `GET /`
健康檢查，回傳 `{"status":"ok", ...}`。

## 6. 測試

```bash
engine.bat test                                # 後端 pytest + 前端 build（一次跑完）
# 或手動：
.venv/Scripts/python -m pytest tests/unit tests/integration -v   # 46 passed
cd frontend && npm run build                   # 前端 typecheck + build
```

測試分層：
- **unit**（`tests/unit/`）：純函數數學正確性（反投影、深度尺度、建面、斷邊、Telea 修補）。
- **integration**（`tests/integration/`）：Orchestrator OOM 降級、`/synthesize` 端點（含 .glb 結構驗證）。

## 7. 設計沿襲與決策

- 本 Web 架構**符合原始 PIM §10 設計本意**（「Rendering Engine 可映射為 WebGL/Three.js」「I/O 對接 DOM 事件」），非架構漂移。
- 桌面版（PySide6 + Open3D 子進程）已封存於 [archive/](archive/README.md)，核心 `src/core/` 被後端直接複用（約 60% 程式碼）。
- 完整缺陷修正與架構決策紀錄見 [docs/重製注意事項.md](docs/重製注意事項.md)。

## 8. 擴充與部署

### 擴充點（OCP，無需改動其他層）
- **新增邊緣策略**：繼承 `EdgeDetectionPolicy`，實作 `compute_mask()`。
- **新增修補策略**：繼承 `AbstractInpainter`，實作 `fill()`。
- **LaMa AI 修補**：補完 `src/core/inpainting.py` 的 `LaMaInpainter`（`_load_model` / `_run_inference`）；OOM 降級路徑（`VRAMExhaustedError`）已就緒。

### 部署
- 後端為標準 ASGI app（`backend.app:app`），可用 `uvicorn` / `gunicorn -k uvicorn.workers.UvicornWorker` 部署，亦可容器化。
- 前端 `npm run build` 產出靜態檔（`frontend/dist/`），可放任意靜態主機 / CDN；以 `VITE_API_BASE` 指向後端網域。
- 生產環境請收斂 `backend/app.py` 的 CORS `allow_origins` 為實際前端網域。

## 9. 已知限制

- **LaMa AI 修補**為架構佔位（`fill()` 拋 `NotImplementedError`），目前主修補器為 Telea。
- **相機內參**以 FOV 60° 估算，可由 `/synthesize` 的 `fov_deg` 覆寫，未來可改從 EXIF 讀取。
- **深度圖**假設已與彩色圖對齊（同視角）；未處理立體校正。
