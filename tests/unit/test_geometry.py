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
from src.core.policies import (
    EdgeDetectionPolicy,
    SobelEdgeDetector,
    DepthDiscontinuityPolicy,
)


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
        """
        FR-002：全深度 = 1.0 的深度圖，反投影後所有點的 Z 值應全為 -1.0。
        （Bug D 座標修正：glTF 右手系 +Z 朝觀者，故 Z_out = -Z_cam。）
        """
        policy = SobelEdgeDetector()
        geo    = GeometryProcessor(default_intrinsics, policy)
        points = geo.unproject_to_points(small_rgbd_frame.depth)
        npt.assert_array_almost_equal(
            points[:, 2], -np.ones(100, dtype=np.float64),
            decimal=6,
            err_msg="反投影後 Z 軸數值不符合原始深度圖數值（應為 -Z_cam）"
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

        # 重建期望值：X[r,c] = c * 2.0（X 不受座標翻轉影響）
        expected_x = np.tile(np.arange(4, dtype=np.float64) * 2.0, 4)  # 每行 4 個，共 4 行
        npt.assert_array_almost_equal(points[:, 0], expected_x, decimal=6)

    def test_y_axis_flipped_for_gltf(self, identity_intrinsics):
        """
        Bug D：影像列 V 向下增長，glTF +Y 朝上，故輸出 Y = -V*Z。
        驗證 Y[r,c] = -r * Z（上方列 r 小 → Y 較大；下方列 r 大 → Y 較負）。
        """
        depth = np.ones((4, 4), dtype=np.float32) * 2.0   # Z_cam = 2.0
        color = np.zeros((4, 4, 3), dtype=np.uint8)
        frame = RGBDFrame(color=color, depth=depth)

        geo    = GeometryProcessor(identity_intrinsics, SobelEdgeDetector())
        points = geo.unproject_to_points(frame.depth)

        # Y[r,c] = -(r) * 2.0，row-major 展平：每行 4 個相同 r
        expected_y = np.repeat(-np.arange(4, dtype=np.float64) * 2.0, 4)
        npt.assert_array_almost_equal(points[:, 1], expected_y, decimal=6)

    def test_near_object_is_closer_to_viewer(self):
        """
        座標系語意：近物（小 metric 深度）反投影後 Z 應比遠物更靠近觀者（+Z 較大）。
        這保證 disparity 統一成 metric 後，深度方向不再反轉。
        """
        intr = CameraIntrinsics(
            fx=1.0, fy=1.0, cx=0.0, cy=0.0, width=2, height=1,
            depth_near=1.0, depth_far=5.0,
        )
        geo = GeometryProcessor(intr, SobelEdgeDetector())
        # d=0.0 為近（Z_cam=1），d=1.0 為遠（Z_cam=5）
        z = geo.unproject_to_points(np.array([[0.0, 1.0]], dtype=np.float32))[:, 2]
        # 輸出 Z = -Z_cam → 近物 -1.0 > 遠物 -5.0
        assert z[0] > z[1], "近物的輸出 Z 應比遠物更靠近觀者（+Z 較大）"

    def test_depth_scale_maps_normalized_depth_to_metric_z(self):
        """
        C-3：正規化深度 d∈[0,1] 應線性映射到 [depth_near, depth_far]。
          d=0 → Z=near，d=1 → Z=far，d=0.5 → Z=(near+far)/2。
        """
        intr = CameraIntrinsics(
            fx=1.0, fy=1.0, cx=0.0, cy=0.0, width=3, height=1,
            depth_near=1.0, depth_far=5.0,
        )
        geo = GeometryProcessor(intr, SobelEdgeDetector())

        depth = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)  # 1×3
        points = geo.unproject_to_points(depth)

        # Z_cam = near + d*(far-near) = 1, 3, 5；輸出取負（glTF +Z 朝觀者）
        npt.assert_array_almost_equal(points[:, 2], [-1.0, -3.0, -5.0], decimal=6)

    def test_depth_scale_preserves_relative_ordering_across_images(self):
        """
        C-3：兩張 max 不同的正規化深度圖，相同 d 值應反投影到相同 Z，
        證明深度尺度不再被各圖的 max 任意縮放（解決原始 max 正規化的失真）。
        """
        intr = CameraIntrinsics(
            fx=1.0, fy=1.0, cx=0.0, cy=0.0, width=2, height=1,
            depth_near=2.0, depth_far=10.0,
        )
        geo = GeometryProcessor(intr, SobelEdgeDetector())

        z1 = geo.unproject_to_points(np.array([[0.25, 0.75]], dtype=np.float32))[:, 2]
        z2 = geo.unproject_to_points(np.array([[0.25, 0.75]], dtype=np.float32))[:, 2]
        npt.assert_array_almost_equal(z1, z2, decimal=6)
        # Z_cam = near + d*(far-near) = 4, 8；輸出取負（glTF +Z 朝觀者）
        npt.assert_array_almost_equal(z1, [-4.0, -8.0], decimal=6)


