# PSM 設計文件：GUI 與輸入適配層 (GUI & Input Adapter)
**文件路徑**：`docs/PSM/05_GUI_and_Adapter.md`
**文件版本**：v1.0 (2026-05-27)
**針對環境**：Python 3.10+, PySide6 (Qt), NumPy

## 1. 架構邊界劃分 (Architecture Boundaries)

* **View 層 (PySide6)**：純 UI。包含按鈕、下拉選單、X/Y/Z 軸旋轉滑桿。
* **Adapter 層 (InputAdapter)**：數學翻譯官。將滑桿的 0~360 度轉換為歐拉角與旋轉矩陣。
* **Core 層 (Orchestrator)**：我們在 Phase 1~4 建立的引擎。它跑在獨立的執行緒中，只聽從 Queue 傳來的指令。

## 2. 系統指令資料契約 (Command DTOs)
除了先前的 `CameraPoseUpdate`，我們新增引擎控制的指令結構。

```python
from dataclasses import dataclass
from enum import Enum

class EngineCommandType(Enum):
    LOAD_IMAGE = 1
    CHANGE_VRAM_STRATEGY = 2
    START_SYNTHESIS = 3

@dataclass(frozen=True)
class EngineCommand:
    """前端發送給後端核心引擎的設定指令"""
    command_type: EngineCommandType
    payload: dict  # 例如: {"rgb_path": "...", "depth_path": "..."}
```

## 3. 輸入適配器實作 (Input Adapter)
這支程式是 GUI 與核心引擎之間的橋樑。它接收 GUI 的具體數值，執行純數學運算，並轉發為抽象資料結構。

```python
import numpy as np
import queue
from math import radians, cos, sin
# 引入先前定義的合約
# from contracts import CameraPoseUpdate, EngineCommand

class InputAdapter:
    def __init__(self, command_queue: queue.Queue, pose_queue: queue.Queue):
        self.command_queue = command_queue
        self.pose_queue = pose_queue

    # ---------------------------------------------------------
    # 映射 1: UI 系統設定 -> 引擎指令
    # ---------------------------------------------------------
    def on_load_files_requested(self, rgb_path: str, depth_path: str):
        """映射 GUI 的檔案選擇事件"""
        cmd = EngineCommand(
            command_type=EngineCommandType.LOAD_IMAGE,
            payload={"rgb": rgb_path, "depth": depth_path}
        )
        self.command_queue.put(cmd)

    # ---------------------------------------------------------
    # 映射 2: UI 幾何操作 -> 數學矩陣轉換
    # ---------------------------------------------------------
    def on_rotation_slider_changed(self, pitch_deg: float, yaw_deg: float, roll_deg: float):
        """
        核心適配邏輯：將人類可讀的歐拉角 (度數) 轉換為 Open3D 需要的 4x4 外參矩陣。
        """
        # 1. 角度轉弧度
        p, y, r = radians(pitch_deg), radians(yaw_deg), radians(roll_deg)

        # 2. 計算各軸旋轉矩陣
        Rx = np.array([
            [1, 0, 0],
            [0, cos(p), -sin(p)],
            [0, sin(p), cos(p)]
        ])
        Ry = np.array([
            [cos(y), 0, sin(y)],
            [0, 1, 0],
            [-sin(y), 0, cos(y)]
        ])
        Rz = np.array([
            [cos(r), -sin(r), 0],
            [sin(r), cos(r), 0],
            [0, 0, 1]
        ])

        # 3. 合成總旋轉矩陣 (ZYX 順序)
        R = Rz @ Ry @ Rx

        # 4. 構建 4x4 外參矩陣 (Extrinsic Matrix)
        # 預設相機在世界座標原點，無平移 (t=[0,0,0])
        extrinsic = np.eye(4)
        extrinsic[:3, :3] = R
        
        # 5. 封裝為 Payload 並發送給渲染引擎
        import time
        update = CameraPoseUpdate(extrinsic_matrix=extrinsic, timestamp=time.time())
        self.pose_queue.put(update)
```

## 4. 前端 View 層展示範例 (PySide6 Dummy View)
這段代碼向實作工程師示範：前端類別完全不需載入任何 AI 或 3D 函式庫。

```python
# 平台依賴：PySide6
from PySide6.QtWidgets import QWidget, QSlider, QPushButton
from PySide6.QtCore import Qt

class MainWindowView(QWidget):
    def __init__(self, adapter: InputAdapter):
        super().__init__()
        self.adapter = adapter  # 注入適配器
        self._setup_ui()

    def _setup_ui(self):
        # 範例：水平旋轉滑桿 (Yaw)
        self.yaw_slider = QSlider(Qt.Horizontal)
        self.yaw_slider.setRange(-45, 45) # 限制視角旋轉為正負45度避免破圖
        
        # 嚴格的訊號映射 (Signal Routing)
        # GUI 不懂矩陣，只負責把數值傳給 Adapter
        self.yaw_slider.valueChanged.connect(self._handle_slider_mapping)

    def _handle_slider_mapping(self):
        # 收集當前 UI 狀態，呼叫適配器
        yaw = self.yaw_slider.value()
        # 假設 pitch 和 roll 為 0
        self.adapter.on_rotation_slider_changed(pitch_deg=0, yaw_deg=yaw, roll_deg=0)
```