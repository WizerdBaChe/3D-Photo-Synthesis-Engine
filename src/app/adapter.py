"""
輸入適配器 (Input Adapter)
============================
設計依據：DD-009（GUI 與引擎徹底解耦）、PSM Phase 6.3、IO-001/002

職責：
  - 將 GUI 事件（滑桿數值、按鈕點擊）翻譯為數學矩陣或指令 DTO。
  - 翻譯後的 DTO 透過 Queue.put() 傳遞給後端，確保 GUI 與引擎完全解耦。

保證：
  - GUI 不需要了解矩陣計算（View is Dumb）。
  - 核心引擎不需要知道 PySide6 的存在。
"""

from __future__ import annotations
import queue
import time
from math import cos, radians, sin

import numpy as np

from src.app.commands import EngineCommand, EngineCommandType
from src.core.contracts import CameraPoseUpdate


class InputAdapter:
    """
    GUI 事件翻譯官（PSM Phase 6.3）。

    所有 on_*() 方法對應一個 GUI 的 Signal，負責：
      1. 接收原始 UI 數值（角度、路徑等）
      2. 翻譯為標準化 DTO（旋轉矩陣、指令物件）
      3. 透過 Queue 傳遞給後端（非同步，不阻塞 GUI 執行緒）

    Args:
        command_queue: 後端引擎監聽的指令佇列（EngineCommand）
        pose_queue:    渲染引擎監聽的位姿佇列（CameraPoseUpdate）
    """

    def __init__(self, command_queue: queue.Queue, pose_queue: queue.Queue):
        self.command_queue = command_queue
        self.pose_queue    = pose_queue

    # ------------------------------------------------------------------
    # 檔案載入事件
    # ------------------------------------------------------------------

    def on_load_files_requested(self, rgb_path: str, depth_path: str):
        """映射 GUI 的檔案選擇事件 → LOAD_IMAGE 指令"""
        cmd = EngineCommand(
            command_type=EngineCommandType.LOAD_IMAGE,
            payload={"rgb": rgb_path, "depth": depth_path}
        )
        self.command_queue.put(cmd)

    # ------------------------------------------------------------------
    # 視角控制事件（IO-001：滑鼠/滑桿 → 旋轉矩陣）
    # ------------------------------------------------------------------

    def on_rotation_slider_changed(
        self,
        pitch_deg: float,
        yaw_deg:   float,
        roll_deg:  float
    ):
        """
        將 GUI 的歐拉角（Pitch/Yaw/Roll，度數）轉換為 4×4 外參矩陣。

        旋轉順序：ZYX（Roll → Yaw → Pitch）
          Rx: 繞 X 軸旋轉（Pitch）
          Ry: 繞 Y 軸旋轉（Yaw）
          Rz: 繞 Z 軸旋轉（Roll）
          R  = Rz @ Ry @ Rx
        """
        p = radians(pitch_deg)
        y = radians(yaw_deg)
        r = radians(roll_deg)

        # 基礎旋轉矩陣（3×3）
        Rx = np.array([
            [1,      0,       0],
            [0,  cos(p), -sin(p)],
            [0,  sin(p),  cos(p)],
        ])
        Ry = np.array([
            [ cos(y), 0, sin(y)],
            [      0, 1,      0],
            [-sin(y), 0, cos(y)],
        ])
        Rz = np.array([
            [cos(r), -sin(r), 0],
            [sin(r),  cos(r), 0],
            [     0,       0, 1],
        ])

        # 複合旋轉（ZYX 順序）→ 嵌入 4×4 外參矩陣
        R = Rz @ Ry @ Rx
        extrinsic = np.eye(4, dtype=np.float64)
        extrinsic[:3, :3] = R

        update = CameraPoseUpdate(
            extrinsic_matrix=extrinsic,
            timestamp=time.time()
        )
        self.pose_queue.put(update)

    # ------------------------------------------------------------------
    # 合成觸發事件
    # ------------------------------------------------------------------

    def on_start_synthesis_requested(self):
        """觸發引擎開始執行合成管線"""
        cmd = EngineCommand(
            command_type=EngineCommandType.START_SYNTHESIS,
            payload={}
        )
        self.command_queue.put(cmd)
