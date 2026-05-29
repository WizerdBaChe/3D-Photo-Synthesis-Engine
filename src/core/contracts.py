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
    """
    fx: float    # 焦距 X（像素單位）
    fy: float    # 焦距 Y（像素單位）
    cx: float    # 光心 X（像素單位）
    cy: float    # 光心 Y（像素單位）
    width: int   # 圖片寬度（像素）
    height: int  # 圖片高度（像素）


# ---------------------------------------------------------------------------
# 通訊 Payload 契約（IPC / Queue）
# ---------------------------------------------------------------------------

@dataclass
class CameraPoseUpdate:
    """
    相機位姿更新 DTO。

    用途：InputAdapter 計算後透過 Queue 傳遞給渲染引擎。
    注意：因含 ndarray 欄位，不設 frozen=True（ndarray 不可雜湊）。
    """
    extrinsic_matrix: np.ndarray  # Shape: (4, 4), dtype: np.float64
    timestamp: float              # Unix 時間戳，用於丟棄過期指令
