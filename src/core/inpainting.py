"""
遮擋修補服務 (Inpainting Service)
===================================
設計依據：DD-007（RGB+Depth 雙重修補）、DD-008（雙模式顯存管理）、BR-001（繼承體系）

規範：
- 所有修補策略必須繼承 AbstractInpainter（BR-001）。
- fill() 必須同時修補 color 與 depth 矩陣（DD-007）。
- 模組為無狀態物件，不存留影像或網格狀態（DD-001）。
- DepthAwareInpainter（Phase 4 C1）為現行主修補器：DIBR 原則「只取背景、排前景」，
  純 CPU、零 GPU 依賴；TeleaInpainter 續留作降級 fallback 與其殘餘收尾。
- LaMaInpainter 為 AI 路線架構佔位符，整合時參照 PSM Phase 4 規範。
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
# Depth-aware 修補器（Phase 4 — C1：DIBR 只取背景、排除前景）
# ---------------------------------------------------------------------------

class DepthAwareInpainter(AbstractInpainter):
    """
    Depth-aware（DIBR 原則）CPU 修補器 — Phase 4 軌道一 C1 的主修補策略。

    解決的問題（與純 Telea 的差異）
    --------------------------------
    斷崖破洞發生在「前景物件」與「其背後背景」的交界。視角移動時露出的，
    在物理上**屬於背景**（前景擋住的是背景，不是反過來）。但 Telea 的
    Fast-Marching 不分前後景，會把破洞邊界**兩側**的色彩一起往內擴散，
    使前景色滲入洞中（房間圖「床上冒出右側櫃子木色」、花瓶窗景物件撥離）。

    DIBR（Depth-Image-Based Rendering）的關鍵修正：補洞時**只取背景側**
    （depth 較大 = 較遠）的鄰域像素，用 depth 把前景鄰居排除在外。

    演算法（depth-gated 背景擴散，純 NumPy/OpenCV、零 GPU、無狀態）
    --------------------------------------------------------------
      1. 由破洞外緣一圈的有效像素，估出「背景深度門檻」：取邊界鄰域深度的
         high 分位數（bg_percentile，預設 50）為界 —— 比它更近的視為前景，
         不得參與填補。
      2. 以該門檻把有效像素切成「背景種子（可借用）」與「前景（禁用）」。
      3. 對破洞做**迭代式背景擴散**：每一輪僅允許背景已知像素把 color/depth
         往尚未填補的破洞像素傳遞（3×3 鄰域均值），逐圈往洞內收斂，直到填滿
         或達到 max_iter。前景像素全程不參與 → 從機制上杜絕前景滲入。
      4. 仍有殘餘未填（背景種子不足）→ 對殘餘區以 Telea 收尾，確保無破洞殘留。
      5. depth 比照 TeleaInpainter 裁回原始有效值域，避免外插尖刺。

    與既有架構的相容性
    ------------------
      - 完全沿用 AbstractInpainter.fill 契約（fast path、輸出新 frame、
        mask 清為 None、color uint8 / depth float32）。
      - 純 CPU、不引入任何重依賴；可直接注入 Orchestrator 的 primary，
        Telea 留作 fallback。OOM 降級鏈不受影響（本類別不會拋 VRAMExhaustedError）。

    Args:
        bg_percentile:  背景深度門檻分位數（0~100）。越高 → 越嚴格只取最遠像素，
                        前景排除越乾淨，但可借用的種子越少。預設 50（中位數）。
        max_iter:       背景擴散最大輪數（每輪約往洞內推進一圈像素）。預設 64，
                        足以填滿斷崖破洞這類細長區域；達上限的殘餘交給 Telea。
        telea_radius:   收尾 Telea 修補半徑。
    """

    def __init__(
        self,
        bg_percentile: float = 50.0,
        max_iter: int = 64,
        telea_radius: int = 3,
    ):
        self.bg_percentile = float(bg_percentile)
        self.max_iter      = int(max_iter)
        self.telea_radius  = int(telea_radius)
        self._fallback     = TeleaInpainter(inpaint_radius=telea_radius)

    def fill(self, frame: RGBDFrame) -> RGBDFrame:
        # 快速路徑：無遮罩或全 False，直接原樣回傳（契約一致）
        if frame.mask is None or not np.any(frame.mask):
            return frame

        hole = frame.mask.astype(bool)
        valid = ~hole
        depth_f32 = frame.depth.astype(np.float32)

        # 全圖皆為破洞的退化情況：無任何有效像素可借 → 交給 Telea（其內部處理）
        if not np.any(valid):
            return self._fallback.fill(frame)

        # --- 1. 估背景深度門檻：取「破洞外緣一圈」有效像素深度的高分位數 ---
        #     只看緊鄰破洞的邊界像素，門檻才反映「這個洞背後的背景」而非全圖。
        kernel = np.ones((3, 3), np.uint8)
        hole_u8 = hole.astype(np.uint8)
        dilated = cv2.dilate(hole_u8, kernel, iterations=1).astype(bool)
        border = dilated & valid                      # 緊貼破洞的有效像素環
        sample = depth_f32[border] if np.any(border) else depth_f32[valid]
        bg_threshold = float(np.percentile(sample, self.bg_percentile))

        # --- 2. 背景種子：有效且 depth >= 門檻（較遠）。前景（較近）排除 ---
        background_seed = valid & (depth_f32 >= bg_threshold)
        if not np.any(background_seed):
            # 邊界全是前景（無背景可借）→ 放寬為「全部有效像素」當種子，
            # 仍走擴散（至少不會比 Telea 差，且維持單一程式路徑）。
            background_seed = valid

        # --- 3. depth-gated 迭代背景擴散 ---
        color = frame.color.astype(np.float32)
        depth = depth_f32.copy()
        known = background_seed.copy()                # 目前可作為來源的「已知背景」
        remaining = hole.copy()                       # 尚未填補的破洞

        for _ in range(self.max_iter):
            if not np.any(remaining):
                break
            known_u8 = known.astype(np.uint8)
            # 已知區往外擴一圈，與「尚未填的破洞」交集 = 本輪可填的前緣
            grown = cv2.dilate(known_u8, kernel, iterations=1).astype(bool)
            frontier = grown & remaining
            if not np.any(frontier):
                break  # 背景擴散到此為止（種子被前景包圍而無法再前進）

            # 前緣每個像素 = 其 3×3 鄰域內「已知像素」的均值（color + depth）
            cnt = cv2.filter2D(known_u8.astype(np.float32), -1, kernel.astype(np.float32))
            cnt_safe = np.where(cnt > 0, cnt, 1.0)
            for c in range(color.shape[2]):
                src = np.where(known, color[..., c], 0.0)
                acc = cv2.filter2D(src, -1, kernel.astype(np.float32))
                color[frontier, c] = (acc / cnt_safe)[frontier]
            d_src = np.where(known, depth, 0.0)
            d_acc = cv2.filter2D(d_src, -1, kernel.astype(np.float32))
            depth[frontier] = (d_acc / cnt_safe)[frontier]

            known[frontier] = True
            remaining[frontier] = False

        # --- 4. 殘餘（背景種子不足以填滿）交給 Telea 收尾，保證無破洞殘留 ---
        repaired_color = np.clip(color, 0, 255).astype(np.uint8)
        repaired_depth = depth.astype(np.float32)
        if np.any(remaining):
            leftover = RGBDFrame(
                color=repaired_color,
                depth=repaired_depth,
                mask=remaining,
            )
            patched = self._fallback.fill(leftover)
            repaired_color = patched.color
            repaired_depth = patched.depth.astype(np.float32)

        # --- 5. 防尖刺：depth 裁回原始有效值域（與 TeleaInpainter 一致）---
        lo = float(depth_f32[valid].min())
        hi = float(depth_f32[valid].max())
        repaired_depth = np.clip(repaired_depth, lo, hi).astype(np.float32)

        return RGBDFrame(color=repaired_color, depth=repaired_depth, mask=None)


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
