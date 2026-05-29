"""
階層一單元測試：幾何處理器 (test_geometry.py)
===============================================
驗證目標（02_verification_testing.md §2.2）：
  - RGBDFrame 維度一致性合約
  - unproject_to_points 反投影輸出形狀與 Z 軸數值
  - build_topology 完整網格面數（162 面 @ 10×10）
  - build_topology 斷崖後面數減少（Tearing 生效）

規範：
  - 禁止啟動 GUI 或佔用真實 GPU（使用合成資料）。
  - 所有測試函數必須在 1 秒內於純 CPU 環境完成。
"""

import numpy as np
import numpy.testing as npt
import pytest

from src.core.contracts import RGBDFrame, CameraIntrinsics
from src.core.geometry import GeometryProcessor
from src.core.policies import SobelEdgeDetector


# ---------------------------------------------------------------------------
# 資料契約驗證
# ---------------------------------------------------------------------------

class TestRGBDFrameContract:

    def test_mismatched_dimensions_raise_value_error(self):
        """FR-001：色彩圖與深度圖維度不一致時必須拋出 ValueError。"""
        color = np.zeros((100, 100, 3), dtype=np.uint8)
        depth = np.ones((50, 50), dtype=np.float32)   # 故意尺寸不同
        with pytest.raises(ValueError, match="維度一致性違反"):
            RGBDFrame(color=color, depth=depth)

    def test_matching_dimensions_succeed(self, small_rgbd_frame):
        """FR-001：維度一致時應正常建構，無異常。"""
        assert small_rgbd_frame.color.shape[:2] == small_rgbd_frame.depth.shape[:2]

    def test_mask_is_optional(self, small_rgbd_frame):
        """mask 欄位預設為 None，符合資料契約。"""
        assert small_rgbd_frame.mask is None


# ---------------------------------------------------------------------------
# 反投影（Unprojection）測試
# ---------------------------------------------------------------------------

class TestUnprojection:

    def test_output_shape_is_n_by_3(self, small_rgbd_frame, default_intrinsics):
        """FR-002：10×10 深度圖反投影後，點雲形狀必須為 (100, 3)。"""
        policy = SobelEdgeDetector()
        geo    = GeometryProcessor(default_intrinsics, policy)
        points = geo.unproject_to_points(small_rgbd_frame.depth)
        assert points.shape == (100, 3), f"預期 (100, 3)，實際 {points.shape}"

    def test_z_values_match_depth(self, small_rgbd_frame, default_intrinsics):
        """FR-002：全深度 = 1.0 的深度圖，反投影後所有點的 Z 值應全為 1.0。"""
        policy = SobelEdgeDetector()
        geo    = GeometryProcessor(default_intrinsics, policy)
        points = geo.unproject_to_points(small_rgbd_frame.depth)
        npt.assert_array_almost_equal(
            points[:, 2], np.ones(100, dtype=np.float64),
            decimal=6,
            err_msg="反投影後 Z 軸數值不符合原始深度圖數值"
        )

    def test_identity_intrinsics_x_equals_u_times_z(self, identity_intrinsics):
        """
        使用單位內參 (fx=fy=1, cx=cy=0) 驗算：
          X = U * Z，Y = V * Z（驗證公式實作正確）
        """
        depth = np.ones((4, 4), dtype=np.float32) * 2.0   # Z = 2.0
        color = np.zeros((4, 4, 3), dtype=np.uint8)
        frame = RGBDFrame(color=color, depth=depth)

        policy = SobelEdgeDetector()
        geo    = GeometryProcessor(identity_intrinsics, policy)
        points = geo.unproject_to_points(frame.depth)

        # 重建期望值：X[r,c] = c * 2.0, Y[r,c] = r * 2.0
        expected_x = np.tile(np.arange(4, dtype=np.float64) * 2.0, 4)  # 每行 4 個，共 4 行
        npt.assert_array_almost_equal(points[:, 0], expected_x, decimal=6)


# ---------------------------------------------------------------------------
# 拓樸建立與斷邊（Tearing）測試
# ---------------------------------------------------------------------------