# ---------------------------------------------------------------------------
# build_topology 契約防護（A-2）
# ---------------------------------------------------------------------------

class TestBuildTopologyContract:

    def test_wrong_points_shape_raises(self, small_rgbd_frame, default_intrinsics):
        """A-2：points 形狀與 H*W 不符時應拋出 ValueError（契約防護）。"""
        geo = GeometryProcessor(default_intrinsics, SobelEdgeDetector())
        bad_points = np.zeros((50, 3), dtype=np.float64)  # 應為 (100, 3)
        small_rgbd_frame.mask = np.zeros((10, 10), dtype=np.bool_)
        with pytest.raises(ValueError, match="points 形狀不符"):
            geo.build_topology(bad_points, small_rgbd_frame)


# ---------------------------------------------------------------------------
# 拓樸建立與斷邊（Tearing）測試
# ---------------------------------------------------------------------------

class _ConstMaskPolicy(EdgeDetectionPolicy):
    """測試輔助：回傳固定遮罩的策略，隔離 build_topology 的拓樸過濾邏輯。

    Bug C 修正後 build_topology 一律呼叫 edge_policy.compute_mask(frame.depth)
    重算斷崖遮罩，不再沿用 frame.mask。為了在單元測試中精確控制遮罩，改以
    注入此固定遮罩策略取代「直接設 frame.mask」的舊作法。
    """

    def __init__(self, mask: np.ndarray):
        self._mask = mask.astype(np.bool_)

    def compute_mask(self, depth_matrix: np.ndarray) -> np.ndarray:
        return self._mask


