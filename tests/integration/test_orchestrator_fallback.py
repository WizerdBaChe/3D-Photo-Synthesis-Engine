"""
階層二整合測試：Orchestrator OOM 降級機制
(test_orchestrator_fallback.py)
=========================================
驗證目標（02_verification_testing.md §3.2）：
  - AI 記憶體爆滿（OOM）時，Orchestrator 不 Crash，自動降級至 TeleaInpainter
  - 降級後仍回傳有效的修補結果（mask 清空）
  - 非 OOM RuntimeError 不應被靜默吞掉，應向上拋出
  - 主修補器成功時，不觸發降級備案
  - LAZY 模式不保留顯存（torch.cuda.memory_allocated 前後一致）

設計原則（02_verification_testing.md §3.3）：
  - 以 unittest.mock 控制例外，不需實際 GPU 環境
  - 跨進程測試加入 pytest.mark.timeout 避免死鎖
"""

import pytest
from unittest.mock import MagicMock, patch, call

from src.core.contracts import RGBDFrame, CameraIntrinsics
from src.core.geometry import GeometryProcessor
from src.core.inpainting import TeleaInpainter, LaMaInpainter, VramStrategy
from src.core.policies import SobelEdgeDetector
from src.app.orchestrator import Orchestrator

import numpy as np


# ---------------------------------------------------------------------------
# 共用 Fixture（此模組局部，補充 conftest 未定義的複雜情境）
# ---------------------------------------------------------------------------

@pytest.fixture
def geo_processor():
    """真實的 GeometryProcessor（使用小尺寸合成資料，快速執行）。"""
    intrinsics = CameraIntrinsics(fx=50.0, fy=50.0, cx=5.0, cy=5.0, width=10, height=10)
    policy     = SobelEdgeDetector(percentile=95.0)
    return GeometryProcessor(intrinsics, policy)


@pytest.fixture
def telea_inpainter():
    return TeleaInpainter(inpaint_radius=3)


@pytest.fixture
def mock_render_controller():
    ctrl = MagicMock()
    ctrl.is_alive.return_value = True
    return ctrl


@pytest.fixture
def simple_frame():
    """10×10 的簡單合成幀，作為管線輸入。"""
    color = np.zeros((10, 10, 3), dtype=np.uint8)
    depth = np.ones((10, 10), dtype=np.float32) * 0.5
    return RGBDFrame(color=color, depth=depth)


# ---------------------------------------------------------------------------
# OOM 降級核心驗證
# ---------------------------------------------------------------------------

class TestOOMFallback:

    def test_oom_triggers_fallback_to_telea(
        self, simple_frame, geo_processor, telea_inpainter, mock_render_controller
    ):
        """
        核心驗證：primary_inpainter.fill() 拋出 OOM RuntimeError 時，
        Orchestrator 必須捕捉例外並呼叫 fallback_inpainter.fill()。
        """
        mock_primary = MagicMock()
        mock_primary.fill.side_effect = RuntimeError("CUDA out of memory")

        mock_fallback = MagicMock()
        # 讓 fallback 回傳一個有效的修補幀，使管線可繼續執行
        repaired = RGBDFrame(
            color=np.zeros((10, 10, 3), dtype=np.uint8),
            depth=np.ones((10, 10), dtype=np.float32),
            mask=None
        )
        mock_fallback.fill.return_value = repaired

        orchestrator = Orchestrator(
            geo_processor=geo_processor,
            primary_inpainter=mock_primary,
            fallback_inpainter=mock_fallback,
            render_controller=mock_render_controller,
        )

        with patch.object(Orchestrator, '_save_mesh_to_tempfile', return_value='/tmp/mesh.ply'):
            orchestrator.process_and_render(simple_frame)

        # 確認有嘗試主修補器
        mock_primary.fill.assert_called_once()
        # 確認觸發降級備案
        mock_fallback.fill.assert_called_once()

    def test_oom_fallback_result_passed_to_geometry(
        self, simple_frame, geo_processor, telea_inpainter, mock_render_controller
    ):
        """
        OOM 降級後，fallback 的回傳結果必須繼續流入幾何處理階段，
        而不是使用未修補的原始幀。
        """
        mock_primary = MagicMock()
        mock_primary.fill.side_effect = RuntimeError("CUDA out of memory")

        repaired_depth = np.full((10, 10), 0.8, dtype=np.float32)  # 特殊深度值用於辨識
        repaired_frame = RGBDFrame(
            color=np.zeros((10, 10, 3), dtype=np.uint8),
            depth=repaired_depth,
            mask=None
        )
        mock_fallback = MagicMock()
        mock_fallback.fill.return_value = repaired_frame

        received_frames = []

        original_unproject = geo_processor.unproject_to_points

        def spy_unproject(depth_matrix):
            received_frames.append(depth_matrix.copy())
            return original_unproject(depth_matrix)

        geo_processor.unproject_to_points = spy_unproject

        orchestrator = Orchestrator(
            geo_processor=geo_processor,
            primary_inpainter=mock_primary,
            fallback_inpainter=mock_fallback,
            render_controller=mock_render_controller,
        )

        with patch.object(Orchestrator, '_save_mesh_to_tempfile', return_value='/tmp/mesh.ply'):
            orchestrator.process_and_render(simple_frame)

        # 傳入幾何引擎的 depth 應來自 fallback 的修補結果
        assert len(received_frames) == 1
        np.testing.assert_array_almost_equal(
            received_frames[0], repaired_depth,
            err_msg="幾何引擎應使用 fallback 修補後的 depth，而非原始 depth。"
        )

    def test_non_oom_runtime_error_propagates(
        self, simple_frame, geo_processor, telea_inpainter, mock_render_controller
    ):
        """
        非 OOM 的 RuntimeError 不應被 Orchestrator 靜默吞掉，
        必須向上拋出讓呼叫者（SynthesisWorker）處理。
        """
        mock_primary = MagicMock()
        mock_primary.fill.side_effect = RuntimeError("模型權重檔案損毀")

        mock_fallback = MagicMock()

        orchestrator = Orchestrator(
            geo_processor=geo_processor,
            primary_inpainter=mock_primary,
            fallback_inpainter=mock_fallback,
            render_controller=mock_render_controller,
        )

        with pytest.raises(RuntimeError, match="模型權重檔案損毀"):
            orchestrator.process_and_render(simple_frame)

        # 非 OOM 時不應觸發降級
        mock_fallback.fill.assert_not_called()

    def test_successful_primary_does_not_invoke_fallback(
        self, simple_frame, geo_processor, telea_inpainter, mock_render_controller
    ):
        """主修補器成功時，fallback 不應被呼叫。"""
        repaired = RGBDFrame(
            color=np.zeros((10, 10, 3), dtype=np.uint8),
            depth=np.ones((10, 10), dtype=np.float32),
            mask=None
        )
        mock_primary  = MagicMock()
        mock_primary.fill.return_value = repaired
        mock_fallback = MagicMock()

        orchestrator = Orchestrator(
            geo_processor=geo_processor,
            primary_inpainter=mock_primary,
            fallback_inpainter=mock_fallback,
            render_controller=mock_render_controller,
        )

        with patch.object(Orchestrator, '_save_mesh_to_tempfile', return_value='/tmp/mesh.ply'):
            orchestrator.process_and_render(simple_frame)

        mock_primary.fill.assert_called_once()
        mock_fallback.fill.assert_not_called()


