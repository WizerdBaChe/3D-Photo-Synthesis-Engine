"""
遮擋修補服務 (Inpainting Service)
===================================
設計依據：DD-007（RGB+Depth 雙重修補）、DD-008（雙模式顯存管理）、BR-001（繼承體系）

規範：
- 所有修補策略必須繼承 AbstractInpainter（BR-001）。
- fill() 必須同時修補 color 與 depth 矩陣（DD-007）。
- 模組為無狀態物件，不存留影像或網格狀態（DD-001）。
- LaMaInpainter 為 MVP 架構佔位符，整合時參照 PSM Phase 4 規範。
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from enum import Enum
from typing import Optional

import cv2
import numpy as np

from src.core.contracts import RGBDFrame


# ---------------------------------------------------------------------------
# 修補專屬例外（取代脆弱的字串比對降級判定）
# ---------------------------------------------------------------------------

class VRAMExhaustedError(RuntimeError):
    """
    顯存耗盡，需要觸發降級備案（DD-008）。

    設計動機：
      OOM 的判定責任應落在「最了解 PyTorch 行為」的修補模組內部，
      由修補器在捕捉到 CUDA OOM 後重新包裝拋出此例外。
      Orchestrator 只需捕捉此型別即可決定是否降級，
      不再依賴 'out of memory' in str(e) 這種對訊息格式的隱性假設。
    """
    pass


# ---------------------------------------------------------------------------
# 顯存管理策略列舉（DD-008）
# ---------------------------------------------------------------------------

class VramStrategy(Enum):
    """
    PERSISTENT : 效能優先 — 模型常駐 VRAM，推論延遲最低。
    LAZY        : 資源友善 — 推論結束後立即釋放顯存（torch.cuda.empty_cache）。
    """
    PERSISTENT = "persistent"
    LAZY       = "lazy"


# ---------------------------------------------------------------------------
# 抽象介面
# ---------------------------------------------------------------------------

class AbstractInpainter(ABC):
    """
    無狀態修補策略抽象介面（BR-001, DD-007）。

    所有繼承此介面的類別必須同時填補 color 與 depth 矩陣，
    確保補全後的 3D 空間具備合理的幾何深度（避免平面化或尖刺）。
    """

    @abstractmethod
    def fill(self, frame: RGBDFrame) -> RGBDFrame:
        """
        輸入：帶有 mask 的 RGBDFrame（mask 中 True 代表需要修補的區域）
        輸出：全新的 RGBDFrame，其 color 與 depth 已被填補，mask 清空為 None。

        契約：
          - 若 frame.mask is None 或全為 False，應直接原樣回傳 frame（快速路徑）。
          - 輸出的 depth 必須維持 float32 精度。
        """
        pass


# ---------------------------------------------------------------------------
# 基準線修補器 (Fallback)
# ---------------------------------------------------------------------------

class TeleaInpainter(AbstractInpainter):
    """
    基於 OpenCV Fast Marching Method (Telea) 的 CPU 修補器。

    角色：系統降級備案（DD-008 Fallback）與 MVP 主修補器。
    優勢：無需 GPU、無需模型權重、延遲穩定（< 1.0 秒 @ 1080p）。

    Args:
        inpaint_radius: 修補半徑（像素），值越大補洞越平滑，但耗時增加。
    """

    def __init__(self, inpaint_radius: int = 3):
        self.radius = inpaint_radius

    def fill(self, frame: RGBDFrame) -> RGBDFrame:
        # 快速路徑：無遮罩或遮罩全為 False，直接回傳
        if frame.mask is None or not np.any(frame.mask):
            return frame

        # 轉換 Mask 格式：np.bool_ → np.uint8（0 或 255）
        cv2_mask = (frame.mask * 255).astype(np.uint8)

        # 1. RGB 色彩修補（Shape: H, W, 3 → H, W, 3）
        repaired_color = cv2.inpaint(
            frame.color, cv2_mask, self.radius, cv2.INPAINT_TELEA
        )

        # 2. 深度圖修補（Shape: H, W → H, W，維持 float32 精度）
        #    cv2.inpaint 支援單通道 float32
        depth_f32 = frame.depth.astype(np.float32)
        repaired_depth = cv2.inpaint(
            depth_f32, cv2_mask, self.radius, cv2.INPAINT_TELEA
        )

        # 2b. 深度防尖刺裁切（DD-007 動機：避免破洞處深度外插成尖刺/拉伸）。
        #     Telea 在尖銳斷崖邊界會把深度外插到原值域之外，反投影後在 3D
        #     空間形成明顯尖刺。將修補後深度裁切回「原始有效像素」的值域，
        #     使補全的背景在 3D 中維持合理且平滑的幾何（Facebook 3D Photo 視覺品質）。
        valid = ~frame.mask
        if np.any(valid):
            lo = float(depth_f32[valid].min())
            hi = float(depth_f32[valid].max())
            repaired_depth = np.clip(repaired_depth, lo, hi)

        # 3. 回傳全新 DTO，清除遮罩（填補完成後無破洞）
        return RGBDFrame(
            color=repaired_color,
            depth=repaired_depth.astype(np.float32),
            mask=None
        )


# ---------------------------------------------------------------------------
# AI 修補器骨架（PSM Phase 4 架構佔位符）
# ---------------------------------------------------------------------------

class LaMaInpainter(AbstractInpainter):
    """
    基於 LaMa (Large Mask inpainting) 神經網路的 AI 修補器（架構佔位符）。

    MVP 狀態：此類別保留完整的架構骨架，但 fill() 尚未整合真實模型權重。
    Orchestrator 的 OOM 降級機制已可正確捕捉此類拋出的例外。

    整合步驟（PSM Phase 4 規範）：
      1. 將 LaMa 模型權重置於 model_path 指定路徑。
      2. 取消 fill() 中的 NotImplementedError，實作 _run_inference()。
      3. 依 VramStrategy 設定決定載入/釋放時機。

    Args:
        model_path:  LaMa 模型權重的路徑（.pth 或 .ckpt）。
        strategy:    VramStrategy.PERSISTENT 或 VramStrategy.LAZY。
    """

    def __init__(self, model_path: str, strategy: VramStrategy):
        self.model_path = model_path
        self.strategy   = strategy
        self.model      = None

        try:
            import torch
            self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        except ImportError:
            self.device = None

    # --- 顯存管理（DD-008）---

    def _load_model(self):
        """載入 LaMa 權重至顯存（PERSISTENT 策略在初始化時呼叫；LAZY 策略每次推論前呼叫）。"""
        # TODO: 整合實際模型時，取消下方 NotImplementedError，實作此方法。
        raise NotImplementedError("LaMaInpainter._load_model() 尚待整合模型權重。")

    def _unload_model(self):
        """徹底釋放 PyTorch 佔用的 VRAM（LAZY 策略在推論後呼叫）。"""
        import gc
        import torch
        if self.model is not None:
            del self.model
            self.model = None
            gc.collect()
            torch.cuda.empty_cache()

    # --- 修補主介面 ---

    def fill(self, frame: RGBDFrame) -> RGBDFrame:
        """
        MVP 注意：目前拋出 NotImplementedError 以明確指示尚未整合。

        整合契約（重製版）：
          真正接入模型後，推論區段必須以 try/except 捕捉 PyTorch 的 CUDA OOM，
          並重新包裝為 VRAMExhaustedError 拋出，例如：

              try:
                  with torch.no_grad():
                      repaired = self.model(image_tensor, mask_tensor)
              except torch.cuda.OutOfMemoryError as e:        # torch>=2.0
                  torch.cuda.empty_cache()
                  raise VRAMExhaustedError(str(e)) from e
              except RuntimeError as e:                        # 舊版 torch 相容
                  if "out of memory" in str(e).lower():
                      torch.cuda.empty_cache()
                      raise VRAMExhaustedError(str(e)) from e
                  raise

          Orchestrator 只攔截 VRAMExhaustedError 來決定是否降級，
          因此 OOM 的判定責任完全封裝在此模組內（消除字串比對耦合）。
        """
        raise NotImplementedError(
            "[LaMaInpainter] 模型尚未整合。\n"
            "MVP 階段請在 Orchestrator 中使用 TeleaInpainter 作為主修補器。\n"
            "整合步驟請參閱 PSM Phase 4 規範與 src/core/inpainting.py 註解。"
        )
