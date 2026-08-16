# PSM 設計文件：獨立渲染管線 (Rendering Pipeline)
**文件路徑**：`docs/PSM/03_Rendering_Pipeline.md`
**文件版本**：v1.0 (2026-05-27)
**針對環境**：Python 3.10+, Open3D, multiprocessing

## 1. 模組職責與進程邊界
* **RenderProcessController (主進程側)**：負責啟動、監控、與關閉 Open3D 子進程。提供統一的 `put()` 介面給 GUI 與協調層。
* **Open3DRenderWorker (子進程側)**：接管獨立的 OS Process，運行 Open3D 的 C++ 視窗事件迴圈，並監聽來自 IPC Queue 的指令。

## 2. 跨進程通訊契約 (IPC Data Contracts)
為避免多進程的序列化瓶頸 (Pickling Overhead)，**嚴禁**直接透過 Queue 傳遞 `o3d.geometry.TriangleMesh` 物件。必須透過中繼檔案或記憶體指標。

```python
from dataclasses import dataclass
import numpy as np

@dataclass(frozen=True)
class MeshLoadCommand:
    """通知渲染器載入新的 3D 網格"""
    mesh_filepath: str  # 實作約束：主進程需將網格存為暫存檔 (.ply)，只傳遞路徑

@dataclass(frozen=True)
class CameraPoseCommand:
    """通知渲染器更新視角"""
    extrinsic_matrix: np.ndarray # Shape (4, 4)

@dataclass(frozen=True)
class ShutdownCommand:
    """通知渲染器安全關閉"""
    pass
```

## 3. 主進程控制器介面 (Render Process Controller)
此介面運行於主程式中，供 `Orchestrator` 與 `InputAdapter` 呼叫。

```python
import multiprocessing as mp

class RenderProcessController:
    def __init__(self):
        # 建立跨進程安全的佇列
        self.command_queue = mp.Queue()
        self.render_process = None

    def start_process(self):
        """實例化 Open3DRenderWorker 並啟動子進程"""
        pass

    def load_mesh(self, mesh_filepath: str):
        self.command_queue.put(MeshLoadCommand(mesh_filepath))

    def update_camera(self, extrinsic_matrix: np.ndarray):
        self.command_queue.put(CameraPoseCommand(extrinsic_matrix))

    def terminate(self):
        """發送關閉指令並等待子進程 join()"""
        self.command_queue.put(ShutdownCommand())
        if self.render_process:
            self.render_process.join()
```

## 4. 子進程渲染器介面 (Render Worker Process)
此介面運行於獨立進程，必須實作非阻塞事件迴圈。

```python
import open3d as o3d
import queue

class Open3DRenderWorker:
    def __init__(self, command_queue: mp.Queue):
        self.command_queue = command_queue
        self.vis = None
        self.mesh = None

    def run(self):
        """子進程進入點"""
        self.vis = o3d.visualization.Visualizer()
        self.vis.create_window(window_name="3D Photo Synthesis Engine", width=1280, height=720)
        
        is_running = True
        while is_running:
            # 1. 處理佇列指令 (非阻塞)
            try:
                cmd = self.command_queue.get_nowait()
                is_running = self._handle_command(cmd)
            except queue.Empty:
                pass
            
            # 2. 維持 Open3D 視窗生命週期
            if not self.vis.poll_events():
                break # 使用者點擊了視窗的 'X'
            self.vis.update_renderer()

        self.vis.destroy_window()

    def _handle_command(self, cmd) -> bool:
        """根據指令類型 (MeshLoad, CameraPose, Shutdown) 更新場景。回傳 False 代表需關閉。"""
        pass
```