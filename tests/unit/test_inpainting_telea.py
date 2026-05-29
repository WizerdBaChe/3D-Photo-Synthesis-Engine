"""
階層一單元測試：Telea 修補器 (test_inpainting_telea.py)
========================================================
驗證目標（02_verification_testing.md §2.2）：
  - 快速路徑：無遮罩 / 全 False 遮罩時直接回傳，不執行修補
  - 修補後輸出 shape 與 dtype 維持不變
  - 修補後 mask 清空為 None（填補完成契約）
  - 遮罩區域 color 與 depth 已被填入非零值（修補確實有效）
  - 輸出為全新 RGBDFrame 物件（不修改傳入的原始幀）

規範：
  - 不啟動 GUI、不佔用 GPU、< 1s / test
"""

import numpy as np
import numpy.testing as npt
import pytest

from src.core.contracts import RGBDFrame
from src.core.inpainting import TeleaInpainter


# ---------------------------------------------------------------------------
# 快速路徑（Fast Path）測試
# ---------------------------------------------------------------------------

class TestTeleaFastPath:
    """修補器在無需修補時應直接回傳，不做任何運算。"""

    def test_returns_same_object_when_mask_is_none(self, no_mask_rgbd_frame):
        """mask=None 時應原樣回傳同一物件（fast path 不複製資料）。"""
        inpainter = TeleaInpainter()
        result = inpainter.fill(no_mask_rgbd_frame)
        assert result is no_mask_rgbd_frame, (
            "mask=None 時應回傳原始 frame，而非新建物件。"
        )

    def test_returns_same_object_when_mask_all_false(self, all_false_mask_frame):
        """遮罩全為 False 時應原樣回傳同一物件。"""
        inpainter = TeleaInpainter()
        result = inpainter.fill(all_false_mask_frame)
        assert result is all_false_mask_frame, (
            "全 False 遮罩時應回傳原始 frame。"
        )


# ---------------------------------------------------------------------------
# 輸出契約驗證
# ---------------------------------------------------------------------------

class TestTeleaOutputContract:
    """驗證修補後輸出的 shape、dtype 與 mask 狀態。"""

    def test_output_color_shape_preserved(self, masked_rgbd_frame):
        """修補後 color.shape 必須與輸入一致。"""
        inpainter = TeleaInpainter()
        result = inpainter.fill(masked_rgbd_frame)
        assert result.color.shape == masked_rgbd_frame.color.shape, (
            f"color.shape 改變：{masked_rgbd_frame.color.shape} → {result.color.shape}"
        )

    def test_output_depth_shape_preserved(self, masked_rgbd_frame):
        """修補後 depth.shape 必須與輸入一致。"""
        inpainter = TeleaInpainter()
        result = inpainter.fill(masked_rgbd_frame)
        assert result.depth.shape == masked_rgbd_frame.depth.shape

    def test_output_color_dtype_is_uint8(self, masked_rgbd_frame):
        """修補後 color 必須維持 uint8（OpenCV inpaint 輸出型別保留）。"""
        inpainter = TeleaInpainter()
        result = inpainter.fill(masked_rgbd_frame)
        assert result.color.dtype == np.uint8, (
            f"color.dtype 應為 np.uint8，實際 {result.color.dtype}"
        )

    def test_output_depth_dtype_is_float32(self, masked_rgbd_frame):
        """修補後 depth 必須維持 float32（DD-004 精度規範）。"""
        inpainter = TeleaInpainter()
        result = inpainter.fill(masked_rgbd_frame)
        assert result.depth.dtype == np.float32, (
            f"depth.dtype 應為 np.float32，實際 {result.depth.dtype}"
        )

    def test_output_mask_is_none(self, masked_rgbd_frame):
        """修補完成後，輸出 frame 的 mask 必須為 None（填補完成契約）。"""
        inpainter = TeleaInpainter()
        result = inpainter.fill(masked_rgbd_frame)
        assert result.mask is None, (
            "修補完成後 mask 應清空為 None，表示無破洞殘留。"
        )

    def test_output_is_new_object(self, masked_rgbd_frame):
        """修補器必須回傳全新的 RGBDFrame，不應原地修改輸入幀（不可變性）。"""
        inpainter = TeleaInpainter()
        result = inpainter.fill(masked_rgbd_frame)
        assert result is not masked_rgbd_frame, (
            "fill() 應回傳新的 RGBDFrame，不得修改傳入的原始幀。"
        )

    def test_output_color_data_is_copy(self, masked_rgbd_frame):
        """輸出 color 矩陣應與輸入無共用記憶體（防止後續操作影響原資料）。"""
        original_color = masked_rgbd_frame.color.copy()
        inpainter = TeleaInpainter()
        result = inpainter.fill(masked_rgbd_frame)
        # 修改輸出不應影響輸入
        result.color[:] = 0
        npt.assert_array_equal(
            masked_rgbd_frame.color, original_color,
            err_msg="修改輸出 color 不應影響原始輸入的 color 矩陣。"
        )


