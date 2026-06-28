"""
單元測試：RGB-D 載入 depth 語意統一 (test_rgbd_loader.py)
=========================================================
驗證 normalize_depth_semantics 把 disparity / metric / auto 統一成
metric（值大=遠），避免 disparity 圖造成深度反轉（Bug A）。
"""

import numpy as np
import numpy.testing as npt
import pytest

from backend.rgbd_loader import normalize_depth_semantics, _detect_is_disparity


class TestNormalizeDepthSemantics:

    def test_metric_passthrough(self):
        """metric：輸入不變（已是值大=遠）。"""
        d = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)
        out = normalize_depth_semantics(d, "metric")
        npt.assert_array_almost_equal(out, d)

    def test_disparity_inverts_ordering(self):
        """
        disparity（近=亮、值大）統一後應反轉為 metric：
        原本最亮（最近）的像素 → 統一後最小值（最近）。
        """
        # d=1.0 為最近（最大視差），d=0.0 為最遠
        d = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)
        out = normalize_depth_semantics(d, "disparity")
        # 反轉後：原最大值(最近)應變最小值；單調遞減
        assert out[0, 0] > out[0, 1] > out[0, 2]
        assert out.min() >= 0.0 and out.max() <= 1.0

    def test_invalid_convention_raises(self):
        d = np.array([[0.0, 1.0]], dtype=np.float32)
        with pytest.raises(ValueError, match="depth_convention"):
            normalize_depth_semantics(d, "nonsense")

    def test_flat_disparity_handled(self):
        """全平 disparity（無範圍）不應崩潰，回傳全 0。"""
        d = np.full((4, 4), 0.5, dtype=np.float32)
        out = normalize_depth_semantics(d, "disparity")
        assert out.shape == d.shape
        assert np.all(np.isfinite(out))


class TestAutoHeuristic:

    def test_disparity_like_image_detected(self):
        """少數很亮的近物 + 大片較暗背景（右偏）→ 判為 disparity。"""
        d = np.full((50, 50), 0.1, dtype=np.float32)   # 大片遠景（暗）
        d[20:25, 20:25] = 0.95                          # 少數近物（亮）
        assert _detect_is_disparity(d) is True

    def test_metric_like_image_detected(self):
        """大片高值（亮=遠）的 metric 圖（高值佔比大）→ 判為 metric。"""
        d = np.full((50, 50), 0.9, dtype=np.float32)   # 大片遠景（亮=遠，metric）
        d[20:25, 20:25] = 0.1                           # 少數近物（暗）
        assert _detect_is_disparity(d) is False

    def test_auto_routes_to_a_valid_output(self):
        """auto 模式輸出範圍合法且不崩潰。"""
        d = np.full((50, 50), 0.1, dtype=np.float32)
        d[20:25, 20:25] = 0.95
        out = normalize_depth_semantics(d, "auto")
        assert out.shape == d.shape
        assert out.min() >= 0.0 and out.max() <= 1.0
