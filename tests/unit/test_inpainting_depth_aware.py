"""
階層一單元測試：DepthAwareInpainter (test_inpainting_depth_aware.py)
====================================================================
驗證目標（Phase 4 軌道一 C1）：
  - 沿用 AbstractInpainter 契約：fast path、輸出新 frame、mask 清為 None、
    color uint8 / depth float32、shape 不變
  - DIBR 核心行為：補洞「只取背景側（depth 較大=較遠）」，排除前景滲入
  - 退化情況：全破洞 / 無背景種子時不崩潰（交給 Telea 收尾）
  - 殘餘區由 Telea 收尾，保證無破洞殘留

規範：
  - 不啟動 GUI、不佔用 GPU、< 1s / test
  - 純合成資料
"""

import numpy as np
import pytest

from src.core.contracts import RGBDFrame
from src.core.inpainting import DepthAwareInpainter, AbstractInpainter


# ---------------------------------------------------------------------------
# 快速路徑（Fast Path）
# ---------------------------------------------------------------------------

class TestDepthAwareFastPath:
    """無需修補時應直接回傳同一物件，不做任何運算（契約一致）。"""

    def test_returns_same_object_when_mask_is_none(self, no_mask_rgbd_frame):
        inpainter = DepthAwareInpainter()
        result = inpainter.fill(no_mask_rgbd_frame)
        assert result is no_mask_rgbd_frame

    def test_returns_same_object_when_mask_all_false(self, all_false_mask_frame):
        inpainter = DepthAwareInpainter()
        result = inpainter.fill(all_false_mask_frame)
        assert result is all_false_mask_frame


# ---------------------------------------------------------------------------
# 輸出契約
# ---------------------------------------------------------------------------

class TestDepthAwareOutputContract:

    def test_is_abstract_inpainter(self):
        """必須是 AbstractInpainter 子類別（可注入 Orchestrator primary）。"""
        assert issubclass(DepthAwareInpainter, AbstractInpainter)

    def test_output_shapes_preserved(self, masked_rgbd_frame):
        inpainter = DepthAwareInpainter()
        result = inpainter.fill(masked_rgbd_frame)
        assert result.color.shape == masked_rgbd_frame.color.shape
        assert result.depth.shape == masked_rgbd_frame.depth.shape

    def test_output_color_dtype_is_uint8(self, masked_rgbd_frame):
        result = DepthAwareInpainter().fill(masked_rgbd_frame)
        assert result.color.dtype == np.uint8

    def test_output_depth_dtype_is_float32(self, masked_rgbd_frame):
        result = DepthAwareInpainter().fill(masked_rgbd_frame)
        assert result.depth.dtype == np.float32

    def test_output_mask_is_none(self, masked_rgbd_frame):
        result = DepthAwareInpainter().fill(masked_rgbd_frame)
        assert result.mask is None, "修補完成後 mask 應清空為 None。"

    def test_output_is_new_object(self, masked_rgbd_frame):
        result = DepthAwareInpainter().fill(masked_rgbd_frame)
        assert result is not masked_rgbd_frame

    def test_no_hole_remains(self):
        """修補後不得有破洞殘留（殘餘交 Telea 收尾）。color 全部被填。"""
        color = np.full((20, 20, 3), 100, dtype=np.uint8)
        depth = np.ones((20, 20), dtype=np.float32)
        mask = np.zeros((20, 20), dtype=np.bool_)
        mask[8:12, 8:12] = True
        color[mask] = 0
        frame = RGBDFrame(color=color, depth=depth, mask=mask)
        result = DepthAwareInpainter().fill(frame)
        # 破洞區域被填為非零（鄰近 100 借入）
        assert result.color[8:12, 8:12].sum() > 0


# ---------------------------------------------------------------------------
# DIBR 核心行為：只取背景、排除前景
# ---------------------------------------------------------------------------