# ---------------------------------------------------------------------------
# OOM 字串比對彈性測試
# ---------------------------------------------------------------------------

class TestOOMMessageMatching:
    """確認 OOM 字串比對對大小寫不敏感（'out of memory' 的各種變體）。"""

    @pytest.mark.parametrize("oom_msg", [
        "CUDA out of memory",
        "cuda out of memory",
        "RuntimeError: CUDA out of memory. Tried to allocate 2.00 GiB",
        "out of memory (device)",
    ])
    def test_various_oom_messages_trigger_fallback(
        self, oom_msg, simple_frame, geo_processor, telea_inpainter, mock_render_controller
    ):
        """不同 OOM 訊息格式均應觸發降級。"""
        repaired = RGBDFrame(
            color=np.zeros((10, 10, 3), dtype=np.uint8),
            depth=np.ones((10, 10), dtype=np.float32),
            mask=None
        )
        mock_primary  = MagicMock()
        mock_primary.fill.side_effect = RuntimeError(oom_msg)
        mock_fallback = MagicMock()
        mock_fallback.fill.return_value = repaired

        orchestrator = Orchestrator(
            geo_processor=geo_processor,
            primary_inpainter=mock_primary,
            fallback_inpainter=mock_fallback,
            render_controller=mock_render_controller,
        )

        with patch.object(Orchestrator, '_save_mesh_to_tempfile', return_value='/tmp/mesh.ply'):
            orchestrator.process_and_render(simple_frame)

        mock_fallback.fill.assert_called_once()


# ---------------------------------------------------------------------------
# 管線流程完整性驗證
# ---------------------------------------------------------------------------

class TestPipelineFlow:

    def test_render_controller_load_mesh_called(
        self, simple_frame, geo_processor, telea_inpainter, mock_render_controller
    ):
        """管線結束時，render_controller.load_mesh() 必須被呼叫一次。"""
        orchestrator = Orchestrator(
            geo_processor=geo_processor,
            primary_inpainter=telea_inpainter,
            fallback_inpainter=telea_inpainter,
            render_controller=mock_render_controller,
        )

        with patch.object(Orchestrator, '_save_mesh_to_tempfile', return_value='/tmp/test_mesh.ply'):
            orchestrator.process_and_render(simple_frame)

        mock_render_controller.load_mesh.assert_called_once_with('/tmp/test_mesh.ply')

    def test_edge_mask_is_set_on_frame_before_inpainting(
        self, simple_frame, geo_processor, mock_render_controller
    ):
        """
        進入修補器前，frame.mask 必須已被 Orchestrator 設定（邊緣偵測先於修補）。
        透過 spy 捕捉 fill() 接收到的 frame 來驗證。
        """
        received_frames = []

        class SpyInpainter(TeleaInpainter):
            def fill(self, frame: RGBDFrame) -> RGBDFrame:
                received_frames.append(frame)
                return super().fill(frame)

        spy = SpyInpainter()
        orchestrator = Orchestrator(
            geo_processor=geo_processor,
            primary_inpainter=spy,
            fallback_inpainter=spy,
            render_controller=mock_render_controller,
        )

        with patch.object(Orchestrator, '_save_mesh_to_tempfile', return_value='/tmp/mesh.ply'):
            orchestrator.process_and_render(simple_frame)

        assert len(received_frames) == 1, "fill() 應被呼叫恰好一次。"
        frame_received = received_frames[0]
        assert frame_received.mask is not None, (
            "修補器收到的 frame.mask 不應為 None：邊緣偵測應在修補前完成。"
        )
        assert frame_received.mask.shape == simple_frame.depth.shape, (
            "mask.shape 應與 depth.shape 一致。"
        )
