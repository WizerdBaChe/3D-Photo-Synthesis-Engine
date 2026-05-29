"""
管線協調層 (Orchestrator)
===========================
設計依據：PSM Phase 4（最終版含 OOM 容錯）、DD-001、DD-008

規範：
- Orchestrator 不知道 PySide6/PyQt 的存在（DD-009）。
- Orchestrator 為無狀態協調者：只注入依賴，不持有影像或網格狀態。
- 捕捉 "out of memory" RuntimeError 並自動降級至 TeleaInpainter（DD-008）。
- 網格透過暫存 .ply 檔傳遞給渲染進程（避免序列化瓶頸，Red Line 4）。
"""

from __future__ import annotations
import logging
import os
import tempfile

import open3d as o3d

from src.core.contracts import RGBDFrame
from src.core.geometry import GeometryProcessor
from src.core.inpainting import AbstractInpainter, TeleaInpainter

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    無狀態管線協調層（PSM Phase 4 最終版）。

    協調流程：
      1. 邊緣斷邊偵測（設定 frame.mask）
      2. AI 修補（含 OOM 自動降級至 Telea）
      3. 點雲反投影 + 三角拓樸建立
      4. 序列化網格為 .ply 暫存檔，傳遞路徑給渲染控制器

    Args:
        geo_processor:       GeometryProcessor 實例（已注入 intrinsics + edge_policy）
        primary_inpainter:   主要修補策略（MVP 為 TeleaInpainter，生產環境為 LaMaInpainter）
        fallback_inpainter:  降級修補策略（始終為 TeleaInpainter）
        render_controller:   RenderProcessController 實例（負責 IPC 傳遞）
    """

    def __init__(
        self,
        geo_processor:      GeometryProcessor,
        primary_inpainter:  AbstractInpainter,
        fallback_inpainter: TeleaInpainter,
        render_controller,               # RenderProcessController（避免循環 import）
    ):
        self.geo_processor      = geo_processor
        self.primary_inpainter  = primary_inpainter
        self.fallback_inpainter = fallback_inpainter
        self.render_controller  = render_controller

    # ------------------------------------------------------------------
    # 公開介面
    # ------------------------------------------------------------------

    def process_and_render(self, frame: RGBDFrame) -> None:
        """
        主合成管線：從 RGB-D 幀到 3D 網格渲染，完整執行。

        階段：
          1. 邊緣偵測 → 設定 frame.mask（斷崖位置）
          2. 修補（primary / fallback）→ 回傳無破洞的 repaired_frame
          3. 點雲反投影 + 拓樸建立 → TriangleMesh
          4. 序列化網格 → .ply 暫存檔路徑 → 傳遞至渲染進程
        """
        logger.info("管線啟動：開始處理 RGB-D 幀")

        # Phase 1: 邊緣斷邊偵測（在原始 depth 上計算斷崖位置）
        frame.mask = self.geo_processor.edge_policy.compute_mask(frame.depth)
        edge_count = int(frame.mask.sum())
        logger.info(f"斷邊偵測完成，斷崖像素數: {edge_count}")

        # Phase 2: 容錯修補（OOM 自動降級）
        repaired_frame = self._inpaint_with_fallback(frame)

        # Phase 3: 幾何處理（在修補後的 depth 上建立完整拓樸）
        points = self.geo_processor.unproject_to_points(repaired_frame.depth)
        mesh   = self.geo_processor.build_topology(points, repaired_frame)
        face_count = len(mesh.triangles)
        logger.info(f"網格建構完成：{len(mesh.vertices)} 頂點 / {face_count} 三角面")

        # Phase 4: 序列化並傳遞給渲染進程（只傳路徑，不傳 Mesh 物件）
        mesh_path = self._save_mesh_to_tempfile(mesh)
        self.render_controller.load_mesh(mesh_path)
        logger.info(f"網格暫存至: {mesh_path}，已通知渲染進程")

    # ------------------------------------------------------------------
    # 私有輔助方法
    # ------------------------------------------------------------------

    def _inpaint_with_fallback(self, frame: RGBDFrame) -> RGBDFrame:
        """
        執行主要修補策略，捕捉 OOM RuntimeError 後自動降級至 TeleaInpainter。
        非 OOM 的 RuntimeError 將正常向上拋出（不靜默吞掉）。
        """
        try:
            result = self.primary_inpainter.fill(frame)
            logger.info("主修補策略執行成功")
            return result

        except RuntimeError as e:
            if "out of memory" in str(e).lower():
                logger.warning(f"VRAM 不足 (OOM)：{e}")
                logger.warning("觸發 TeleaInpainter 降級備案...")
                # 嘗試釋放 PyTorch 顯存（若未安裝 torch 則跳過）
                try:
                    import torch
                    torch.cuda.empty_cache()
                except ImportError:
                    pass
                result = self.fallback_inpainter.fill(frame)
                logger.info("降級修補完成")
                return result
            # 非 OOM 例外：記錄後重新拋出
            logger.error(f"修補管線發生非 OOM 例外：{e}")
            raise

    @staticmethod
    def _save_mesh_to_tempfile(mesh: o3d.geometry.TriangleMesh) -> str:
        """
        將 TriangleMesh 序列化為暫存 .ply 檔案，回傳絕對路徑。

        此設計避免了直接透過 IPC Queue 傳遞大型 3D Mesh 物件的序列化瓶頸
        （Red Line 4：嚴禁透過 Queue 直接傳遞大型 3D Mesh 物件）。
        """
        tmp = tempfile.NamedTemporaryFile(
            suffix=".ply", prefix="synthesis_mesh_", delete=False
        )
        tmp.close()
        o3d.io.write_triangle_mesh(tmp.name, mesh)
        return tmp.name
