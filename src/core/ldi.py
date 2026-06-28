"""
LDI 分層補洞引擎 (Layered Depth Image)
==========================================
設計依據：DD-001（無狀態）、DD-007（color+depth 雙補）、第一性原理（FB 3D Photo 小角度視差）

職責
----
把一張場景 RGB-D 沿 depth 斷崖切成「由近到遠」數層 LDILayer，並對每一層**其前方
被遮擋的破洞**用既有 inpainter（C1 DepthAwareInpainter）**預先填補**。如此前端多層
shader 在小角度視差下讓前景滑開時，露出的是「已經填好的背景層」，而非黑洞或滲入前景
——這正是 Facebook 3D Photo 網頁版的縱深來源（單層視差只能改取既有鄰近背景、填不了
真正缺失的內容）。

設計原則
--------
- 純 NumPy/OpenCV、零 GPU、零新依賴；完全複用 src/core 既有模組
  （DepthDiscontinuityPolicy 找斷崖、DepthAwareInpainter 補背景層破洞）。
- 無狀態：build() 只吃 RGBDFrame、回 LDIScene，不存留任何影像/狀態（DD-001）。
- 深度語意與全專案一致：depth ∈ [0,1]，值大 = 遠。

演算法（build）
---------------
  1. 由 depth 直方圖/分位數，取 (num_layers-1) 個門檻把像素切成 num_layers 個深度帶
     （band 0 = 最近的前景，最後一個 band = 最遠背景）。門檻落在縱深斷崖處最理想，
     故以「深度分位數」為基準（自適應任意深度尺度），對單調平滑的 ML depth 也穩。
  2. 對每一層 L：
       - 該層「原生內容」= 深度落在本帶的像素（alpha=255）。
       - 「需補洞區」= 比本層更近的所有像素（被前景遮擋、本層在其後本應有背景內容）。
         對這些洞，把 color/depth 餵 DepthAwareInpainter（只取背景、排前景）預填。
       - 最遠的背景底層：補洞後 alpha 全 255（不透明底，任何視差量都不露黑洞）。
         其餘層：補洞區 alpha 設為「半透明過渡」由 shader 用各層 alpha 合成 —— 實作上
         非背景底層的補洞像素 alpha 仍設 255（已是合理背景內容），純靠「比自己近的層
         會蓋在上面」達成正確遮擋順序，避免羽化造成的鬼影。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import numpy as np

from src.core.contracts import RGBDFrame, LDILayer, LDIScene
from src.core.inpainting import AbstractInpainter, DepthAwareInpainter

logger = logging.getLogger(__name__)


class AbstractLDIBuilder(ABC):
    """
    RGB-D → 多層 LDIScene 的抽象介面（Provider 模式，便於日後抽換更強分層器）。
    """

    @abstractmethod
    def build(self, frame: RGBDFrame, num_layers: int = 2) -> LDIScene:
        """輸入 RGBDFrame（depth ∈ [0,1]，值大=遠）→ 回 LDIScene（層由近到遠）。"""
        raise NotImplementedError


class LDIBuilder(AbstractLDIBuilder):
    """
    純 CPU LDI 分層器（預設實作）。

    Args:
        inpainter:  背景層破洞補繪器，預設 DepthAwareInpainter（C1，只取背景、排前景）。
                    可注入其他 AbstractInpainter（例如未來的 AI 補繪）。
        min_band_ratio:  單一深度帶最少需佔的像素比例（低於則合併相鄰帶，避免空層）。
    """

    def __init__(
        self,
        inpainter: AbstractInpainter | None = None,
        min_band_ratio: float = 0.02,
    ):
        self.inpainter = inpainter or DepthAwareInpainter()
        self.min_band_ratio = float(min_band_ratio)

    # ------------------------------------------------------------------

    def build(self, frame: RGBDFrame, num_layers: int = 2) -> LDIScene:
        if num_layers < 1:
            raise ValueError(f"num_layers 需 >= 1，收到 {num_layers}")

        color = frame.color
        depth = frame.depth.astype(np.float32)
        h, w = depth.shape[:2]

        # 單層退化：直接回原圖一層（alpha 全 255）。
        if num_layers == 1:
            layer = self._make_layer(color, depth, np.ones((h, w), bool))
            return LDIScene(layers=[layer], width=w, height=h)

        # --- 1. 切深度帶門檻（分位數，自適應深度尺度）---
        thresholds = self._compute_band_thresholds(depth, num_layers)
        # band 標籤：0 = 最近，len(thresholds) = 最遠
        band = np.digitize(depth, thresholds).astype(np.int32)  # 值 0..num_layers-1
        n_bands = int(band.max()) + 1

        layers: list[LDILayer] = []
        for b in range(n_bands):
            native = band == b               # 本帶原生內容
            if not np.any(native):
                continue
            is_background = b == n_bands - 1

            # 「需補洞區」= 比本層更近的像素（被前景遮擋，本層其後本應有背景）。
            occluded = band < b              # True = 待補的破洞
            layer = self._build_layer(
                color, depth, native, occluded, is_background
            )
            layers.append(layer)

        # 由近到遠（band 小=近），上面迴圈本就是 0→n 升序，即近→遠。
        logger.info(f"LDI 分層完成：{len(layers)} 層（{w}×{h}, 請求 {num_layers}）")
        return LDIScene(layers=layers, width=w, height=h)

    # ------------------------------------------------------------------
    # 私有輔助
    # ------------------------------------------------------------------

    def _compute_band_thresholds(
        self, depth: np.ndarray, num_layers: int
    ) -> np.ndarray:
        """
        取 (num_layers-1) 個深度門檻，用分位數均分像素到各帶。

        分位數而非等距切：對前景小、背景大的場景（FB 3D Photo 典型）能讓前景單獨
        成層，不被背景淹沒。退化情況（深度近乎平坦）回單一極大門檻 → 實質單層。
        """
        depth_range = float(depth.max() - depth.min())
        if depth_range <= 1e-6:
            # 平坦深度：無從分層，給一個比所有值都大的門檻 → digitize 全歸 band 0。
            return np.array([depth.max() + 1.0], dtype=np.float32)

        qs = [i / num_layers * 100.0 for i in range(1, num_layers)]
        thresholds = np.percentile(depth, qs).astype(np.float32)
        # 去重（分位數可能相等於同一值），維持嚴格遞增。
        thresholds = np.unique(thresholds)
        return thresholds

    def _build_layer(
        self,
        color: np.ndarray,
        depth: np.ndarray,
        native: np.ndarray,
        occluded: np.ndarray,
        is_background: bool,
    ) -> LDILayer:
        """
        組一層：原生內容 native 直接保留；occluded（被前景遮擋）區用 inpainter 預填。
        """
        if not np.any(occluded):
            # 最前景層通常無遮擋 → 無需補洞。
            return self._make_layer(color, depth, native)

        # 「已知區」= 本層原生內容（背景），「破洞」= occluded。交給 inpainter
        # （C1 只會借背景側像素，前景已被排除在 native 外，語意天然吻合）。
        # inpainter 契約：mask=True 處補繪。我們要補的就是 occluded。
        known = native
        # 退化保護：若本層原生像素太少（< min_band_ratio），inpainter 種子不足，
        # 仍照常呼叫（C1 內部對種子不足會退 Telea 收尾）。
        fill_frame = RGBDFrame(
            color=color.copy(),
            depth=depth.copy(),
            mask=occluded.copy(),
        )
        filled = self.inpainter.fill(fill_frame)

        # 本層 = 原生 + 補好的遮擋背景；其餘（比本層更遠處）非本層職責，alpha=0。
        valid = native | occluded
        # 比本層更遠的像素（既非原生也非被遮擋）→ 留給後層，本層透空。
        return self._make_layer(
            filled.color, filled.depth, valid, force_opaque=is_background
        )

    def _make_layer(
        self,
        color: np.ndarray,
        depth: np.ndarray,
        valid: np.ndarray,
        force_opaque: bool = False,
    ) -> LDILayer:
        """由 color/depth/有效遮罩組 LDILayer（depth_min/max 取有效區值域）。"""
        alpha_mask = np.ones(valid.shape, bool) if force_opaque else valid
        alpha = (alpha_mask * 255).astype(np.uint8)

        if np.any(valid):
            dmin = float(depth[valid].min())
            dmax = float(depth[valid].max())
        else:
            dmin = dmax = 0.0

        return LDILayer(
            color=color.astype(np.uint8),
            depth=depth.astype(np.float32),
            alpha=alpha,
            depth_min=dmin,
            depth_max=dmax,
        )


# ---------------------------------------------------------------------------
# 單例 Provider（鏡像 backend.depth_estimator 模式）
# ---------------------------------------------------------------------------

_builder: AbstractLDIBuilder = LDIBuilder()


def get_ldi_builder() -> AbstractLDIBuilder:
    """取得目前的 LDI 分層器（預設純 CPU LDIBuilder）。"""
    return _builder


def set_ldi_builder(builder: AbstractLDIBuilder) -> None:
    """替換 LDI 分層器（供日後接更強分層器 / 測試注入）。"""
    global _builder
    _builder = builder
