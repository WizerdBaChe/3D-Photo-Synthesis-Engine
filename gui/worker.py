"""
AI 運算背景執行緒 (Synthesis Worker)
=======================================
設計依據：PSM Phase 7（Thread 1 — AI 運算背景執行緒）、Red Line 1（不阻塞主執行緒）

規範：
  - 所有耗時運算（幾何處理、修補、網格建構）必須在此 QThread 中執行。
  - 主執行緒（GUI）只透過 Signal 接收進度，不做任何業務邏輯（Red Line 1）。
  - 此類允許 import 核心引擎模組（src.core.*、src.app.*）。
  - GUI View 層（main_window.py）禁止 import 核心引擎模組。
"""

from __future__ import annotations
import logging
import queue

import numpy as np
from PySide6.QtCore import QThread, Signal

from src.core.contracts import RGBDFrame, CameraIntrinsics
from src.core.policies import SobelEdgeDetector
from src.core.geometry import GeometryProcessor
from src.core.inpainting import TeleaInpainter
from src.app.orchestrator import Orchestrator
from src.app.render_ipc import RenderProcessController

logger = logging.getLogger(__name__)

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False


class SynthesisWorker(QThread):
    """
    3D 合成管線的背景 QThread（PSM Phase 7, Thread 1）。

    Signals:
        progress_updated(int, str)  — 進度百分比 + 狀態訊息
        synthesis_finished()        — 管線成功完成
        synthesis_failed(str)       — 管線失敗，附帶錯誤訊息
    """

    progress_updated  = Signal(int, str)
    synthesis_finished = Signal()
    synthesis_failed  = Signal(str)

    def __init__(
        self,
        command_queue:     queue.Queue,
        render_controller: RenderProcessController,
        parent=None
    ):
        super().__init__(parent)
        self.command_queue     = command_queue
        self.render_controller = render_controller
        self._rgb_path:   str = None
        self._depth_path: str = None

    def set_files(self, rgb_path: str, depth_path: str):
        """設定待處理的 RGB 與深度圖路徑（在 start() 前呼叫）。"""
        self._rgb_path   = rgb_path
        self._depth_path = depth_path

    # ------------------------------------------------------------------
    # QThread 主體
    # ------------------------------------------------------------------

    def run(self):
        """
        在背景執行緒中執行完整的 3D 合成管線。
        透過 Signal 向 GUI 回報進度，不直接操作任何 GUI 元件。
        """
        try:
            self.progress_updated.emit(10, "載入 RGB-D 影像中...")
            frame = self._load_rgbd(self._rgb_path, self._depth_path)
            logger.info(f"影像載入完成：{frame.color.shape[:2]}")

            self.progress_updated.emit(25, "估算相機內參...")
            intrinsics = self._estimate_intrinsics(frame)

            self.progress_updated.emit(35, "初始化幾何引擎...")
            edge_policy  = SobelEdgeDetector(percentile=95.0)
            geo_processor = GeometryProcessor(intrinsics, edge_policy)

            self.progress_updated.emit(45, "初始化修補服務...")
            telea = TeleaInpainter(inpaint_radius=3)

            orchestrator = Orchestrator(
                geo_processor=geo_processor,
                primary_inpainter=telea,     # MVP：Telea 作為主修補器
                fallback_inpainter=telea,    # MVP：降級也使用 Telea
                render_controller=self.render_controller,
            )

            self.progress_updated.emit(55, "執行邊緣偵測與遮擋修補...")
            orchestrator.process_and_render(frame)

            self.progress_updated.emit(85, "通知渲染進程載入網格...")
            if not self.render_controller.is_alive():
                self.render_controller.start_process()

            self.progress_updated.emit(100, "合成完成！")
            self.synthesis_finished.emit()

        except FileNotFoundError as e:
            logger.error(f"檔案載入失敗：{e}")
            self.synthesis_failed.emit(f"找不到檔案：{e}")
        except Exception as e:
            logger.exception("合成管線發生未預期錯誤")
            self.synthesis_failed.emit(str(e))

    # ------------------------------------------------------------------
    # 私有輔助方法
    # ------------------------------------------------------------------

    def _load_rgbd(self, rgb_path: str, depth_path: str) -> RGBDFrame:
        """
        從檔案路徑載入 RGB 與深度圖，正規化並驗證資料契約（FR-001）。

        支援格式：
          RGB:   .png / .jpg / .jpeg / .bmp
          Depth: .png (8/16bit) / .exr (32bit float) / .tiff
        """
        if not _CV2_AVAILABLE:
            raise RuntimeError("OpenCV (cv2) 未安裝，請執行: pip install opencv-python")

        # 載入 RGB（BGR → RGB 轉換）
        color_bgr = cv2.imread(rgb_path)
        if color_bgr is None:
            raise FileNotFoundError(f"無法載入 RGB 圖片：{rgb_path}")
        color_rgb = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)

        # 載入深度圖（支援多種位元深度）
        depth_raw = cv2.imread(depth_path, cv2.IMREAD_ANYDEPTH | cv2.IMREAD_GRAYSCALE)
        if depth_raw is None:
            raise FileNotFoundError(f"無法載入深度圖：{depth_path}")

        # 正規化深度圖至 float32 [0, 1]
        depth_f32 = depth_raw.astype(np.float32)
        max_val = depth_f32.max()
        if max_val > 1.0:
            depth_f32 /= max_val

        # 解析度對齊：若 RGB 與 Depth 解析度不一致，縮放 Depth 至 RGB 尺寸
        h_rgb, w_rgb = color_rgb.shape[:2]
        h_dep, w_dep = depth_f32.shape[:2]
        if (h_rgb, w_rgb) != (h_dep, w_dep):
            logger.warning(
                f"RGB ({w_rgb}x{h_rgb}) 與 Depth ({w_dep}x{h_dep}) 解析度不一致，"
                f"自動縮放 Depth 圖。"
            )
            depth_f32 = cv2.resize(depth_f32, (w_rgb, h_rgb), interpolation=cv2.INTER_LINEAR)

        return RGBDFrame(color=color_rgb, depth=depth_f32)

    @staticmethod
    def _estimate_intrinsics(frame: RGBDFrame) -> CameraIntrinsics:
        """
        依圖片解析度估算相機內參（假設水平 FOV = 60°）。

        實際整合時，應從相機設備或 EXIF 資料取得真實內參。
        """
        h, w = frame.color.shape[:2]
        # FOV 60° → fx = w / (2 * tan(30°))
        fx = fy = w / (2.0 * np.tan(np.radians(30.0)))
        cx, cy = w / 2.0, h / 2.0
        return CameraIntrinsics(fx=fx, fy=fy, cx=cx, cy=cy, width=w, height=h)
