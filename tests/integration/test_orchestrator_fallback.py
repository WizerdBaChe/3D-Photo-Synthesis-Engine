"""
階層二整合測試：Orchestrator OOM 降級機制 + MeshData 輸出
(test_orchestrator_fallback.py)
=========================================================
驗證目標：
  - VRAMExhaustedError 時自動降級至 TeleaInpainter，不 Crash
  - 降級後的修補結果確實流入幾何階段（非原始幀）
  - 非 VRAMExhaustedError 不被靜默吞掉，向上拋出（含含 'out of memory' 字串者）
  - 主修補器成功時不觸發降級
  - process() 回傳合法 MeshData（vertices/faces/colors）

設計原則：
  - 以 unittest.mock 控制例外，不需 GPU。
  - Web 架構：Orchestrator.process() 回傳 MeshData，不涉及渲染控制器 / .ply。
"""

import pytest
from unittest.mock import MagicMock

import numpy as np

from src.core.contracts import RGBDFrame, CameraIntrinsics, MeshData
from src.core.geometry import GeometryProcessor
from src.core.inpainting import (
    TeleaInpainter, VRAMExhaustedError,
)
from src.core.policies import SobelEdgeDetector
from src.app.orchestrator import Orchestrator


# ---------------------------------------------------------------------------
# 共用 Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def geo_processor():
    intrinsics = CameraIntrinsics(fx=50.0, fy=50.0, cx=5.0, cy=5.0, width=10, height=10)
    policy     = SobelEdgeDetector(percentile=95.0)
    return GeometryProcessor(intrinsics, policy)


@pytest.fixture
def telea_inpainter():
    return TeleaInpainter(inpaint_radius=3)


@pytest.fixture
def simple_frame():
    color = np.zeros((10, 10, 3), dtype=np.uint8)
    depth = np.ones((10, 10), dtype=np.float32) * 0.5
    return RGBDFrame(color=color, depth=depth)


# ---------------------------------------------------------------------------
# OOM 降級核心驗證
# ---------------------------------------------------------------------------

class TestOOMFallback:

    def test_oom_triggers_fallback_to_telea(self, simple_frame, geo_processor):
        """primary 拋 VRAMExhaustedError 時，應呼叫 fallback.fill()。"""
        mock_primary = MagicMock()
        mock_primary.fill.side_effect = VRAMExhaustedError("CUDA out of memory")

        repaired = RGBDFrame(
            color=np.zeros((10, 10, 3), dtype=np.uint8),
            depth=np.ones((10, 10), dtype=np.float32),
            mask=None,
        )
        mock_fallback = MagicMock()
        mock_fallback.fill.return_value = repaired

        orch = Orchestrator(geo_processor, mock_primary, mock_fallback)
        mesh = orch.process(simple_frame)

        mock_primary.fill.assert_called_once()
        mock_fallback.fill.assert_called_once()
        assert isinstance(mesh, MeshData)

    def test_oom_fallback_result_passed_to_geometry(self, simple_frame, geo_processor):
        """降級後 fallback 的 depth 應流入幾何階段（非原始幀）。"""
        mock_primary = MagicMock()
        mock_primary.fill.side_effect = VRAMExhaustedError("CUDA out of memory")

        repaired_depth = np.full((10, 10), 0.8, dtype=np.float32)
        repaired_frame = RGBDFrame(
            color=np.zeros((10, 10, 3), dtype=np.uint8),
            depth=repaired_depth, mask=None,
        )
        mock_fallback = MagicMock()
        mock_fallback.fill.return_value = repaired_frame

        received = []
        original_unproject = geo_processor.unproject_to_points

        def spy(depth_matrix):
            received.append(depth_matrix.copy())
            return original_unproject(depth_matrix)

        geo_processor.unproject_to_points = spy

        orch = Orchestrator(geo_processor, mock_primary, mock_fallback)
        orch.process(simple_frame)

        assert len(received) == 1
        np.testing.assert_array_almost_equal(received[0], repaired_depth)

    def test_successful_primary_does_not_invoke_fallback(self, simple_frame, geo_processor):
        repaired = RGBDFrame(
            color=np.zeros((10, 10, 3), dtype=np.uint8),
            depth=np.ones((10, 10), dtype=np.float32), mask=None,
        )
        mock_primary  = MagicMock()
        mock_primary.fill.return_value = repaired
        mock_fallback = MagicMock()

        orch = Orchestrator(geo_processor, mock_primary, mock_fallback)
        orch.process(simple_frame)

        mock_primary.fill.assert_called_once()
        mock_fallback.fill.assert_not_called()


# ---------------------------------------------------------------------------
# 降級判定與字串解耦（A-1 / C-4）
# ---------------------------------------------------------------------------

class TestFallbackDecoupledFromMessage:

    def test_vram_exhausted_error_triggers_fallback(self, simple_frame, geo_processor):
        """VRAMExhaustedError 觸發降級，與訊息文字無關。"""
        repaired = RGBDFrame(
            color=np.zeros((10, 10, 3), dtype=np.uint8),
            depth=np.ones((10, 10), dtype=np.float32), mask=None,
        )
        mock_primary  = MagicMock()
        mock_primary.fill.side_effect = VRAMExhaustedError("顯存配置失敗")  # 無 'out of memory'
        mock_fallback = MagicMock()
        mock_fallback.fill.return_value = repaired

        orch = Orchestrator(geo_processor, mock_primary, mock_fallback)
        orch.process(simple_frame)

        mock_fallback.fill.assert_called_once()

    def test_plain_runtime_error_with_oom_text_still_propagates(self, simple_frame, geo_processor):
        """含 'out of memory' 字串的 RuntimeError 若非 VRAMExhaustedError，應向上拋。"""
        mock_primary  = MagicMock()
        mock_primary.fill.side_effect = RuntimeError("CUDA out of memory")
        mock_fallback = MagicMock()

        orch = Orchestrator(geo_processor, mock_primary, mock_fallback)
        with pytest.raises(RuntimeError, match="out of memory"):
            orch.process(simple_frame)

        mock_fallback.fill.assert_not_called()


# ---------------------------------------------------------------------------
# 管線輸出完整性
# ---------------------------------------------------------------------------

class TestPipelineOutput:

    def test_process_returns_valid_meshdata(self, simple_frame, geo_processor, telea_inpainter):
        orch = Orchestrator(geo_processor, telea_inpainter, telea_inpainter)
        mesh = orch.process(simple_frame)

        assert isinstance(mesh, MeshData)
        assert mesh.vertex_count == 100          # 10×10
        assert mesh.faces.shape[1] == 3
        assert mesh.colors.shape == mesh.vertices.shape
        assert mesh.normals is not None

    def test_edge_mask_set_before_inpainting(self, simple_frame, geo_processor):
        """進入修補器前 frame.mask 必須已設定（邊緣偵測先於修補）。"""
        received = []

        class SpyInpainter(TeleaInpainter):
            def fill(self, frame: RGBDFrame) -> RGBDFrame:
                received.append(frame)
                return super().fill(frame)

        spy = SpyInpainter()
        orch = Orchestrator(geo_processor, spy, spy)
        orch.process(simple_frame)

        assert len(received) == 1
        assert received[0].mask is not None
        assert received[0].mask.shape == simple_frame.depth.shape
