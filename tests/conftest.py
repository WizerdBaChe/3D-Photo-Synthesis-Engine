"""
pytest 共用 Fixtures (conftest.py)
=====================================
供所有測試層（unit / integration / benchmark）共用的測試夾具。

設計原則：
  - 所有 Fixture 使用合成資料（Synthetic Data），不依賴真實圖片。
  - 測試不啟動 GUI 視窗，不佔用真實 GPU 資源（階層一規範）。
  - 以 numpy.testing 進行矩陣比對，確保數值正確性。
"""

import numpy as np
import pytest

from src.core.contracts import RGBDFrame, CameraIntrinsics


# ---------------------------------------------------------------------------
# 基礎合成影像 Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def small_rgbd_frame() -> RGBDFrame:
    """
    10×10 的最小合成 RGB-D 幀，深度全為 1.0。
    用於快速驗證資料契約、維度一致性與基本幾何運算。
    """
    color = np.zeros((10, 10, 3), dtype=np.uint8)
    depth = np.ones((10, 10), dtype=np.float32)
    return RGBDFrame(color=color, depth=depth)


@pytest.fixture
def cliff_rgbd_frame() -> RGBDFrame:
    """
    10×10 的斷崖合成 RGB-D 幀：左半部深度 1.0，右半部深度 100.0。
    用於驗證 Sobel 斷邊偵測與網格斷裂（Tearing）邏輯。
    """
    depth = np.ones((10, 10), dtype=np.float32)
    depth[:, 5:] = 100.0
    color = np.zeros((10, 10, 3), dtype=np.uint8)
    return RGBDFrame(color=color, depth=depth)


@pytest.fixture
def masked_rgbd_frame() -> RGBDFrame:
    """
    10×10 的帶遮罩 RGB-D 幀，中央 2×2 區塊標記為需修補。
    用於驗證 TeleaInpainter 的修補行為與輸出契約。
    """
    color = (np.random.rand(10, 10, 3) * 255).astype(np.uint8)
    depth = np.random.rand(10, 10).astype(np.float32)
    mask  = np.zeros((10, 10), dtype=np.bool_)
    mask[4:6, 4:6] = True   # 中央 2×2 破洞
    return RGBDFrame(color=color, depth=depth, mask=mask)


@pytest.fixture
def no_mask_rgbd_frame() -> RGBDFrame:
    """無遮罩 RGB-D 幀，用於驗證修補器的快速路徑（應直接回傳原物件）。"""
    color = np.zeros((8, 8, 3), dtype=np.uint8)
    depth = np.ones((8, 8), dtype=np.float32)
    return RGBDFrame(color=color, depth=depth, mask=None)


@pytest.fixture
def all_false_mask_frame() -> RGBDFrame:
    """遮罩全為 False 的 RGB-D 幀，驗證修補器不執行無效修補。"""
    color = np.zeros((8, 8, 3), dtype=np.uint8)
    depth = np.ones((8, 8), dtype=np.float32)
    mask  = np.zeros((8, 8), dtype=np.bool_)
    return RGBDFrame(color=color, depth=depth, mask=mask)


# ---------------------------------------------------------------------------
# 相機內參 Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def default_intrinsics() -> CameraIntrinsics:
    """
    10×10 圖片的預設相機內參（光心居中，焦距 500px）。
    用於幾何處理器的單元測試。

    C-3 註：單元測試刻意使用「恆等深度映射」(depth_near=0, depth_far=1)，
    使 Z = d，隔離並驗證反投影『公式本身』的正確性；
    生產預設的 near/far 視差尺度由 contracts.py 的預設值與整合層負責。
    """
    return CameraIntrinsics(
        fx=500.0, fy=500.0, cx=5.0, cy=5.0, width=10, height=10,
        depth_near=0.0, depth_far=1.0,
    )


@pytest.fixture
def identity_intrinsics() -> CameraIntrinsics:
    """
    fx=fy=1, cx=cy=0 的單位內參，使 X=U*Z, Y=V*Z，方便驗算反投影數值。
    同樣採用恆等深度映射（Z = d），驗算公式不受 near/far 影響。
    """
    return CameraIntrinsics(
        fx=1.0, fy=1.0, cx=0.0, cy=0.0, width=10, height=10,
        depth_near=0.0, depth_far=1.0,
    )