class TestDepthAwareDIBR:
    """
    構造一個「前景 vs 背景」場景，破洞夾在兩者之間，
    驗證補入的色彩來自背景側（遠）而非前景側（近）。
    """

    def _build_scene(self):
        """
        20×20：
          左半（col<9）= 前景，近（depth 0.1），鮮紅 [255,0,0]
          右半（col>=11）= 背景，遠（depth 0.9），鮮藍 [0,0,255]
          中間直條（col 9..10）= 破洞（前景遮住背景後露出的縫）
        DIBR 預期：破洞應被「背景藍」填入，而非「前景紅」。
        """
        H, W = 20, 20
        color = np.zeros((H, W, 3), dtype=np.uint8)
        depth = np.zeros((H, W), dtype=np.float32)
        # 前景（近、紅）
        color[:, :9] = [255, 0, 0]
        depth[:, :9] = 0.1
        # 背景（遠、藍）
        color[:, 11:] = [0, 0, 255]
        depth[:, 11:] = 0.9
        # 破洞縫
        mask = np.zeros((H, W), dtype=np.bool_)
        mask[:, 9:11] = True
        # 破洞處填中性值（會被覆蓋）
        depth[mask] = 0.5
        return RGBDFrame(color=color, depth=depth, mask=mask)

    def test_hole_filled_from_background_not_foreground(self):
        frame = self._build_scene()
        result = DepthAwareInpainter(bg_percentile=50.0).fill(frame)
        hole_region = result.color[:, 9:11].astype(np.int32)
        blue_strength = hole_region[..., 2].mean()   # 背景藍
        red_strength = hole_region[..., 0].mean()    # 前景紅
        assert blue_strength > red_strength, (
            f"破洞應由背景（藍）填補，實得 紅={red_strength:.1f} 藍={blue_strength:.1f}；"
            "前景色滲入代表 DIBR 排除前景失效。"
        )

    def test_filled_depth_is_background_level(self):
        """補入的 depth 應接近背景（遠，~0.9），而非前景（近，~0.1）。"""
        frame = self._build_scene()
        result = DepthAwareInpainter(bg_percentile=50.0).fill(frame)
        hole_depth = result.depth[:, 9:11].mean()
        assert hole_depth > 0.5, (
            f"補入深度 {hole_depth:.2f} 偏向前景；應接近背景遠值。"
        )

    def test_telea_would_blend_foreground(self):
        """
        對照組：純 Telea 在同場景會把前景紅一起糊進破洞（紅不再明顯小於藍）。
        此測試記錄 DepthAware 相對 Telea 的改善方向（非嚴格門檻，僅證明差異存在）。
        """
        from src.core.inpainting import TeleaInpainter
        frame = self._build_scene()
        telea = TeleaInpainter(inpaint_radius=3).fill(frame)
        depth_aware = DepthAwareInpainter(bg_percentile=50.0).fill(
            self._build_scene()
        )
        telea_red = telea.color[:, 9:11, 0].mean()
        da_red = depth_aware.color[:, 9:11, 0].mean()
        assert da_red <= telea_red + 1e-6, (
            f"DepthAware 補入的前景紅({da_red:.1f}) 應不多於 Telea({telea_red:.1f})。"
        )


# ---------------------------------------------------------------------------
# 退化 / 邊界情況
# ---------------------------------------------------------------------------

class TestDepthAwareDegenerate:

    def test_all_hole_falls_back_to_telea(self):
        """整張圖都是破洞（無任何有效像素）→ 不崩潰，交 Telea 處理。"""
        color = np.zeros((8, 8, 3), dtype=np.uint8)
        depth = np.ones((8, 8), dtype=np.float32)
        mask = np.ones((8, 8), dtype=np.bool_)
        frame = RGBDFrame(color=color, depth=depth, mask=mask)
        result = DepthAwareInpainter().fill(frame)
        assert result.mask is None
        assert result.color.shape == color.shape

    def test_no_background_seed_still_fills(self):
        """
        破洞邊界全是前景（無更遠的背景像素）→ 放寬種子，仍須填滿、不崩潰。
        全圖同一深度即無「更遠」者。
        """
        color = np.full((16, 16, 3), 70, dtype=np.uint8)
        depth = np.full((16, 16), 0.3, dtype=np.float32)
        mask = np.zeros((16, 16), dtype=np.bool_)
        mask[6:10, 6:10] = True
        color[mask] = 0
        frame = RGBDFrame(color=color, depth=depth, mask=mask)
        result = DepthAwareInpainter().fill(frame)
        assert result.mask is None
        assert result.color[6:10, 6:10].sum() > 0


class TestDepthAwareInit:

    def test_defaults(self):
        ip = DepthAwareInpainter()
        assert ip.bg_percentile == 50.0
        assert ip.max_iter == 64
        assert ip.telea_radius == 3

    def test_custom_params_stored(self):
        ip = DepthAwareInpainter(bg_percentile=75.0, max_iter=32, telea_radius=5)
        assert ip.bg_percentile == 75.0
        assert ip.max_iter == 32
        assert ip.telea_radius == 5
