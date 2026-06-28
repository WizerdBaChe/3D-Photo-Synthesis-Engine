"""
幾何處理器 (Geometry Processor)
=================================
設計依據：DD-001（無狀態）、DD-002（NumPy 向量化）、DD-005（策略注入）

規範：
- 此模組為純函數性質，只接收 DTO 並回傳 DTO（MeshData）。
- 禁止在此模組內存留任何 GUI 狀態、相機座標或全域變數。
- 邊緣判定策略透過建構子注入，確保演算法可抽換（OCP）。
- 平台無關：不依賴 Open3D，輸出純 NumPy 的 MeshData，渲染交由前端 WebGL。
"""

import numpy as np

from src.core.contracts import RGBDFrame, CameraIntrinsics, MeshData
from src.core.policies import EdgeDetectionPolicy


class GeometryProcessor:
    """
    無狀態幾何處理器（DD-001, DD-002）。

    職責：
      1. 深度圖反投影為 3D 點雲（unproject_to_points）
      2. 建立三角拓樸並套用斷邊遮罩（build_topology）

    注入：CameraIntrinsics + EdgeDetectionPolicy，確保算法與硬體參數可替換。
    """

    def __init__(
        self,
        intrinsics: CameraIntrinsics,
        edge_policy: EdgeDetectionPolicy,
        max_edge_ratio: float | None = None,
    ):
        """
        Args:
            intrinsics:      相機內參。
            edge_policy:     斷崖偵測策略（注入，OCP）。
            max_edge_ratio:  3D 邊長剔除門檻（佔全體中位邊長的倍數）。None=關閉（預設）。
                開啟時，任一邊在 3D 長度 > max_edge_ratio × 中位邊長的三角形會被
                剔除。這是「斷崖遮罩漏切」的最終防線：平滑 ML depth 沒有銳利
                斷崖、修補又會把斷崖糊成緩坡，使遮罩切不到真正的前/背景邊界，
                反投影遂把這些落差沿光心射線拉成放射狀長條；放射線三角形的
                3D 邊長遠大於主體（實測 max/median 可達數百倍），以邊長比例
                剔除即可在「不依賴視角、不依賴 2D 斷崖判定」下根治。
        """
        self.intrinsics = intrinsics
        self.edge_policy = edge_policy
        self.max_edge_ratio = max_edge_ratio

    # ------------------------------------------------------------------
    # 公開介面
    # ------------------------------------------------------------------

    def unproject_to_points(self, depth_matrix: np.ndarray) -> np.ndarray:
        """
        將深度圖（像素座標 + 深度值）反投影為 3D 點雲。

        數學公式（Pinhole Camera Model）+ glTF 右手座標系修正：
            Z_cam = depth_near + d * (depth_far - depth_near)   # C-3：正規化深度 → 物理尺度
            X =  (U - cx) * Z_cam / fx
            Y = -(V - cy) * Z_cam / fy   # 翻 Y：影像列 V 向下增長，glTF +Y 朝上
            Z = -Z_cam                   # 翻 Z：相機朝 +Z_cam（螢幕內），glTF +Z 朝觀者

        座標系（Bug D 修正）：
            影像反投影的原生座標為 Y 朝下、Z 朝螢幕內（左手系），但 glTF 2.0 /
            Three.js 約定右手系（+Y 上、+Z 朝觀者）。直接輸出會使模型上下/前後
            翻轉、OrbitControls 旋轉方向相反。此處在反投影階段一次轉正，
            gltf_export 即可原樣輸出，無需再做座標 hack。

        輸入：Shape (H, W), dtype: np.float32 — 正規化深度圖 d ∈ [0, 1]
        輸出：Shape (H*W, 3), dtype: np.float64 — 3D 點雲 (X, Y, Z)，glTF 右手系
              （刻意升 float64 維持反投影精度，符合 DD-001/約束條件「保持浮點數精度」）
        """
        fx = self.intrinsics.fx
        fy = self.intrinsics.fy
        cx = self.intrinsics.cx
        cy = self.intrinsics.cy
        near = self.intrinsics.depth_near
        far  = self.intrinsics.depth_far

        h, w = depth_matrix.shape

        # 生成 U（列）、V（行）像素座標網格，Row-Major 排列
        U, V = np.meshgrid(np.arange(w, dtype=np.float64),
                           np.arange(h, dtype=np.float64))

        # C-3：將正規化深度 d∈[0,1] 線性還原到實際相機座標 Z_cam
        d = depth_matrix.astype(np.float64)
        z_cam = near + d * (far - near)

        # 向量化反投影（廣播計算，無 Python 迴圈）
        X = (U - cx) * z_cam / fx
        Y = -(V - cy) * z_cam / fy   # Bug D：翻 Y，glTF +Y 朝上
        Z = -z_cam                   # Bug D：翻 Z，glTF +Z 朝觀者

        # 堆疊並壓平為 (N, 3)
        # np.dstack 產生 (H, W, 3)，reshape 壓平為 (H*W, 3)
        return np.dstack((X, Y, Z)).reshape(-1, 3)

    def build_topology(self, points: np.ndarray, frame: RGBDFrame) -> MeshData:
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
        輸出：MeshData（純 NumPy：頂點、三角面、頂點色、頂點法線），平台無關。
        """
        h, w = frame.depth.shape

        # Step 0: 契約防護（A-2 / DD-004「模組邊界先驗證契約」）
        #   points、color、depth 必須同屬 row-major 的 H×W 展平，否則頂點/顏色錯位。
        n = h * w
        if points.shape != (n, 3):
            raise ValueError(
                f"[build_topology] points 形狀不符：期望 ({n}, 3)，收到 {points.shape}。"
                f" 應為 depth (H={h}, W={w}) 經 unproject_to_points 展平的結果。"
            )
        if frame.color.shape[:2] != (h, w):
            raise ValueError(
                f"[build_topology] color 與 depth 維度不一致："
                f" color={frame.color.shape[:2]} vs depth={(h, w)}。"
            )

        # Step 1: 決定斷邊遮罩（Bug C 修正）
        #   斷崖該不該連面，取決於「修補後」的 depth，因此一律在傳入的
        #   frame.depth（已修補）上重新計算，不再沿用 frame.mask。
        #
        #   語意分離：frame.mask 是「破洞修補遮罩」（inpainting 用，標記要填補
        #   的破洞），與此處的「斷崖剔除遮罩」目的不同，不應共用同一欄位。
        #   舊版直接沿用 frame.mask 會在平滑 ML depth 上完全切錯位置，導致斷崖
        #   未被剔除、反投影把深度不連續處沿光心射線拉成放射狀長條。
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

        # Step 5b: 3D 邊長剔除（最終防線，可關；預設 max_edge_ratio=None）
        #   斷崖遮罩在平滑 ML depth 上會漏切真正的前/背景邊界（無銳利斷崖、
        #   修補又把斷崖糊成緩坡），反投影把這些落差沿光心射線拉成放射狀長條。
        #   這些三角形的 3D 邊長遠大於主體，以「邊長 > k×中位邊長」剔除即可
        #   在不依賴視角與 2D 斷崖判定下根治。
        if self.max_edge_ratio is not None and faces.shape[0] > 0:
            faces = self._cull_long_edge_faces(points, faces, self.max_edge_ratio)

        # Step 6: 頂點顏色（正規化至 [0, 1]）
        colors = (frame.color.reshape(-1, 3).astype(np.float32) / 255.0)

        # Step 7: 頂點法線（純 NumPy 計算，不依賴 Open3D）
        vertices = points.astype(np.float32)
        faces_i32 = faces.astype(np.int32)
        normals = self._compute_vertex_normals(vertices, faces_i32)

        return MeshData(
            vertices=vertices,
            faces=faces_i32,
            colors=colors,
            normals=normals,
        )

    @staticmethod
    def _compute_vertex_normals(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
        """
        以純 NumPy 計算頂點法線（取代 Open3D 的 compute_vertex_normals）。

        作法：
          1. 每個三角面的法線 = (v1-v0) × (v2-v0)（未正規化，等價以面積加權）。
          2. 用 np.add.at 將面法線散佈累加到三個頂點上。
          3. 正規化每個頂點累加後的法線。

        輸入：vertices (V,3) float32、faces (F,3) int32
        輸出：normals  (V,3) float32
        """
        normals = np.zeros_like(vertices, dtype=np.float32)
        if faces.shape[0] == 0:
            return normals

        v0 = vertices[faces[:, 0]]
        v1 = vertices[faces[:, 1]]
        v2 = vertices[faces[:, 2]]
        face_n = np.cross(v1 - v0, v2 - v0)   # (F, 3)，面積加權法線

        # 散佈累加至頂點（一個頂點被多個面共享）
        np.add.at(normals, faces[:, 0], face_n)
        np.add.at(normals, faces[:, 1], face_n)
        np.add.at(normals, faces[:, 2], face_n)

        # 正規化（避免除以 0）
        lengths = np.linalg.norm(normals, axis=1, keepdims=True)
        lengths[lengths == 0] = 1.0
        return (normals / lengths).astype(np.float32)

    @staticmethod
    def _cull_long_edge_faces(
        points: np.ndarray, faces: np.ndarray, max_edge_ratio: float
    ) -> np.ndarray:
        """
        剔除 3D 邊長過大的三角形（放射狀拉伸面的最終防線）。

        對每個三角形計算三邊在 3D 的長度，取全體邊長的中位數為基準，
        任一邊 > max_edge_ratio × 中位邊長的三角形即剔除。中位數對長尾
        離群（正是放射線本身）穩健，不會被被剔除的對象拉高基準。

        向量化：無 Python 迴圈。輸入 faces (F,3) int、回傳過濾後的 faces。
        """
        v0 = points[faces[:, 0]]
        v1 = points[faces[:, 1]]
        v2 = points[faces[:, 2]]
        e01 = np.linalg.norm(v1 - v0, axis=1)
        e12 = np.linalg.norm(v2 - v1, axis=1)
        e20 = np.linalg.norm(v0 - v2, axis=1)
        max_edge = np.maximum(np.maximum(e01, e12), e20)   # 每面最長邊 (F,)

        median_edge = float(np.median(np.concatenate([e01, e12, e20])))
        if median_edge <= 0.0:
            return faces
        keep = max_edge <= (max_edge_ratio * median_edge)
        return faces[keep]