class TestBuildTopology:

    def _make_geo(self, intrinsics: CameraIntrinsics, mask: np.ndarray) -> GeometryProcessor:
        # build_topology 重算斷崖遮罩，故以固定遮罩策略注入精確控制（Bug C 修正）。
        return GeometryProcessor(intrinsics, _ConstMaskPolicy(mask))

    def test_full_mesh_face_count(self, small_rgbd_frame, default_intrinsics):
        """
        FR-003：10×10 點雲，無任何斷邊遮罩時，應產生完整的 (9×9×2) = 162 個三角面。
        注入全零遮罩策略（強制無斷邊）來隔離拓樸邏輯。
        """
        geo    = self._make_geo(default_intrinsics, np.zeros((10, 10), dtype=np.bool_))
        points = geo.unproject_to_points(small_rgbd_frame.depth)
        mesh   = geo.build_topology(points, small_rgbd_frame)

        face_count = mesh.face_count
        assert face_count == 162, (
            f"預期完整網格 162 面，實際 {face_count} 面。"
            f"請確認 build_topology 的向量化索引邏輯正確。"
        )

    def test_tearing_reduces_face_count(self, cliff_rgbd_frame, default_intrinsics):
        """
        FR-003：斷崖遮罩（標記 col=4 為斷邊）應觸發斷邊，導致面數 < 162。

        注入固定遮罩策略而非真實偵測器，隔離 build_topology 的拓樸過濾邏輯
        （斷崖偵測器行為由 TestSobelEdgeDetector / TestDepthDiscontinuityPolicy 獨立驗證）。
        """
        mask = np.zeros((10, 10), dtype=np.bool_)
        mask[:, 4] = True   # 斷崖邊界列

        geo    = self._make_geo(default_intrinsics, mask)
        points = geo.unproject_to_points(cliff_rgbd_frame.depth)
        mesh   = geo.build_topology(points, cliff_rgbd_frame)

        face_count = mesh.face_count
        assert face_count < 162, (
            f"斷崖幀應使面數 < 162，但得到 {face_count}。"
            f"請確認 build_topology 的斷邊遮罩套用邏輯。"
        )

    def test_tearing_expected_face_count(self, cliff_rgbd_frame, default_intrinsics):
        """
        精確驗證斷崖後面數。

        標記 col=4（斷崖邊界列）：每個像素屬於左右各 9 個方格，
        共 18 個無效方格 → 剔除 36 面 → 162 - 36 = 126 面。
        """
        mask = np.zeros((10, 10), dtype=np.bool_)
        mask[:, 4] = True

        geo    = self._make_geo(default_intrinsics, mask)
        points = geo.unproject_to_points(cliff_rgbd_frame.depth)
        mesh   = geo.build_topology(points, cliff_rgbd_frame)

        face_count = mesh.face_count
        assert face_count == 126, (
            f"預期 126 面（162 - 36），實際 {face_count} 面。"
        )

    def test_mesh_has_vertex_colors_and_normals(self, small_rgbd_frame, default_intrinsics):
        """MeshData 必須含頂點顏色與法線（前端 WebGL 渲染所需）。"""
        geo    = self._make_geo(default_intrinsics, np.zeros((10, 10), dtype=np.bool_))
        points = geo.unproject_to_points(small_rgbd_frame.depth)
        mesh   = geo.build_topology(points, small_rgbd_frame)

        assert mesh.colors.shape == mesh.vertices.shape, "頂點色數應與頂點數一致。"
        assert mesh.colors.min() >= 0.0 and mesh.colors.max() <= 1.0, "顏色應正規化至 [0,1]。"
        assert mesh.normals is not None and mesh.normals.shape == mesh.vertices.shape
        lengths = np.linalg.norm(mesh.normals, axis=1)
        assert np.allclose(lengths[lengths > 0], 1.0, atol=1e-5)

    def test_all_true_mask_produces_minimal_faces(self, small_rgbd_frame, default_intrinsics):
        """遮罩全為 True（所有像素皆為斷崖）時，應產生 0 個三角面。"""
        geo    = self._make_geo(default_intrinsics, np.ones((10, 10), dtype=np.bool_))
        points = geo.unproject_to_points(small_rgbd_frame.depth)
        mesh   = geo.build_topology(points, small_rgbd_frame)

        face_count = mesh.face_count
        assert face_count == 0, f"全遮罩應產生 0 面，實際 {face_count} 面。"


# ---------------------------------------------------------------------------
# 3D 邊長剔除（放射狀拉伸面的最終防線）
# ---------------------------------------------------------------------------

