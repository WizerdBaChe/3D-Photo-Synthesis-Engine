# 3D Photo Synthesis Engine

**版本：** MVP v1.0 · **架構文件版本：** 設計稿 v1.0 (2026-05-27)

從一對 RGB + 深度圖，在本機端即時合成可互動的 3D 場景。無需雲端、無需伺服器，所有運算在本機 CPU/GPU 完成。

---

## 目錄

1. [專案概覽](#1-專案概覽)
2. [系統架構](#2-系統架構)
3. [檔案結構](#3-檔案結構)
4. [模組說明](#4-模組說明)
5. [安裝與環境需求](#5-安裝與環境需求)
6. [快速啟動](#6-快速啟動)
7. [驗證測試](#7-驗證測試)
8. [設計決策紀錄 (ADR)](#8-設計決策紀錄-adr)
9. [架構強制規範](#9-架構強制規範)
10. [MVP 限制與擴充路線](#10-mvp-限制與擴充路線)

---

## 1. 專案概覽

### 功能

| 功能 | MVP 狀態 | 說明 |
|------|----------|------|
| RGB-D 圖片載入 | ✅ 完成 | 支援 PNG / JPG / EXR / TIFF 深度圖 |
| Sobel 動態斷邊偵測 | ✅ 完成 | 百分位數自適應閾值，場景無關 |
| Telea CPU 遮擋修補 | ✅ 完成 | RGB + Depth 雙重修補，< 1.0s @ 1080p |
| 向量化三角網格建構 | ✅ 完成 | NumPy 廣播，無 Python 迴圈 |
| Open3D 獨立渲染進程 | ✅ 完成 | 子進程隔離，主進程 GUI 不卡頓 |
| PySide6 視角滑桿控制 | ✅ 完成 | Euler 角 → 4×4 外參矩陣，即時更新 |
| LaMa AI 修補 | 🔲 架構佔位 | 骨架已預留，整合步驟詳見 §10 |
| OOM 自動降級 | ✅ 完成 | LaMa OOM → 自動切回 Telea，不閃退 |

### 目標硬體

- CPU：Intel Core i5 第 10 代或以上
- GPU：NVIDIA RTX 3060 12GB 或同等（LaMa 修補時使用；MVP 階段可無 GPU）
- OS：Windows 10/11（已針對 Windows `spawn` 多進程模式設計）

---

## 2. 系統架構

### 進程邊界

```
┌─────────────────────────────────────────────────────┐
│  主進程 (Main Process)                               │
│                                                     │
│  ┌──────────────┐    Signal    ┌─────────────────┐  │
│  │  MainWindow  │ ──────────▶ │ SynthesisWorker │  │
│  │  (PySide6)   │ ◀────────── │  (QThread)      │  │
│  │  View is     │   Signal    │  Orchestrator   │  │
│  │  Dumb        │             │  GeometryProc.  │  │
│  └──────┬───────┘             │  TeleaInpaint.  │  │
│         │ InputAdapter        └────────┬────────┘  │
│         │ (Euler→Matrix)               │            │
│         ▼                             │            │
│  ┌──────────────┐              multiprocessing     │
│  │ command_queue│              .Queue (IPC)        │
│  │ pose_queue   │◀────────────────────┘            │
└──────────┬──────────────────────────────────────────┘
           │ multiprocessing.Queue
           │ (MeshLoadCommand / CameraPoseCommand)
           ▼
┌─────────────────────────────────────────────────────┐
│  子進程 (Sub-Process)                                │
│  Open3DRenderWorker                                 │
│  ・open3d.visualization.Visualizer                  │
│  ・從 .ply 暫存檔讀取 TriangleMesh                   │
│  ・Latest-Wins 位姿更新策略                           │
└─────────────────────────────────────────────────────┘
```

### 模組分層

```
┌─────────────────────────────────────────────────────────┐
│  Layer 0 — View (gui/)                                  │
│  MainWindowView · SynthesisWorker                       │
│  規則：禁止 import src.core.*，只觸發 Signal              │
├─────────────────────────────────────────────────────────┤
│  Layer 1 — Application (src/app/)                       │
│  Orchestrator · RenderProcessController                 │
│  InputAdapter · Command DTOs                            │
│  規則：協調流程，不持有影像或網格狀態                        │
├─────────────────────────────────────────────────────────┤
│  Layer 2 — Core (src/core/)                             │
│  GeometryProcessor · AbstractInpainter                  │
│  EdgeDetectionPolicy · Data Contracts (DTO)             │
│  規則：純函數 / 無狀態物件，只吃 DTO 吐 DTO               │
└─────────────────────────────────────────────────────────┘
```

### 合成管線流程

```
RGB 圖片 + Depth 圖片
        │
        ▼ (SynthesisWorker._load_rgbd)
   RGBDFrame (DTO)
        │
        ▼ (SobelEdgeDetector.compute_mask)
   frame.mask ← 斷崖位置布林遮罩
        │
        ▼ (TeleaInpainter.fill  ← 若 LaMa OOM 則自動降級至此)
   repaired RGBDFrame（color + depth 已填補，mask=None）
        │
        ▼ (GeometryProcessor.unproject_to_points)
   points: ndarray (H*W, 3)
        │
        ▼ (GeometryProcessor.build_topology)
   TriangleMesh（含頂點色、法線）
        │
        ▼ (Orchestrator._save_mesh_to_tempfile)
   synthesis_mesh_XXXX.ply  ← 暫存檔（不走 Queue 傳 Mesh 物件）
        │
        ▼ (RenderProcessController.load_mesh → IPC Queue)
   Open3DRenderWorker 讀取並渲染
```

---

## 3. 檔案結構

```
3D_Synthesis_Engine/
│
├── main.py                        # 應用程式進入點
├── requirements.txt               # 套件依賴清單
├── setup_structure.bat            # 目錄初始化腳本（首次執行）
│
├── src/
│   ├── core/                      # 核心無狀態層（Layer 2）
│   │   ├── contracts.py           # 資料契約 DTO：RGBDFrame, CameraIntrinsics, CameraPoseUpdate
│   │   ├── policies.py            # 邊緣策略介面 + SobelEdgeDetector
│   │   ├── geometry.py            # GeometryProcessor（反投影 + 拓樸建立）
│   │   └── inpainting.py          # AbstractInpainter, TeleaInpainter, LaMaInpainter（佔位）
│   │
│   └── app/                       # 應用協調層（Layer 1）
│       ├── commands.py            # 指令 DTO：EngineCommand, MeshLoadCommand, CameraPoseCommand
│       ├── orchestrator.py        # 管線協調器（含 OOM 降級）
│       ├── render_ipc.py          # 渲染子進程 + RenderProcessController
│       └── adapter.py             # InputAdapter（GUI 事件 → 矩陣 → Queue）
│
├── gui/                           # 前端 View 層（Layer 0）
│   ├── main_window.py             # PySide6 主視窗（View is Dumb）
│   └── worker.py                  # SynthesisWorker（QThread，背景 AI 運算）
│
└── tests/
    ├── conftest.py                # pytest 共用 Fixtures（合成資料）
    ├── unit/
    │   ├── test_geometry.py       # 幾何處理器單元測試（反投影 + 斷邊）
    │   └── test_inpainting_telea.py  # Telea 修補器單元測試
    ├── integration/
    │   ├── test_orchestrator_fallback.py  # OOM 降級整合測試
    │   └── test_render_ipc.py            # IPC 佇列與進程管理測試
    └── benchmark/
        └── run_benchmarks.py      # 端到端效能基準測試（SLA 驗證）
```

---

## 4. 模組說明

### `src/core/contracts.py` — 資料契約

所有跨模組傳輸的資料必須以這裡定義的 `@dataclass` 封裝，禁止直接傳裸 `ndarray`。

| DTO | 欄位 | 用途 |
|-----|------|------|
| `RGBDFrame` | `color (H,W,3) uint8` · `depth (H,W) float32` · `mask (H,W) bool_` | 管線核心資料單元，`__post_init__` 強制驗證維度一致 |
| `CameraIntrinsics` | `fx, fy, cx, cy, width, height` | 相機針孔模型內參，`frozen=True` |
| `CameraPoseUpdate` | `extrinsic_matrix (4,4) float64` · `timestamp` | IPC 位姿更新 DTO |

### `src/core/policies.py` — 邊緣策略

以策略模式（Strategy Pattern）封裝斷邊演算法，`GeometryProcessor` 在初始化時注入，新增演算法無需修改幾何引擎（開閉原則）。

| 類別 | 機制 | 參數 |
|------|------|------|
| `EdgeDetectionPolicy` | ABC 抽象介面 | — |
| `SobelEdgeDetector` | Sobel 梯度 + 百分位數動態閾值 | `percentile=95.0` |

### `src/core/geometry.py` — 幾何處理器

| 方法 | 輸入 | 輸出 | 複雜度 |
|------|------|------|--------|
| `unproject_to_points` | `depth (H,W) float32` | `points (H*W,3) float64` | O(H×W)，純 NumPy 廣播 |
| `build_topology` | `points (H*W,3)` + `RGBDFrame` | `o3d.TriangleMesh` | O(H×W)，向量化切片索引 |

### `src/core/inpainting.py` — 修補服務

| 類別 | 後端 | 狀態 | 備注 |
|------|------|------|------|
| `AbstractInpainter` | ABC | — | 定義 `fill(RGBDFrame) → RGBDFrame` 介面 |
| `TeleaInpainter` | OpenCV FMM | ✅ 可用 | RGB + Depth 雙重修補，無需 GPU |
| `LaMaInpainter` | PyTorch (LaMa) | 🔲 佔位 | 骨架完整，`fill()` 待接入模型權重 |

### `src/app/orchestrator.py` — 管線協調器

```
process_and_render(frame)
  ├── 邊緣偵測 → frame.mask
  ├── _inpaint_with_fallback()
  │     ├── primary_inpainter.fill()
  │     └── [OOM] → torch.cuda.empty_cache() → fallback_inpainter.fill()
  ├── unproject_to_points() + build_topology()
  └── _save_mesh_to_tempfile() → render_controller.load_mesh(path)
```

### `src/app/render_ipc.py` — 獨立渲染管線

- **`Open3DRenderWorker`**：子進程中運行，管理 `o3d.visualization.Visualizer` 的完整生命週期。
- **`RenderProcessController`**：主進程側介面，封裝所有 IPC 細節。
  - `update_camera()` 採用 **Latest-Wins** 策略：在 `put` 前清空佇列中的舊位姿指令，防止高頻拖曳時佇列堆積。
  - `terminate()` 先發 `ShutdownCommand`，等待 5 秒，超時才強制 `terminate()`，確保無殭屍進程。

### `src/app/adapter.py` — 輸入適配器

| 方法 | GUI 事件 | 翻譯結果 |
|------|----------|----------|
| `on_load_files_requested` | 檔案對話框選取 | `EngineCommand(LOAD_IMAGE)` → `command_queue` |
| `on_rotation_slider_changed` | Pitch/Yaw/Roll 滑桿 | `Rz@Ry@Rx` → 4×4 外參矩陣 → `CameraPoseUpdate` → `pose_queue` |
| `on_start_synthesis_requested` | 按鈕點擊 | `EngineCommand(START_SYNTHESIS)` → `command_queue` |

---

## 5. 安裝與環境需求

### Python 版本

Python 3.10 或以上（建議 3.11）

### 套件安裝

```bash
pip install -r requirements.txt
```

`requirements.txt` 內容：

```
numpy>=1.24.0
opencv-python>=4.8.0
open3d>=0.17.0
PySide6>=6.5.0
pytest>=7.4.0
pytest-timeout>=2.1.0
```

> LaMa 整合時額外需要：`torch>=2.0.0`、`torchvision>=0.15.0`。`requirements.txt` 中已預留但以 `#` 註解。

### Windows 免安裝環境（Portable）

若使用類似 ComfyUI\_portable 的嵌入式 Python：

1. 將專案根目錄置於 `python_embeded\` 的同層。
2. 使用 `run_tests.bat` 執行測試（自動設定 `PYTHONPATH`）。
3. 使用 `run_app.bat` 啟動應用程式。

所有路徑引用均為相對路徑，不依賴系統全域環境變數。

---

## 6. 快速啟動

### 啟動 GUI

```bash
# 從專案根目錄執行
python main.py
```

### 操作流程

1. 點擊「RGB 圖片 → 瀏覽…」，選取彩色圖片（`.png` / `.jpg`）。
2. 點擊「Depth 圖片 → 瀏覽…」，選取深度圖（`.png` 16bit / `.exr`）。
3. 點擊「▶ 開始 3D 合成」。
4. 進度條完成後，Open3D 渲染視窗自動彈出。
5. 拖曳 Pitch / Yaw / Roll 滑桿即時旋轉視角。

### 深度圖格式說明

| 格式 | 位元深度 | 正規化方式 |
|------|----------|------------|
| PNG 8-bit | 0–255 | ÷ 255 → [0,1] |
| PNG 16-bit | 0–65535 | ÷ 65535 → [0,1] |
| EXR 32-bit float | 直接讀取 | 若最大值 > 1 則÷最大值 |

RGB 與 Depth 解析度不一致時，系統自動雙線性插值對齊，並輸出警告至 console。

---

## 7. 驗證測試

### 測試層架構

```
階層一（Unit）      ── 純函數數學正確性，禁止啟動 GUI 或 GPU，< 1s / test
階層二（Integration）── 跨模組 IPC 與 OOM 降級，允許輕量 mock
階層三（Benchmark）  ── 真實硬體 SLA 驗證，需完整環境
```

### 執行測試

```bash
# 執行全部單元 + 整合測試
pytest tests/unit tests/integration -v

# 執行單一測試類別
pytest tests/unit/test_geometry.py -v

# 執行效能基準（需完整硬體環境）
python tests/benchmark/run_benchmarks.py
```

### 效能 SLA（階層三門檻）

| 指標 | 測試條件 | 合格門檻 |
|------|----------|----------|
| 幾何預處理 | 1080p 圖片 | < 0.5 秒 |
| Telea 修補 | 1080p 圖片 | < 1.0 秒 |
| LaMa 推論（常駐） | 1080p，模型已在 VRAM | < 3.0 秒 |
| LaMa 推論（Lazy） | 含模型載入 + 釋放 | < 6.0 秒 |
| 渲染互動幀率 | 連續 60 個旋轉矩陣 | ≥ 30 FPS |

任一指標低於門檻 80% 將標記為 `PERFORMANCE_REGRESSION`。

---

## 8. 設計決策紀錄 (ADR)

| 決策 ID | 決策主題 | 選擇 | 原因摘要 |
|---------|----------|------|----------|
| DD-001 | 模組狀態性 | 無狀態 | 避免並行競態、方便測試 |
| DD-002 | 幾何運算方式 | NumPy 向量化 | 避免 Python 迴圈效能瓶頸 |
| DD-003 | 跨模組通訊 | Queue + DTO | 解耦模組邊界，可測試可替換 |
| DD-004 | 資料型別規範 | `@dataclass` + Shape 註解 | 防止裸 ndarray 引發隱性 bug |
| DD-005 | 斷邊演算法擴充 | 策略模式 (Strategy) | 不修改幾何引擎即可替換演算法 |
| DD-006 | 斷邊閾值 | 百分位數動態計算 | 場景自適應，無需手動調參 |
| DD-007 | 修補範圍 | RGB + Depth 雙重修補 | 單修 RGB 會導致 3D 幾何破洞不合理 |
| DD-008 | 顯存管理 | Persistent / Lazy 雙模式 + OOM 降級 | 平衡效能與 8GB VRAM 限制 |
| DD-009 | GUI 與引擎耦合 | InputAdapter + Queue 完全解耦 | GUI 只觸發 Signal，核心不知 PySide6 |
| DD-010 | GUI 框架 | PySide6 | 與 PyTorch/Open3D 無 OpenGL context 衝突 |
| DD-011 | 執行環境 | 嵌入式 Python Portable | 免安裝部署，相對路徑，不依賴系統環境 |

---

## 9. 架構強制規範

以下規範對所有後續開發者具有強制效力。Code Review 中任何違反項將觸發否決（Veto）。

### Mandatory Rules（實作規則）

**規則一：純粹的無狀態分層模組**
`GeometryProcessor` 與所有 `AbstractInpainter` 子類別必須是無狀態物件。只允許接收 DTO、回傳 DTO，模組內部禁止持有 GUI 狀態、相機座標或全域變數。

**規則二：嚴格的資料契約**
跨模組通訊只能使用 `contracts.py` 或 `commands.py` 中定義的 `@dataclass` 物件。所有 `ndarray` 與 `Tensor` 欄位必須在程式碼中明確標註 `Shape` 與 `dtype`（例：`# Shape: (H, W, 3), dtype: np.uint8`）。

**規則三：View 只做映射**
`gui/main_window.py` 不允許包含任何業務邏輯，不允許直接 import `src.core.*` 或 `src.app.orchestrator`。

**規則四：攜帶式環境優先**
所有路徑引用必須使用相對路徑，禁止寫死絕對路徑或依賴系統全域環境變數。

### Absolute Red Lines（Code Review Veto）

| 紅線 | 違規行為 | 後果 |
|------|----------|------|
| 🚫 Red Line 1 | 在 GUI 主執行緒執行超過 16ms 的運算 | 架構違規，PR 否決 |
| 🚫 Red Line 2 | 跨模組直接傳裸 ndarray/Tensor 且無契約說明 | 高風險整合缺陷，PR 否決 |
| 🚫 Red Line 3 | GUI 直接呼叫 AI / Geometry 核心（跳過 Adapter/Queue） | 架構違規，PR 否決 |
| 🚫 Red Line 4 | 透過 Queue 直接傳遞大型 3D Mesh 物件 | IPC 序列化瓶頸，PR 否決 |

---

## 10. MVP 限制與擴充路線

### 目前 MVP 限制

- **LaMa 修補器**為架構佔位符（`fill()` 拋出 `NotImplementedError`）。MVP 階段主修補器為 `TeleaInpainter`，品質較 AI 修補遜色，大面積遮擋區域可能出現模糊或紋理拉伸。
- **相機內參**以固定 FOV 60° 估算，實際整合時應從相機設備或 EXIF 取得真實內參。
- **深度圖格式**假設已完成對齊（RGB 與 Depth 同視角），未處理立體校正。
- **渲染視窗**為 Open3D 預設外觀，尚未整合自訂 UI 元件（如截圖、匯出按鈕）。

### LaMa 整合步驟（PSM Phase 4）

1. 在 `requirements.txt` 取消 `torch` / `torchvision` 的註解並安裝。
2. 下載 LaMa 預訓練權重（`.pth`），置於 `models/lama_weights.pth`。
3. 在 `src/core/inpainting.py` 的 `LaMaInpainter._load_model()` 實作模型載入邏輯。
4. 實作 `LaMaInpainter.fill()` 中的 `_run_inference()` 推論流程。
5. 在 `gui/worker.py` 的 `SynthesisWorker.run()` 中，將 `primary_inpainter` 替換為 `LaMaInpainter` 實例。
6. 執行 `tests/benchmark/run_benchmarks.py` 驗證 LaMa 延遲符合 SLA。

### 後續擴充方向

- **新增邊緣策略**：繼承 `EdgeDetectionPolicy`，實作 `compute_mask()`，無需修改 `GeometryProcessor`（OCP）。
- **新增修補策略**：繼承 `AbstractInpainter`，實作 `fill()`，在 `SynthesisWorker` 中注入即可。
- **多幀合成**：`Orchestrator.process_and_render()` 已設計為無狀態，可在外部迴圈中重複呼叫，無需修改內部邏輯。
- **匯出 PLY/OBJ**：`Orchestrator._save_mesh_to_tempfile()` 已產生 `.ply` 暫存，可延伸為永久匯出功能。

---

## 授權

本專案為內部研發用途，架構設計依據 `3D_Photo_Synthesis_Engine_DesignPaper.md`（設計稿 v1.0）。
