"""
管線協調層 (Orchestrator)
===========================
設計依據：DD-001（無狀態）、DD-007/008（雙修補 + OOM 容錯）

規範：
- Orchestrator 不知道任何 UI / 渲染 / 傳輸框架的存在（DD-009）。
- 無狀態協調者：只注入依賴，不持有影像或網格狀態。
- 捕捉 VRAMExhaustedError 並自動降級至 TeleaInpainter（DD-008）。

Web 架構：
  process() 純粹回傳平台無關的 MeshData，由呼叫端（FastAPI）負責序列化為
  glTF / JSON 給前端 Three.js 渲染。不再涉及 Open3D / 暫存 .ply / 子進程 IPC。
"""

from __future__ import annotations
import logging

from src.core.contracts import RGBDFrame, MeshData
from src.core.geometry import GeometryProcessor
from src.core.inpainting import AbstractInpainter, TeleaInpainter, VRAMExhaustedError

logger = logging.getLogger(__name__)


class Orchestrator:
    """
    無狀態管線協調層。

    協調流程：
      1. 邊緣斷邊偵測（設定 frame.mask）
      2. 修補（primary，含 OOM 自動降級至 fallback）
      3. 點雲反投影 + 三角拓樸建立 → MeshData

    Args:
        geo_processor:       GeometryProcessor 實例（已注入 intrinsics + edge_policy）
        primary_inpainter:   主要修補策略（MVP 為 TeleaInpainter，生產可換 LaMaInpainter）
        fallback_inpainter:  降級修補策略（始終為 TeleaInpainter）
    """

    def __init__(
        self,
        geo_processor:      GeometryProcessor,
        primary_inpainter:  AbstractInpainter,
        fallback_inpainter: TeleaInpainter,
    ):
        self.geo_processor      = geo_processor
        self.primary_inpainter  = primary_inpainter
        self.fallback_inpainter = fallback_inpainter

    # ------------------------------------------------------------------
    # 公開介面
    # ------------------------------------------------------------------

    def process(self, frame: RGBDFrame) -> MeshData:
        """
        主合成管線：從 RGB-D 幀產生平台無關的 3D 網格資料。

        階段：
          1. 邊緣偵測 → 設定 frame.mask（斷崖位置）
          2. 修補（primary / fallback）→ 無破洞的 repaired_frame
          3. 點雲反投影 + 拓樸建立 → MeshData（vertices/faces/colors/normals）

        回傳：MeshData，供呼叫端序列化為 glTF / JSON。
        """
        logger.info("管線啟動：開始處理 RGB-D 幀")

        # Phase 1: 在原始 depth 上算斷崖位置，作為「破洞修補遮罩」交給 inpainter，
        #          使斷崖邊緣的 RGB/Depth 接縫被填補得更平滑（破洞語意）。
        frame.mask = self.geo_processor.edge_policy.compute_mask(frame.depth)
        logger.info(f"斷邊偵測完成，斷崖像素數: {int(frame.mask.sum())}")

        # Phase 2: 容錯修補（OOM 自動降級）；修補後 mask 被清為 None。
        repaired_frame = self._inpaint_with_fallback(frame)

        # Phase 3: 幾何處理（Bug C：build_topology 會在修補後 depth 上「重算」
        #          斷崖剔除遮罩，與 Phase 1 的破洞遮罩語意分離）。
        points = self.geo_processor.unproject_to_points(repaired_frame.depth)
        mesh   = self.geo_processor.build_topology(points, repaired_frame)
        logger.info(f"網格建構完成：{mesh.vertex_count} 頂點 / {mesh.face_count} 三角面")

        return mesh

    # ------------------------------------------------------------------
    # 私有輔助方法
    # ------------------------------------------------------------------

    def _inpaint_with_fallback(self, frame: RGBDFrame) -> RGBDFrame:
        """
        執行主要修補策略，捕捉 VRAMExhaustedError 後自動降級至 TeleaInpainter。

        設計（A-1 / C-4）：
          降級判定改為攔截專屬例外 VRAMExhaustedError，而非比對
          'out of memory' 字串。OOM 的辨識責任封裝在修補模組內部
          （見 LaMaInpainter.fill 的整合契約），Orchestrator 只關心業務語意：
          「主修補器宣告顯存耗盡 → 切換至 CPU 備案」。
          其他任何例外（含非 OOM 的 RuntimeError）一律向上拋出，不靜默吞掉。
        """
        try:
            result = self.primary_inpainter.fill(frame)
            logger.info("主修補策略執行成功")
            return result

        except VRAMExhaustedError as e:
            logger.warning(f"VRAM 不足 (OOM)：{e}")
            logger.warning("觸發 TeleaInpainter 降級備案...")
            result = self.fallback_inpainter.fill(frame)
            logger.info("降級修補完成")
            return result
