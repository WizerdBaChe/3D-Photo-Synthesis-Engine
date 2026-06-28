"""
階層一單元測試：LDI 分層補洞引擎 (test_ldi.py)
================================================
驗證目標：
  - LDILayer / LDIScene 契約形狀與一致性
  - LDIBuilder.build 層數、由近到遠排序、契約 dtype
  - 背景層的 disocclusion 破洞（前景遮擋處）被 inpaint 預填（非黑洞）
  - 最遠背景底層 alpha 全 255（任何視差量不露黑洞）
  - num_layers=2/3 皆通；單層退化與平坦深度退化

規範：
  - 純 CPU、合成資料、秒級完成。
"""

import numpy as np
import pytest

from src.core.contracts import RGBDFrame, LDILayer, LDIScene
from src.core.ldi import LDIBuilder, get_ldi_builder, set_ldi_builder


# ---------------------------------------------------------------------------
# 合成測資：左半為近前景方塊、右半為遠背景
# ---------------------------------------------------------------------------

def make_frame(h: int = 32, w: int = 32) -> RGBDFrame:
    """近前景（depth=0.2，紅）佔左半；遠背景（depth=0.8，藍）佔右半。"""
    color = np.zeros((h, w, 3), dtype=np.uint8)
    depth = np.full((h, w), 0.8, dtype=np.float32)   # 預設遠背景
    color[:, :] = (0, 0, 255)                         # 背景藍 (BGR/RGB 無妨，測形狀)
    # 左半變成近前景
    fg = slice(0, w // 2)
    depth[:, fg] = 0.2
    color[:, fg] = (255, 0, 0)
    return RGBDFrame(color=color, depth=depth)


# ---------------------------------------------------------------------------
# 契約
# ---------------------------------------------------------------------------

class TestLDIContracts:

    def test_ldilayer_dimension_mismatch_raises(self):
        color = np.zeros((10, 10, 3), np.uint8)
        depth = np.zeros((10, 10), np.float32)
        alpha = np.zeros((5, 5), np.uint8)            # 故意不一致
        with pytest.raises(ValueError, match="維度一致性違反"):
            LDILayer(color=color, depth=depth, alpha=alpha,
                     depth_min=0.0, depth_max=1.0)

    def test_ldiscene_num_layers_property(self):
        scene = LDIScene(layers=[], width=4, height=4)
        assert scene.num_layers == 0


# ---------------------------------------------------------------------------
# LDIBuilder
# ---------------------------------------------------------------------------

class TestLDIBuilder:

    def test_two_layers_basic(self):
        scene = LDIBuilder().build(make_frame(), num_layers=2)
        assert isinstance(scene, LDIScene)
        assert scene.num_layers == 2
        assert scene.width == 32 and scene.height == 32

    def test_layers_sorted_near_to_far(self):
        """層由近到遠：前層的 depth_min 應 <= 後層的 depth_min。"""
        scene = LDIBuilder().build(make_frame(), num_layers=2)
        mins = [l.depth_min for l in scene.layers]
        assert mins == sorted(mins)

    def test_contract_dtypes(self):
        scene = LDIBuilder().build(make_frame(), num_layers=2)
        for l in scene.layers:
            assert l.color.dtype == np.uint8
            assert l.depth.dtype == np.float32
            assert l.alpha.dtype == np.uint8
            assert l.color.shape == (32, 32, 3)
            assert l.depth.shape == (32, 32)
            assert l.alpha.shape == (32, 32)

    def test_background_disocclusion_filled(self):
        """
        背景層在「前景遮擋處」(左半) 應被 inpaint 填成背景內容，alpha=255，
        而非黑洞——這是 LDI 補洞的核心驗收。
        """
        scene = LDIBuilder().build(make_frame(), num_layers=2)
        bg = scene.layers[-1]                          # 最遠背景底層
        # 左半（原本是前景）在背景層應為有效（被預填）。
        left = bg.alpha[:, :16]
        assert np.all(left == 255), "背景層遮擋區未被預填（出現透空/黑洞）"

    def test_background_layer_fully_opaque(self):
        """最遠背景底層 alpha 全 255（任何視差量都不露黑洞）。"""
        scene = LDIBuilder().build(make_frame(), num_layers=2)
        assert np.all(scene.layers[-1].alpha == 255)

    def test_three_layers(self):
        """三帶深度（0.2/0.5/0.8）應切出多層且不崩。"""
        h = w = 30
        color = np.zeros((h, w, 3), np.uint8)
        depth = np.full((h, w), 0.5, np.float32)
        depth[:, :10] = 0.2
        depth[:, 20:] = 0.8
        scene = LDIBuilder().build(RGBDFrame(color=color, depth=depth), num_layers=3)
        assert scene.num_layers >= 2          # 至少切出多層
        assert np.all(scene.layers[-1].alpha == 255)

    def test_single_layer_degenerate(self):
        scene = LDIBuilder().build(make_frame(), num_layers=1)
        assert scene.num_layers == 1
        assert np.all(scene.layers[0].alpha == 255)

    def test_flat_depth_degenerate(self):
        """全平深度：無從分層，不應崩潰，回至少一層不透明。"""
        color = np.zeros((16, 16, 3), np.uint8)
        depth = np.full((16, 16), 0.5, np.float32)
        scene = LDIBuilder().build(RGBDFrame(color=color, depth=depth), num_layers=2)
        assert scene.num_layers >= 1
        assert np.all(scene.layers[-1].alpha == 255)


# ---------------------------------------------------------------------------
# Provider 單例
# ---------------------------------------------------------------------------

class TestLDIProvider:

    def test_default_is_ldibuilder(self):
        assert isinstance(get_ldi_builder(), LDIBuilder)

    def test_set_and_restore(self):
        original = get_ldi_builder()
        try:
            sentinel = LDIBuilder(min_band_ratio=0.5)
            set_ldi_builder(sentinel)
            assert get_ldi_builder() is sentinel
        finally:
            set_ldi_builder(original)
