"""
核心資料契約 (Data Contracts)
=================================
設計依據：DD-004（嚴格型別與形狀註解）、DD-001（無狀態分層模組）

規範：
- 所有跨模組資料傳輸物件必須使用 @dataclass 封裝。
- ndarray 欄位必須標註 Shape 與 dtype。
- 模組邊界必須先驗證這些資料契約，不允許傳遞裸 ndarray。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


# ---------------------------------------------------------------------------
# 輸入資料契約
# ---------------------------------------------------------------------------

@dataclass
class RGBDFrame:
    """
    正規化後的色彩與深度矩陣。

    約束（DD-004）：
      color.shape[:2] 必須等於 depth.shape[:2]（H, W 必須一致）。
    """
    color: np.ndarray        # Shape: (H, W, 3), dtype: np.uint8
    depth: np.ndarray        # Shape: (H, W),    dtype: np.float32
    mask:  Optional[np.ndarray] = field(default=None)
    # mask Shape: (H, W), dtype: np.bool_
    # True 代表需要修補的破洞區域

    def __post_init__(self):
        if self.color.shape[:2] != self.depth.shape[:2]:
            raise ValueError(
                f"[RGBDFrame] 維度一致性違反：\n"
                f"  color.shape = {self.color.shape[:2]}\n"
                f"  depth.shape = {self.depth.shape[:2]}\n"
                f"  請確保 RGB 圖片與深度圖解析度一致。"
            )


@dataclass(frozen=True)
class CameraIntrinsics:
    """
    相機內參矩陣（Pinhole Camera Model）。

    用途：幾何引擎進行像素→3D 反投影時使用。

    深度尺度（C-3 修正）：
      深度圖在載入時被正規化到 [0, 1]（相對深度 / 視差倒數），
      但反投影公式 X=(u-cx)*Z/fx 需要「具一致物理尺度」的 Z，
      否則不同圖片的 max 會把同一物體任意縮放、透視關係失真。
      因此將正規化深度 d∈[0,1] 線性映射回實際相機座標 Z：

          Z = depth_near + d * (depth_far - depth_near)

      depth_near / depth_far 定義場景在相機前方的近/遠平面（相機單位，如公尺）。
      這讓 3D 照片擁有穩定、可重現的深度分離（Facebook 3D Photo 視差效果的關鍵）。
    """
    fx: float                    # 焦距 X（像素單位）
    fy: float                    # 焦距 Y（像素單位）
    cx: float                    # 光心 X（像素單位）
    cy: float                    # 光心 Y（像素單位）
    width: int                   # 圖片寬度（像素）
    height: int                  # 圖片高度（像素）
    depth_near: float = 1.0      # 正規化深度 0 對應的實際 Z（相機前方近平面）
    depth_far:  float = 4.0      # 正規化深度 1 對應的實際 Z（相機前方遠平面）


# ---------------------------------------------------------------------------
# 輸出資料契約：平台無關的網格表示
# ---------------------------------------------------------------------------

@dataclass
class MeshData:
    """
    平台無關的 3D 網格資料（Web 架構核心輸出契約）。

    設計動機（去 Open3D 耦合）：
      舊桌面版 build_topology 直接回傳 o3d.geometry.TriangleMesh，使整個
      Core 綁死 Open3D。Web 架構下渲染交給前端 Three.js / WebGL，後端不需
      Open3D。改以純 NumPy 陣列封裝網格，序列化為 glTF / JSON 給前端即可。

    所有陣列皆為 row-major 展平，索引彼此對齊（vertices[i] 的顏色為 colors[i]）。
    """
    vertices: np.ndarray            # Shape: (V, 3), dtype: np.float32 — 3D 頂點座標
    faces:    np.ndarray            # Shape: (F, 3), dtype: np.int32   — 三角面頂點索引
    colors:   np.ndarray            # Shape: (V, 3), dtype: np.float32 — 頂點色 [0,1]
    normals:  Optional[np.ndarray] = field(default=None)
    # normals Shape: (V, 3), dtype: np.float32 — 頂點法線（可選，前端可自行計算）

    @property
    def vertex_count(self) -> int:
        return int(self.vertices.shape[0])

    @property
    def face_count(self) -> int:
        return int(self.faces.shape[0])


# ---------------------------------------------------------------------------
# 輸出資料契約：LDI（Layered Depth Image）分層補洞表示
# ---------------------------------------------------------------------------

@dataclass
class LDILayer:
    """
    LDI 單一深度層（Facebook 3D Photo 縱深補洞的核心單位）。

    一張場景照沿 depth 斷崖被切成由近到遠數層，每層是一張帶 alpha 的
    RGBA + depth 圖。前端多層 shader 由遠到近疊加、各層按自身深度做視差
    位移；前景層滑開時，露出的是「背景層**預先 inpaint 填好**」的內容，
    從而補掉小角度視差下的 disocclusion 空洞（單層視差填不了真正缺失內容）。

    語意約定（與全專案一致）：
      - depth ∈ [0,1] float32，值大 = 遠（metric 語意，同 /parallax）。
      - alpha：uint8，255 = 該層此像素有有效內容，0 = 透空（讓後層透出）。
        近層在「被自己佔據處」alpha=255、其餘 0；最遠的背景層補洞後 alpha 全 255
        （作為不透明底，保證任何視差量都不露黑洞）。
    """
    color: np.ndarray            # Shape: (H, W, 3), dtype: np.uint8
    depth: np.ndarray            # Shape: (H, W),    dtype: np.float32，值大=遠
    alpha: np.ndarray            # Shape: (H, W),    dtype: np.uint8，255=有效
    depth_min: float             # 本層有效像素的最小深度（近界）
    depth_max: float             # 本層有效像素的最大深度（遠界）

    def __post_init__(self):
        if self.color.shape[:2] != self.depth.shape[:2] or \
           self.color.shape[:2] != self.alpha.shape[:2]:
            raise ValueError(
                f"[LDILayer] 維度一致性違反：color={self.color.shape[:2]} "
                f"depth={self.depth.shape[:2]} alpha={self.alpha.shape[:2]}（H,W 須一致）。"
            )


@dataclass
class LDIScene:
    """
    多層 LDI 場景（LDIBuilder 的輸出契約、/ldi 端點與 .ldi 格式的來源）。

    layers 由「近到遠」排序（index 0 = 最前景，最後一個 = 補好洞的背景底）。
    """
    layers: list                 # list[LDILayer]，由近到遠
    width: int
    height: int

    @property
    def num_layers(self) -> int:
        return len(self.layers)


# ---------------------------------------------------------------------------
# 通訊 Payload 契約
# ---------------------------------------------------------------------------
#
# 註（Web 架構）：
#   相機位姿更新已完全移至前端（Three.js OrbitControls 在瀏覽器端即時旋轉），
#   後端不再需要任何位姿 DTO / IPC 指令。舊桌面版的 CameraPoseCommand /
#   MeshLoadCommand 等已封存於 archive/src/app/commands.py。
