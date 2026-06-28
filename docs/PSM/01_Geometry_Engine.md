# PSM 設計文件： 邊緣判定與網格剔除介面
**文件版本**：v1.0 (2026-05-27)
**針對環境**：Python 3.10+, NumPy, OpenCV

## 1. 幾何處理介面更新 (Geometry Processor Interface - Updated)

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