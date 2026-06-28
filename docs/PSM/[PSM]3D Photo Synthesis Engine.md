# PSM 設計文件：通訊協定與網格生成 (Communication & Mesh Generation)
**文件版本**：v1.0 (2026-05-27)

## 1. 通訊協定與 I/O 介面設計 (I/O & Protocol)

在此分層架構下，外部環境不允許直接呼叫引擎內部的物件屬性。所有的互動皆需透過標準化的 Payload 進行。

### 1.1 狀態通訊 Payload 結構
定義一個純資料結構 (Data Class)，用於描述虛擬相機在 3D 空間中的唯一狀態：
```python
import numpy as np
from dataclasses import dataclass

@dataclass(frozen=True)
class CameraPoseUpdate:
    # 4x4 外參矩陣，包含旋轉 (R) 與平移 (t)
    extrinsic_matrix: np.ndarray 
    # 更新發生的時間戳，用於丟棄過期的操作事件
    timestamp: float 
```

### 1.2 佇列通訊協定 (Queue Protocol)
由於 Python 的 GUI/渲染視窗（如 Open3D 或 PySide）通常需要佔用主執行緒 (Main Thread)，我們採用生產者-消費者模式：
- **生產者 (Input Adapter)**：監聽滑鼠/鍵盤事件，計算出新的 `extrinsic_matrix`，並 `put()` 進入 `queue.Queue[CameraPoseUpdate]`。
- **消費者 (Rendering Engine)**：在渲染迴圈中，每幀執行 `get_nowait()`。若有新矩陣，則覆寫當前視角並調用重繪指令；若無，則保持畫面靜止以節省 GPU 資源。

---

## 2. 網格生成與斷離演算法 (Mesh Generation & Tearing)

此模組實踐純粹的無狀態邏輯，接收 $(H, W)$ 的深度矩陣，輸出剔除了深度斷層面的 `open3d.geometry.TriangleMesh`。

### 2.1 空間反投影 (Unprojection) 的向量化
不使用迴圈，直接生成像素座標網格，並套用反投影公式。

已知像素座標 $U, V$，深度 $Z$，相機光心 $c_x, c_y$ 與焦距 $f_x, f_y$：
$$X = \frac{(U - c_x) \cdot Z}{f_x}$$
$$Y = \frac{(V - c_y) \cdot Z}{f_y}$$

**NumPy 實作概念：**
```python
# 生成 U, V 網格
U, V = np.meshgrid(np.arange(width), np.arange(height))

# 向量化反投影
X = (U - cx) * Z_matrix / fx
Y = (V - cy) * Z_matrix / fy

# 堆疊並壓平為 Open3D 接受的格式 (N, 3)
points_3d = np.dstack((X, Y, Z_matrix)).reshape(-1, 3)
```

### 2.2 拓樸建立與邊緣斷離 (Triangulation & Tearing)
一張圖片中，相鄰的 $4$ 個像素 $(i, j), (i, j+1), (i+1, j), (i+1, j+1)$ 可以構成兩個相連的三角形。

**斷離條件 (Tearing Condition)：**
計算這四個頂點的深度差異 $\Delta Z$。我們採用 Sobel 梯度遮罩（先前決定的策略），若該區域在遮罩上的值高於 `Z_threshold`，則**不將該組三角形加入 Faces 陣列**。

**NumPy 向量化建面邏輯：**
1. 建立全局像素的索引矩陣 `idx_matrix`，形狀為 $(H, W)$。
2. 透過矩陣切片取得四個頂點的索引：
   - `TL` (Top-Left) = `idx_matrix[:-1, :-1]`
   - `TR` (Top-Right) = `idx_matrix[:-1, 1:]`
   - `BL` (Bottom-Left) = `idx_matrix[1:, :-1]`
   - `BR` (Bottom-Right) = `idx_matrix[1:, 1:]`
3. 組合出全局的三角形陣列 (Faces)：
   - 三角形 1 集合：`[TL, TR, BL]`
   - 三角形 2 集合：`[TR, BR, BL]`
4. **套用斷離遮罩**：取得 Sobel 遮罩的布林矩陣 `valid_mask = (grad_mask < threshold)`。利用 `valid_mask` 對上述的 Faces 陣列進行過濾 (Filter)，直接丟棄跨越斷崖邊緣的三角形索引。
5. 將過濾後的 `points_3d` 與 `faces` 封裝回傳。

