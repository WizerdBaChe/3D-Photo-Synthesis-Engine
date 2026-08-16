# 3D Photo Synthesis Engine 驗證與測試主體

文件角色：Verification & Testing Authority

內容來源：原主文件第四部分。

AI 閱讀指引：
- 若問題涉及驗證覆蓋率、測試範圍、SLA、Benchmark、測試腳本，請優先引用本文件。
- 若問題涉及正式架構設計與模組責任，請回到 `01_core_design.md`。

# 第四部分：驗證規劃與測試藍圖 (Verification & Testing)

## 1. 驗證規劃總覽 (Master Verification Plan)

ℹ️ 文件版本：v1.0 (2026-05-27)

### 1.1 驗證目標 (Verification Objectives)

本專案為高吞吐量之本機端 3D 圖形應用，基於 V-Model 系統工程法，本計畫旨在驗證「無狀態分層模組架構」與「獨立渲染管線」在 Python (PyTorch/Open3D) 環境下的正確性與穩定性。目標確保系統在 Intel 10 代與獨立顯卡環境下，不發生 OOM 崩潰，且畫面更新率達標。

### 1.2 測試環境與工具 (Testing Environment & Tools)

| 領域 | 測試框架/工具 | 用途 |
| --- | --- | --- |
| 自動化測試框架 | pytest | 執行所有單元與整合測試，驗證資料契約 (Data Contracts)。 |
| 資料模擬 (Mocking) | unittest.mock, numpy.testing | 攔截 PyTorch 錯誤、模擬高梯度深度圖矩陣。 |
| 記憶體監控 | memory_profiler, torch.cuda | 追蹤 Python 主進程 RAM 與 GPU VRAM 的洩漏狀況。 |
| 效能分析 | cProfile, time | 定位 AI 推論與幾何三角化的 CPU/GPU 耗時瓶頸。 |

### 1.3 驗證策略階層 (Verification Tiers)

本計畫採由下而上 (Bottom-Up) 的三層驗證策略：

* 階層一（Unit Test）：驗證無狀態純函數的數學正確性（確保 Git 協作時底層邏輯不被破壞）。
* 階層二（Integration Test）：驗證跨執行緒/進程的 IPC 佇列與 OOM 容錯降級機制。
* 階層三（Benchmark）：驗證端到端 (End-to-End) 系統在真實硬體上的延遲與幀率 (FPS)。

## 2. 階層一：單元測試規範 (Tier 1: Unit Testing)

### 2.1 驗證範圍

本階層專注於「無狀態模組 (Stateless Modules)」，包含 GeometryProcessor、SobelEdgeDetector 與 TeleaInpainter。測試過程禁止啟動 GUI 視窗或佔用真實的 GPU 資源。

### 2.2 資料契約斷言規範 (Data Contract Assertions)

| 測試目標 | 輸入模擬 (Mock Data) | 預期斷言 (Expected Assertions) |
| --- | --- | --- |
| RGBDFrame 建構 | 傳入 100×100 的 color 矩陣與 50×50 的 depth 矩陣。 | 斷言拋出 ValueError（驗證維度一致性合約）。 |
| 邊緣判定 (Sobel) | 傳入 10×10 深度矩陣，左半部為 1.0，右半部為 10.0。 | 斷言輸出的 Mask 矩陣形狀為 10×10，且布林值 True 僅出現於第 5 行邊界。 |
| 反投影 (Unprojection) | 傳入 10×10 深度矩陣（全為 1.0），與預設內參。 | 斷言輸出的 points 陣列形狀為 (100, 3)，且 Z 軸數值全為 1.0。 |
| 網格剔除 (Topology) | 傳入上述 points 與全為 False 的 Mask。 | 斷言產出的 TriangleMesh 包含精準的 162 個面 (9×9×2)。 |
| 網格破洞 (Tearing) | 傳入一組 Mask，其中包含 4 個相連的 True 像素。 | 斷言產出的 TriangleMesh 面數小於 162，確認破洞物理生成成功。 |

### 2.3 測試設計原則

* 利用 numpy.testing.assert_array_equal 進行矩陣比對。
* 所有測試函數必須能在 1 秒內於純 CPU 環境執行完畢，確保 CI/CD 管線的極速回饋。

## 3. 階層二：整合與容錯測試規範 (Tier 2: Integration & Fallback)

### 3.1 驗證範圍

