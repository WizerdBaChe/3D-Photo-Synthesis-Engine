# 驗證實作藍圖 (Verification Implementation Blueprint)
**文件路徑**：`docs/Testing/04_Test_Implementation.md`
**文件版本**：v1.0 (2026-05-27)
**針對環境**：`pytest`, `numpy.testing`, Python `unittest.mock`

## 1. 測試目錄結構規劃 (Test Directory Structure)
為維持主專案目錄的乾淨，所有驗證邏輯與 Mock 假資料皆收攏於 `tests/` 資料夾下，並與 `src/` (原始碼) 保持鏡像結構。

```text
3D_Synthesis_Engine/
├── src/                    # (未來實作的原始碼)
│   ├── core/
│   │   ├── geometry.py     # 包含 GeometryProcessor
│   │   └── inpainting.py   # 包含 LaMaInpainter
│   └── app/
│       ├── orchestrator.py
│       └── render_ipc.py
├── tests/                  # (驗證腳本)
│   ├── conftest.py         # Pytest 共用 Fixtures (如準備假圖片、假模型)
│   ├── unit/               # 階層一：單元測試
│   │   ├── test_geometry.py
│   │   └── test_inpainting_telea.py
│   ├── integration/        # 階層二：整合與容錯測試
│   │   ├── test_orchestrator_fallback.py
│   │   └── test_render_ipc.py
│   └── benchmark/          # 階層三：效能基準測試
│       └── run_benchmarks.py
└── run_tests.bat           # 便攜環境下的測試啟動腳本
```

## 2. 關鍵測試案例樣板 (Key Test Case Templates)

以下提供開發團隊在實作測試時必須遵循的撰寫規範與斷言邏輯。

### 2.1 階層一：網格斷邊單元測試 (`test_geometry.py`)
**目標**：驗證 Numpy 向量化斷邊邏輯，確保 $Z$ 軸落差過大時，該處的三角面會被精準剔除。

```python
import pytest
import numpy as np
from src.core.geometry import GeometryProcessor, CameraIntrinsics
from src.core.policies import SobelEdgeDetector

def test_mesh_tearing_with_synthetic_cliff():
    # 1. Arrange: 準備 10x10 的假深度圖，並在中間製造一個 "斷崖"
    depth_matrix = np.ones((10, 10), dtype=np.float32)
    depth_matrix[:, 5:] = 100.0  # 右半邊深度突然變 100
    
    dummy_color = np.zeros((10, 10, 3), dtype=np.uint8)
    frame = RGBDFrame(color=dummy_color, depth=depth_matrix)
    
    intrinsics = CameraIntrinsics(fx=500, fy=500, cx=5, cy=5, width=10, height=10)
    # 設定極低的閾值，確保斷崖一定會被偵測到
    edge_policy = SobelEdgeDetector(percentile=50.0) 
    geo_processor = GeometryProcessor(intrinsics, edge_policy)

    # 2. Act: 執行生成
    points = geo_processor.unproject_to_points(frame.depth)
    mesh = geo_processor.build_topology(points, frame)

    # 3. Assert: 驗證物理斷離
    # 10x10 的點雲原本應該產生 (9 * 9 * 2) = 162 個面
    # 但中間第 5 行被判定為斷崖，所以有 9 個正方形 (18 個三角形) 會被剔除
    expected_faces = 162 - 18
    actual_faces = np.asarray(mesh.triangles).shape[0]
    
    assert actual_faces == expected_faces, f"Expected {expected_faces} faces, got {actual_faces}"
```

### 2.2 階層二：OOM 降級整合測試 (`test_orchestrator_fallback.py`)
**目標**：確保當 PyTorch 耗盡 VRAM 時，系統不會崩潰（Crash），而是平滑過渡到 CPU 的 OpenCV 演算法。

```python
import pytest
from unittest.mock import patch, MagicMock
from src.app.orchestrator import Orchestrator

@patch('src.core.inpainting.LaMaInpainter.fill')
def test_orchestrator_fallback_on_cuda_oom(mock_lama_fill, dummy_rgbd_frame):
    # 1. Arrange: 強制 LaMa 拋出 Out of Memory 錯誤
    mock_lama_fill.side_effect = RuntimeError("CUDA out of memory")
    
    mock_geo = MagicMock()
    mock_telea = MagicMock()
    mock_telea.fill.return_value = "Mocked_Telea_Result" # 假設 Telea 成功
    mock_renderer = MagicMock()

    orchestrator = Orchestrator(mock_geo, mock_lama_fill, mock_telea, mock_renderer)

    # 2. Act: 啟動管線
    # 如果降級機制失效，這裡會直接拋出 Exception 導致測試失敗
    orchestrator.process_and_render(dummy_rgbd_frame)

    # 3. Assert: 驗證行為
    mock_lama_fill.assert_called_once() # 確認有嘗試呼叫 LaMa
    mock_telea.fill.assert_called_once() # 確認觸發了降級備案
    # 確認清空 VRAM 的指令有被執行 (需依據實作細節斷言 torch.cuda.empty_cache)
```

### 2.3 階層三：IPC 效能與記憶體基準測試 (`run_benchmarks.py`)
**目標**：模擬真實使用者的高頻率滑鼠拖曳，並監控記憶體。這不是傳統的 pytest，而是一支獨立的 Profiling 腳本。

```python
import time
import psutil
import multiprocessing as mp
from src.app.render_ipc import RenderProcessController, CameraPoseCommand

def benchmark_ipc_throughput():
    controller = RenderProcessController()
    controller.start_process()
    
    # 準備 1000 個高頻相機位姿更新 (模擬滑鼠快速甩動)
    commands = [CameraPoseCommand(np.eye(4)) for _ in range(1000)]
    
    start_time = time.time()
    
    # 壓力灌入佇列
    for cmd in commands:
        controller.update_camera(cmd.extrinsic_matrix)
        
    # 等待子進程消化完畢 (實務上需實作 Ack 回呼或輪詢)
    wait_for_queue_empty(controller.command_queue)
    
    end_time = time.time()
    latency = end_time - start_time
    
    print(f"IPC 吞吐量基準測試:")
    print(f"1000 次指令消化時間: {latency:.3f} 秒")
    assert latency < 2.0, "IPC 佇列發生嚴重阻塞，效能未達標！"
    
    controller.terminate()
```

## 3. 免安裝環境 (Portable) 下的自動化執行
為了確保測試結果與最終使用者的環境完全一致，所有測試必須在 `ComfyUI_portable` 型態的隔離環境中執行。

建立 `run_tests.bat`：
```bat
@echo off
echo [INFO] 初始化嵌入式 Python 測試環境...

:: 將系統路徑鎖定在可攜式資料夾內的 python
set EMBEDDED_PYTHON=%~dp0\python_embeded\python.exe
set PYTHONPATH=%~dp0\src

:: 執行 Pytest
"%EMBEDDED_PYTHON%" -m pytest tests/unit tests/integration -v

:: 執行效能基準 (可選)
:: "%EMBEDDED_PYTHON%" tests/benchmark/run_benchmarks.py

pause
```