# PSM 設計文件：核心模組介面與資料契約
**文件版本**：v1.1 (2026-05-27)
**針對環境**：Python 3.10+, NumPy, Open3D

## 1. 資料契約 (Data Contracts)
所有跨模組資料轉移必須使用 `@dataclass`，並在註解中明確約束 NumPy 矩陣的 Shape 與 dtype。

```python
from dataclasses import dataclass
import numpy as np

@dataclass
class RGBDFrame:
    """
    約束：color 與 depth 必須在載入時保證 H (高度) 與 W (寬度) 一致。
    """
    color: np.ndarray  # Shape: (H, W, 3), dtype: np.uint8
    depth: np.ndarray  # Shape: (H, W), dtype: np.float32
    mask: np.ndarray = None # Shape: (H, W), dtype: np.bool_

@dataclass
class CameraIntrinsics:
    fx: float          
    fy: float          
    cx: float          
    cy: float          
    width: int         
    height: int        
```

## 2. 幾何處理介面 (Geometry Processor Interface)
確保無狀態 (Stateless) 設計，不保留影像或網格狀態。

```python
import open3d as o3d

class GeometryProcessor:
    def __init__(self, intrinsics: CameraIntrinsics):
        self.intrinsics = intrinsics

    def unproject_to_points(self, depth_matrix: np.ndarray) -> np.ndarray:
        """
        輸入：Shape (H, W)
        輸出：Shape (N, 3), N = H * W
        """
        pass

    def build_topology(self, points: np.ndarray, frame: RGBDFrame) -> o3d.geometry.TriangleMesh:
        """
        輸入 points：Shape (N, 3)
        輸出：o3d.geometry.TriangleMesh (包含 vertices, triangles, vertex_colors)
        """
        pass
```

## 3. 渲染與協調控制介面 (Renderer & Orchestrator Interfaces)

```python
import queue

class Orchestrator:
    def __init__(self, geo_processor: GeometryProcessor, renderer: 'Open3DRenderer'):
        self.geo = geo_processor
        self.renderer = renderer
        
    def process_and_render(self, frame: RGBDFrame):
        pass

class Open3DRenderer:
    def __init__(self, pose_queue: queue.Queue):
        self.pose_queue = pose_queue 
        
    def initialize_scene(self, mesh: o3d.geometry.TriangleMesh) -> None:
        pass
        
    def run_event_loop(self) -> None:
        pass
```

# PSM 設計文件：Phase 2 邊緣判定與網格剔除介面
**文件版本**：v1.3 (2026-05-27)
**針對環境**：Python 3.10+, NumPy, OpenCV

## 1. 邊緣判定策略介面 (Edge Detection Policy)

```python
from abc import ABC, abstractmethod
import numpy as np

class EdgeDetectionPolicy(ABC):
    @abstractmethod
    def compute_mask(self, depth_matrix: np.ndarray) -> np.ndarray:
        """
        輸入：Shape (H, W), dtype: np.float32
        輸出：Shape (H, W), dtype: np.bool_ (True 代表斷層邊緣)
        """
        pass

class SobelEdgeDetector(EdgeDetectionPolicy):
    """
    動態 Sobel 邊緣偵測器 (基於分位數)
    """
    def __init__(self, percentile: float = 95.0):
        # 預設將梯度強度落在前 5% 的像素視為邊緣
        self.percentile = percentile

    def compute_mask(self, depth_matrix: np.ndarray) -> np.ndarray:
        # 實作指導 (PSM 規範算法邏輯)：
        # 1. cv2.Sobel 提取 X, Y 梯度，計算 Magnitude (強度)。
        # 2. threshold_value = np.percentile(Magnitude, self.percentile)
        # 3. 回傳 (Magnitude > threshold_value) 的布林遮罩。
        pass
```

## 2. 幾何處理介面更新 (Geometry Processor Interface - Updated)

```python
import open3d as o3d

class GeometryProcessor:
    def __init__(self, intrinsics: CameraIntrinsics, edge_policy: EdgeDetectionPolicy):
        self.intrinsics = intrinsics
        self.edge_policy = edge_policy

    def build_topology(self, points: np.ndarray, frame: RGBDFrame) -> o3d.geometry.TriangleMesh:
        """
        斷邊邏輯指導：
        1. 取得遮罩：mask = self.edge_policy.compute_mask(frame.depth)
        2. 更新狀態：frame.mask = mask
        3. 剔除面數：在生成 Faces (N, 3) 時，若任何一個頂點的 mask == True，則該 Face 不予建立。
        """
        pass
```