驗證 Orchestrator（協調層）的管線流轉、AI 模型降級機制，以及 RenderProcessController 的跨進程通訊防呆機制。

### 3.2 容錯與狀態斷言規範 (State & Error Assertions)

| 測試情境 (Scenario) | 執行動作與 Mock 設置 | 預期斷言 (Expected Assertions) |
| --- | --- | --- |
| AI 記憶體爆滿降級 | 攔截 LaMaInpainter.fill()，強制拋出 RuntimeError("CUDA out of memory")。 | 斷言 Orchestrator 捕捉異常、TeleaInpainter 被自動呼叫，並成功回傳無破洞的 RGBDFrame。 |
| LAZY 模式記憶體釋放 | 實例化 LaMaInpainter(strategy=LAZY) 並執行一次修補。 | 斷言執行前後的 torch.cuda.memory_allocated() 數值完全一致（確認無洩漏）。 |
| IPC 佇列擠壓防護 | 向 RenderProcessController.command_queue 連續寫入 10,000 個相機位姿指令。 | 啟動子進程後，斷言佇列能在 0.5 秒內被清空或只讀取最新值，不發生阻塞死鎖。 |
| 子進程安全關閉 | 呼叫 RenderProcessController.terminate()。 | 斷言 render_process.is_alive() 在 2 秒內變為 False，無殭屍進程 (Zombie Process) 殘留。 |

### 3.3 測試設計原則

* 本階層允許載入輕量級神經網路權重進行測試，但仍以 unittest.mock 控制例外狀況為主。
* 針對跨進程測試，需加入超時機制 (pytest.mark.timeout) 避免死鎖導致測試卡死。

## 4. 階層三：效能基準測試規範 (Tier 3: Performance Benchmarking)

### 4.1 驗證範圍

於目標硬體環境（Intel Core i5 10th Gen 或以上，搭配 NVIDIA RTX 3060 12GB 或同等顯卡）執行端到端（GUI 點擊至畫面重繪）的真實效能壓力測試。

### 4.2 效能指標門檻 (SLA / KPIs)

本測試將輸入三張標準解析度的 RGB-D 圖片（512×512、1024×1024、1920×1080），紀錄並驗證以下指標：

| 指標名稱 | 測試定義 | 合格門檻 (Pass Criteria) |
| --- | --- | --- |
| 幾何預處理時間 | 從載入圖片到完成斷邊遮罩與三角網格生成。 | 1080p 圖片需於 < 0.5 秒內完成（驗證 NumPy 向量化效能）。 |
| Telea 修補耗時 | 執行 OpenCV 雙重修補 (RGB + Depth)。 | 1080p 圖片需於 < 1.0 秒內完成。 |
| LaMa 延遲（常駐） | 模型已在 VRAM 中，單次推論耗時。 | 1080p 圖片需於 < 3.0 秒內完成。 |
| LaMa 延遲（用完即丟） | 包含模型載入、推論、釋放顯存的總耗時。 | 1080p 圖片需於 < 6.0 秒內完成。 |
| 渲染互動幀率 | 在 Open3D 視窗中連續發送 60 個視角旋轉矩陣。 | 平均更新率需維持 >= 30 FPS，無明顯卡頓撕裂。 |

### 4.3 測試執行與報告

* 使用 Python 腳本封裝上述測試，並於每次執行後輸出 benchmark_report.json。
* 若任何一項效能指標低於合格門檻的 80%，將標記為 PERFORMANCE_REGRESSION，需重新檢視 PSM 中的迴圈或記憶體映射實作。

## 5. 驗證實作藍圖 (Verification Implementation Blueprint)

### 5.1 測試目錄結構規劃

```text
3D_Synthesis_Engine/
├── src/
│   ├── core/
│   │   ├── geometry.py # 包含 GeometryProcessor
│   │   └── inpainting.py # 包含 LaMaInpainter
│   └── app/
│       ├── orchestrator.py
│       └── render_ipc.py
├── tests/
│   ├── conftest.py # Pytest 共用 Fixtures
│   ├── unit/
│   │   ├── test_geometry.py
│   │   └── test_inpainting_telea.py
│   ├── integration/
│   │   ├── test_orchestrator_fallback.py
│   │   └── test_render_ipc.py
│   └── benchmark/
│       └── run_benchmarks.py
└── run_tests.bat # 便攜環境下的測試啟動腳本
```

### 5.2 階層一：網格斷邊單元測試範本 (test_geometry.py)