class TestBuildTopology:

    def _make_geo(self, intrinsics: CameraIntrinsics) -> GeometryProcessor:
        return GeometryProcessor(intrinsics, SobelEdgeDetector(percentile=95.0))

    def test_full_mesh_face_count(self, small_rgbd_frame, default_intrinsics):
        """
        FR-003：10×10 點雲，無任何斷邊遮罩時，應產生完整的 (9×9×2) = 162 個三角面。
        使用全零 mask（強制無斷邊）來隔離拓樸邏輯。
        """
        small_rgbd_frame.mask = np.zeros((10, 10), dtype=np.bool_)  # 強制無斷崖
        geo    = self._make_geo(default_intrinsics)
        points = geo.unproject_to_points(small_rgbd_frame.depth)
        mesh   = geo.build_topology(points, small_rgbd_frame)

        face_count = np.asarray(mesh.triangles).shape[0]
        assert face_count == 162, (
            f"預期完整網格 162 面，實際 {face_count} 面。"
            f"請確認 build_topology 的向量化索引邏輯正確。"
        )

    def test_tearing_reduces_face_count(self, cliff_rgbd_frame, default_intrinsics):
        """
        FR-003：斷崖深度圖（左半 1.0，右半 100.0）應觸發斷邊，導致面數 < 162。

        斷崖發生在第 5 行（索引 4↔5），9 個方格（9 個正方形 × 2 三角形 = 18 面）
        應被剔除，預期剩餘 162 - 18 = 144 面。
        """
        geo    = self._make_geo(default_intrinsics)
        points = geo.unproject_to_points(cliff_rgbd_frame.depth)
        mesh   = geo.build_topology(points, cliff_rgbd_frame)

        face_count = np.asarray(mesh.triangles).shape[0]
        assert face_count < 162, (
            f"斷崖幀應使面數 < 162，但得到 {face_count}。"
            f"請確認 SobelEdgeDetector 與 build_topology 的斷邊遮罩套用邏輯。"
        )

    def test_tearing_expected_face_count(self, cliff_rgbd_frame, default_intrinsics):
        """精確驗證斷崖後面數為 144（162 - 18）。"""
        geo    = self._make_geo(default_intrinsics)
        points = geo.unproject_to_points(cliff_rgbd_frame.depth)
        mesh   = geo.build_topology(points, cliff_rgbd_frame)

        face_count = np.asarray(mesh.triangles).shape[0]
        assert face_count == 144, (
            f"預期 144 面（162 - 18），實際 {face_count} 面。"
        )

    def test_mesh_has_vertex_colors(self, small_rgbd_frame, default_intrinsics):
        """網格必須包含頂點顏色（用於 Open3D 渲染紋理）。"""
        small_rgbd_frame.mask = np.zeros((10, 10), dtype=np.bool_)
        geo    = self._make_geo(default_intrinsics)
        points = geo.unproject_to_points(small_rgbd_frame.depth)
        mesh   = geo.build_topology(points, small_rgbd_frame)

        assert mesh.has_vertex_colors(), "網格缺少頂點顏色資料，渲染將無紋理。"

    def test_all_true_mask_produces_minimal_faces(self, small_rgbd_frame, default_intrinsics):
        """遮罩全為 True（所有像素皆為斷崖）時，應產生 0 個三角面。"""
        small_rgbd_frame.mask = np.ones((10, 10), dtype=np.bool_)
        geo    = self._make_geo(default_intrinsics)
        points = geo.unproject_to_points(small_rgbd_frame.depth)
        mesh   = geo.build_topology(points, small_rgbd_frame)

        face_count = np.asarray(mesh.triangles).shape[0]
        assert face_count == 0, f"全遮罩應產生 0 面，實際 {face_count} 面。"


# ---------------------------------------------------------------------------
# SobelEdgeDetector 策略測試
# ---------------------------------------------------------------------------

class TestSobelEdgeDetector:

    def test_output_shape_matches_input(self, small_rgbd_frame):
        """策略輸出遮罩的形狀必須與輸入深度圖一致。"""
        detector = SobelEdgeDetector(percentile=95.0)
        mask = detector.compute_mask(small_rgbd_frame.depth)
        assert mask.shape == small_rgbd_frame.depth.shape

    def test_output_is_boolean(self, small_rgbd_frame):
        """策略輸出必須為布林型別 (np.bool_)。"""
        detector = SobelEdgeDetector(percentile=95.0)
        mask = detector.compute_mask(small_rgbd_frame.depth)
        assert mask.dtype == np.bool_, f"預期 np.bool_，實際 {mask.dtype}"

    def test_cliff_frame_detects_edge(self, cliff_rgbd_frame):
        """斷崖幀應在深度突變位置偵測到斷崖像素（mask 中有 True 值）。"""
        detector = SobelEdgeDetector(percentile=50.0)   # 較低門檻，確保能偵測
        mask = detector.compute_mask(cliff_rgbd_frame.depth)
        assert mask.any(), "斷崖幀應偵測到至少一個斷崖像素，但 mask 全為 False。"

    def test_flat_depth_produces_few_edges(self, small_rgbd_frame):
        """全平深度圖（全為 1.0），使用 percentile=99.9 時，斷崖像素應極少或為零。"""
        detector = SobelEdgeDetector(percentile=99.9)
        mask = detector.compute_mask(small_rgbd_frame.depth)
        # 梯度為 0 時，np.percentile(zeros, 99.9) = 0，所以 mask 全 False
        assert not mask.any(), "全平深度圖不應有斷崖像素。"

    def test_invalid_percentile_raises(self):
        """超出 [0, 100] 範圍的 percentile 應拋出 ValueError。"""
        with pytest.raises(ValueError):
            SobelEdgeDetector(percentile=101.0)
        with pytest.raises(ValueError):
            SobelEdgeDetector(percentile=-1.0)
