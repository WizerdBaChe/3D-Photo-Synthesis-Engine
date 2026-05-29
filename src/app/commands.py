"""
指令資料契約 (Command DTOs)
==============================
設計依據：DD-003（Queue 非同步通訊）、DD-009（GUI 與引擎解耦）

規範：
- GUI 層只能透過這些 DTO 與後端溝通，禁止直接呼叫引擎模組（Red Line 3）。
- IPC 指令（MeshLoadCommand 等）嚴禁直接攜帶大型物件（Red Line 4）。
- 所有指令皆為輕量級 DTO，只傳遞路徑、純量或小型矩陣。
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

import numpy as np


# ---------------------------------------------------------------------------
# GUI → 後端核心引擎指令
# ---------------------------------------------------------------------------

class EngineCommandType(Enum):
    LOAD_IMAGE           = 1   # 載入 RGB-D 圖片
    CHANGE_VRAM_STRATEGY = 2   # 切換 VramStrategy
    START_SYNTHESIS      = 3   # 觸發合成管線


@dataclass
class EngineCommand:
    """
    前端發送給後端核心引擎的設定指令（DD-009）。

    payload 範例：
      LOAD_IMAGE:           {"rgb": "path/to/color.png", "depth": "path/to/depth.png"}
      CHANGE_VRAM_STRATEGY: {"strategy": VramStrategy.LAZY}
      START_SYNTHESIS:      {}
    """
    command_type: EngineCommandType
    payload: Dict[str, Any]


# ---------------------------------------------------------------------------
# 主進程 → 渲染子進程 IPC 指令（PSM Phase 5）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MeshLoadCommand:
    """
    通知渲染器載入新的 3D 網格。

    ⚠️ 實作約束（Red Line 4）：
      嚴禁直接傳遞 o3d.geometry.TriangleMesh 物件（序列化瓶頸）。
      必須先將網格存為暫存 .ply 檔，僅傳遞檔案路徑。
    """
    mesh_filepath: str   # 暫存 .ply 檔案的絕對路徑


@dataclass
class CameraPoseCommand:
    """
    通知渲染器更新相機視角。

    注意：因含 ndarray 欄位，不設 frozen=True（ndarray 不可雜湊）。
    IPC Queue 以「最新優先」原則處理此指令：
      RenderProcessController 在 put 前會清空佇列中舊的位姿指令。
    """
    extrinsic_matrix: np.ndarray   # Shape: (4, 4), dtype: np.float64


@dataclass(frozen=True)
class ShutdownCommand:
    """通知渲染器安全關閉視窗並退出子進程。"""
    pass
