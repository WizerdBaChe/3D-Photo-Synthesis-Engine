"""
幾何處理器 (Geometry Processor)
=================================
設計依據：DD-001（無狀態）、DD-002（NumPy 向量化）、DD-005（策略注入）

規範：
- 此模組為純函數性質，只接收 DTO 並回傳 DTO/Mesh。
- 禁止在此模組內存留任何 GUI 狀態、相機座標或全域變數。
- 邊緣判定策略透過建構子注入，確保演算法可抽換（OCP）。
"""

import numpy as np
import open3d as o3d

from src.core.contracts import RGBDFrame, CameraIntrinsics
from src.core.policies import EdgeDetectionPolicy


class GeometryProcessor:
    """
    無狀態幾何處理器（DD-001, DD-002）。

    職責：
      1. 深度圖反投影為 3D 點雲（unproject_to_points）
      2. 建立三角拓樸並套用斷邊遮罩（build_topology）

    注入：CameraIntrinsics + EdgeDetectionPolicy，確保算法與硬體參數可替換。
    """

    def __init__(self, intrinsics: CameraIntrinsics, edge_policy: EdgeDetectionPolicy):
        self.intrinsics = intrinsics
        self.edge_policy = edge_policy

    # ------------------------------------------------------------------
    # 公開介面
    # ------------------------------------------------------------------

    def unproject_to_points(self, depth_matrix: np.ndarray) -> np.ndarray:
        """
        將深度圖（像素座標 + 深度值）反投影為 3D 點雲。

        數學公式（Pinhole Camera Model）：
            X = (U - cx) * Z / fx
            Y = (V - cy) * Z / fy

        輸入：Shape (H, W), dtype: np.float32 — 正規化深度圖
        輸出：Shape (H*W, 3), dtype: np.float64 — 3D 點雲 (X, Y, Z)
        """
        fx = self.intrinsics.fx
        fy = self.intrinsics.fy
        cx = self.intrinsics.cx
        cy = self.intrinsics.cy

        h, w = depth_matrix.shape

        # 生成 U（列）、V（行）像素座標網格，Row-Major 排列
        U, V = np.meshgrid(np.arange(w, dtype=np.float64),
                           np.arange(h, dtype=np.float64))

        # 向量化反投影（廣播計算，無 Python 迴圈）
        Z = depth_matrix.astype(np.float64)
        X = (U - cx) * Z / fx
        Y = (V - cy) * Z / fy

        # 堆疊並壓平為 Open3D 接受的格式 (N, 3)
        # np.dstack 產生 (H, W, 3)，reshape 壓平為 (H*W, 3)
        return np.dstack((X, Y, Z)).reshape(-1, 3)

    def build_topology(self, points: np.ndarray, frame: RGBDFrame) -> o3d.geometry.TriangleMesh:
        """
        從點雲建立三角網格，並套用斷邊遮罩剔除深度斷崖處的面。

        拓樸建立原理（PSM Phase 2.4 向量化算法）：
            相鄰 4 像素 [TL, TR, BL, BR] → 2 個三角形
            ┌──┐  TL─TR   TL: Top-Left    索引 idx[  i, j  ]
            │  │   │╲│    TR: Top-Right   索引 idx[  i, j+1]
            └──┘  BL─BR   BL: Bottom-Left 索引 idx[i+1, j  ]
                           BR: Bottom-Right 索引 idx[i+1, j+1]
            三角形 1: [TL, TR, BL]
            三角形 2: [TR, BR, BL]

        輸入 points：Shape (H*W, 3), dtype: np.float64
        輸出：o3d.geometry.TriangleMesh（含頂點、三角面、頂點顏色）
        """
        h, w = frame.depth.shape

        # Step 1: 決定斷邊遮罩
        #   優先使用 frame.mask（若已由 Orchestrator 預先計算）
        #   否則在修補後的 depth 上重新計算（確保修補區域有正確拓樸）
        if frame.mask is not None:
            edge_mask = frame.mask  # Shape (H, W), bool
        else:
            edge_mask = self.edge_policy.compute_mask(frame.depth)

        # Step 2: 建立全局像素索引矩陣 (Row-Major)
        idx_matrix = np.arange(h * w, dtype=np.int32).reshape(h, w)

        # Step 3: 向量化切片取得四個鄰居頂點的索引（Shape: H-1, W-1）
        TL = idx_matrix[:-1, :-1]   # Top-Left
        TR = idx_matrix[:-1,  1:]   # Top-Right
        BL = idx_matrix[ 1:, :-1]   # Bottom-Left
        BR = idx_matrix[ 1:,  1:]   # Bottom-Right

        # Step 4: 斷邊遮罩擴展至四頂點——任一頂點在斷崖上則整個方格無效
        edge_tl = edge_mask[:-1, :-1]
        edge_tr = edge_mask[:-1,  1:]
        edge_bl = edge_mask[ 1:, :-1]
        edge_br = edge_mask[ 1:,  1:]
        invalid = edge_tl | edge_tr | edge_bl | edge_br   # Shape (H-1, W-1)
        valid   = ~invalid                                  # 有效方格遮罩

        # Step 5: 組合三角形並以 valid 遮罩過濾
        #   np.stack + valid 布林索引 → 只取有效方格
        tri1 = np.stack([TL[valid], TR[valid], BL[valid]], axis=-1)  # (K, 3)
        tri2 = np.stack([TR[valid], BR[valid], BL[valid]], axis=-1)  # (K, 3)
        faces = np.vstack([tri1, tri2])                               # (2K, 3)

        # Step 6: 建立 Open3D TriangleMesh
        mesh = o3d.geometry.TriangleMesh()
        mesh.vertices  = o3d.utility.Vector3dVector(points)
        mesh.triangles = o3d.utility.Vector3iVector(faces)

        # Step 7: 指定頂點顏色（正規化至 [0, 1]）
        colors = frame.color.reshape(-1, 3).astype(np.float64) / 255.0
        mesh.vertex_colors = o3d.utility.Vector3dVector(colors)

        mesh.compute_vertex_normals()
        return mesh