class TestEdgeLengthCulling:
    """
    驗證 max_edge_ratio 剔除 3D 邊長過長的三角形（放射線根治），
    且預設關閉（None）時行為與原本完全一致。
    """

    @staticmethod
    def _geo(intrinsics, mask, max_edge_ratio):
        # 注入全零遮罩（不靠斷崖切割），純粹測邊長剔除這一道。
        return GeometryProcessor(
            intrinsics, _ConstMaskPolicy(mask), max_edge_ratio=max_edge_ratio
        )

    def test_default_off_keeps_all_faces(self, cliff_rgbd_frame, default_intrinsics):
        """預設 max_edge_ratio=None：即使有巨大深度落差也不剔除（與原行為一致）。"""
        mask = np.zeros((10, 10), dtype=np.bool_)   # 無斷崖遮罩
        geo = self._geo(default_intrinsics, mask, None)
        points = geo.unproject_to_points(cliff_rgbd_frame.depth)
        mesh = geo.build_topology(points, cliff_rgbd_frame)
        assert mesh.face_count == 162, "預設關閉時應保留完整 162 面。"

    def test_culling_removes_stretched_faces(self, cliff_rgbd_frame, default_intrinsics):
        """
        開啟剔除後，橫跨 depth 1.0↔100.0 斷崖的拉伸三角形（3D 邊長遠大於
        中位）應被剔除，面數 < 162。
        """
        mask = np.zeros((10, 10), dtype=np.bool_)   # 不靠斷崖遮罩，純靠邊長
        geo = self._geo(default_intrinsics, mask, max_edge_ratio=5.0)
        points = geo.unproject_to_points(cliff_rgbd_frame.depth)
        mesh = geo.build_topology(points, cliff_rgbd_frame)
        assert mesh.face_count < 162, (
            f"開啟邊長剔除後拉伸面應被剔除，但面數仍為 {mesh.face_count}。"
        )

    def test_culling_keeps_uniform_mesh_intact(self, small_rgbd_frame, default_intrinsics):
        """深度均勻（無拉伸）時，即使開啟剔除也不應誤刪任何面。"""
        mask = np.zeros((10, 10), dtype=np.bool_)
        geo = self._geo(default_intrinsics, mask, max_edge_ratio=5.0)
        points = geo.unproject_to_points(small_rgbd_frame.depth)
        mesh = geo.build_topology(points, small_rgbd_frame)
        assert mesh.face_count == 162, (
            f"均勻深度不應觸發邊長剔除，但面數為 {mesh.face_count}。"
        )


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


# ---------------------------------------------------------------------------
# DepthDiscontinuityPolicy 策略測試（絕對深度差為主、Sobel 為輔）
# ---------------------------------------------------------------------------

class TestDepthDiscontinuityPolicy:

    def test_flat_depth_no_edges(self, small_rgbd_frame):
        """全平深度圖：深度範圍為 0，應回傳全 False（無斷崖）。"""
        policy = DepthDiscontinuityPolicy()
        mask = policy.compute_mask(small_rgbd_frame.depth)
        assert mask.dtype == np.bool_
        assert not mask.any()

    def test_cliff_detected_at_boundary(self, cliff_rgbd_frame):
        """斷崖幀（左 1.0 / 右 100.0）應在 col 4↔5 邊界偵測到斷崖。"""
        policy = DepthDiscontinuityPolicy()
        mask = policy.compute_mask(cliff_rgbd_frame.depth)
        assert mask.any(), "斷崖幀應偵測到斷崖像素。"
        # 斷崖兩側（col 4、5）應被標記
        assert mask[:, 4].any() or mask[:, 5].any()

    def test_smooth_ramp_not_torn(self):
        """
        平滑深度斜坡（模擬 ML depth）：絕對深度差遠小於門檻，不應被切成放射線。
        這正是純 Sobel 百分位失效、本策略要解決的核心情境。
        """
        # 0→1 緩坡橫跨 100 px，相鄰差約 0.01，遠小於 4% 門檻
        ramp = np.tile(np.linspace(0, 1, 100, dtype=np.float32), (10, 1))
        policy = DepthDiscontinuityPolicy(abs_diff_ratio=0.04)
        mask = policy.compute_mask(ramp)
        assert not mask.any(), "平滑斜坡不應被判為斷崖。"

    def test_sobel_refinement_toggle(self, cliff_rgbd_frame):
        """use_sobel_refinement=False 時退化為純絕對深度差版本（quick bisect 用）。"""
        no_sobel = DepthDiscontinuityPolicy(use_sobel_refinement=False)
        mask = no_sobel.compute_mask(cliff_rgbd_frame.depth)
        assert mask.any()
        # 純絕對差版本的候選數應 ≥ 含 Sobel 細化版本（細化只會收斂、不會增加）
        with_sobel = DepthDiscontinuityPolicy(use_sobel_refinement=True)
        assert mask.sum() >= with_sobel.compute_mask(cliff_rgbd_frame.depth).sum()

    def test_invalid_params_raise(self):
        with pytest.raises(ValueError):
            DepthDiscontinuityPolicy(abs_diff_ratio=0.0)
        with pytest.raises(ValueError):
            DepthDiscontinuityPolicy(abs_diff_ratio=1.5)
        with pytest.raises(ValueError):
            DepthDiscontinuityPolicy(sobel_percentile=101.0)