# ---------------------------------------------------------------------------
# 修補效果驗證
# ---------------------------------------------------------------------------

class TestTeleaInpaintEffect:
    """確認遮罩區域確實被填入了內容（修補不是 no-op）。"""

    def test_masked_region_color_is_filled(self):
        """
        遮罩中心區域的 color 像素，修補後不應全為 0（應被鄰近像素填補）。
        使用具有鮮明顏色的周圍像素，確保 Telea 有值可以借用。
        """
        color = np.zeros((20, 20, 3), dtype=np.uint8)
        # 設定周圍圈為紅色，確保修補器有非零像素可參考
        color[0:5, :] = [255, 0, 0]
        color[15:, :] = [255, 0, 0]
        color[:, 0:5] = [255, 0, 0]
        color[:, 15:] = [255, 0, 0]

        depth = np.ones((20, 20), dtype=np.float32)
        mask  = np.zeros((20, 20), dtype=np.bool_)
        mask[8:12, 8:12] = True   # 中央 4×4 破洞

        frame = RGBDFrame(color=color, depth=depth, mask=mask)
        inpainter = TeleaInpainter(inpaint_radius=5)
        result = inpainter.fill(frame)

        # 修補區域不應全為 0（應被周圍紅色填入）
        repaired_region = result.color[8:12, 8:12]
        assert repaired_region.sum() > 0, (
            "修補後中央遮罩區域仍全為 0，Telea 修補未正確執行。"
        )

    def test_masked_region_depth_is_filled(self):
        """
        深度圖遮罩區域，修補後不應保留原始值。
        將遮罩區深度設為 0，修補後應被鄰近深度值填補為非零。
        """
        depth = np.ones((20, 20), dtype=np.float32) * 0.5  # 背景深度 0.5
        color = np.full((20, 20, 3), 128, dtype=np.uint8)
        mask  = np.zeros((20, 20), dtype=np.bool_)
        mask[8:12, 8:12] = True
        depth[mask] = 0.0   # 破洞處深度設為 0

        frame = RGBDFrame(color=color, depth=depth, mask=mask)
        inpainter = TeleaInpainter(inpaint_radius=5)
        result = inpainter.fill(frame)

        repaired_depth_region = result.depth[8:12, 8:12]
        assert repaired_depth_region.mean() > 0.0, (
            "修補後深度圖遮罩區域仍為 0，深度修補未正確執行。"
        )

    def test_non_masked_region_color_unchanged(self):
        """修補器不應改變非遮罩區域的 color 像素值。"""
        color = np.full((20, 20, 3), 100, dtype=np.uint8)
        depth = np.ones((20, 20), dtype=np.float32)
        mask  = np.zeros((20, 20), dtype=np.bool_)
        mask[9, 9] = True  # 只有一個像素需要修補

        frame = RGBDFrame(color=color, depth=depth, mask=mask)
        inpainter = TeleaInpainter()
        result = inpainter.fill(frame)

        # 遠離遮罩的區域（左上角）不應被改動
        npt.assert_array_equal(
            result.color[0:5, 0:5],
            color[0:5, 0:5],
            err_msg="非遮罩區域的 color 不應被修補器更動。"
        )


# ---------------------------------------------------------------------------
# 初始化參數驗證
# ---------------------------------------------------------------------------

class TestTeleaInit:

    def test_default_radius_is_3(self):
        inpainter = TeleaInpainter()
        assert inpainter.radius == 3

    def test_custom_radius_is_stored(self):
        inpainter = TeleaInpainter(inpaint_radius=7)
        assert inpainter.radius == 7