ℹ️ 目標：驗證 NumPy 向量化斷邊邏輯，確保 Z 軸落差過大時，該處的三角面會被精準剔除。

```python
import pytest
import numpy as np
from src.core.geometry import GeometryProcessor, CameraIntrinsics
from src.core.policies import SobelEdgeDetector

def test_mesh_tearing_with_synthetic_cliff():
    # 1. Arrange: 準備 10x10 的假深度圖，在中間製造一個「斷崖」
    depth_matrix = np.ones((10, 10), dtype=np.float32)
    depth_matrix[:, 5:] = 100.0 # 右半邊深度突然變 100
    dummy_color = np.zeros((10, 10, 3), dtype=np.uint8)
    frame = RGBDFrame(color=dummy_color, depth=depth_matrix)
    intrinsics = CameraIntrinsics(fx=500, fy=500, cx=5, cy=5, width=10, height=10)
    edge_policy = SobelEdgeDetector(percentile=50.0)
    geo_processor = GeometryProcessor(intrinsics, edge_policy)

    # 2. Act
    points = geo_processor.unproject_to_points(frame.depth)
    mesh = geo_processor.build_topology(points, frame)

    # 3. Assert: 10x10 點雲原本應產生 (9*9*2) = 162 個面
    # 但中間第 5 行被判定為斷崖，有 9 個正方形 (18 個三角形) 會被剔除
    expected_faces = 162 - 18
    actual_faces = np.asarray(mesh.triangles).shape[0]
    assert actual_faces == expected_faces, f"Expected {expected_faces}, got {actual_faces}"
```

### 5.3 階層二：OOM 降級整合測試範本 (test_orchestrator_fallback.py)

ℹ️ 目標：確保當 PyTorch 耗盡 VRAM 時，系統不會 Crash，而是平滑過渡到 CPU 的 OpenCV 演算法。

```python
import pytest
from unittest.mock import patch, MagicMock
from src.app.orchestrator import Orchestrator

@patch('src.core.inpainting.LaMaInpainter.fill')
def test_orchestrator_fallback_on_cuda_oom(mock_lama_fill, dummy_rgbd_frame):
    # 1. Arrange: 強制 LaMa 拋出 OOM 錯誤
    mock_lama_fill.side_effect = RuntimeError("CUDA out of memory")
    mock_geo = MagicMock()
    mock_telea = MagicMock()
    mock_telea.fill.return_value = "Mocked_Telea_Result"
    mock_renderer = MagicMock()
    orchestrator = Orchestrator(mock_geo, mock_lama_fill, mock_telea, mock_renderer)

    # 2. Act
    orchestrator.process_and_render(dummy_rgbd_frame)

    # 3. Assert
    mock_lama_fill.assert_called_once() # 確認有嘗試呼叫 LaMa
    mock_telea.fill.assert_called_once() # 確認觸發了降級備案
```

### 5.4 階層三：IPC 效能基準測試範本 (run_benchmarks.py)

**⚠️ wait_for_queue_empty(controller.command_queue) 為未定義的函式，實作時需自行實作此輪詢邏輯（例如輪詢 command_queue.empty() 加上超時判斷）。**

```python
import time
import numpy as np
import multiprocessing as mp
from src.app.render_ipc import RenderProcessController, CameraPoseCommand

def benchmark_ipc_throughput():
    controller = RenderProcessController()
    controller.start_process()
    commands = [CameraPoseCommand(np.eye(4)) for _ in range(1000)]
    start_time = time.time()

    for cmd in commands:
        controller.update_camera(cmd.extrinsic_matrix)

    # TODO: 實作 wait_for_queue_empty() 輪詢邏輯
    wait_for_queue_empty(controller.command_queue)

    latency = time.time() - start_time
    print(f"1000 次指令消化時間: {latency:.3f} 秒")
    assert latency < 2.0, "IPC 佇列發生嚴重阻塞！"
    controller.terminate()
```

### 5.5 免安裝環境下的測試腳本 (run_tests.bat)

```bat
@echo off

echo [INFO] 初始化嵌入式 Python 測試環境...
set EMBEDDED_PYTHON=%~dp0\python_embeded\python.exe
set PYTHONPATH=%~dp0\src
"%EMBEDDED_PYTHON%" -m pytest tests/unit tests/integration -v
:: 執行效能基準 (可選)
:: "%EMBEDDED_PYTHON%" tests/benchmark/run_benchmarks.py
pause
```
