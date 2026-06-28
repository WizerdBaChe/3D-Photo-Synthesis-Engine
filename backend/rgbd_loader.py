"""
RGB-D 載入與內參估算 (RGB-D Loader)
=====================================
職責：把上傳的 RGB / Depth 影像位元組解碼、正規化、對齊，封裝為 RGBDFrame，
並估算相機內參。此邏輯自桌面版 SynthesisWorker 抽出，與框架無關。

設計：
  - 純函數風格，輸入 bytes / ndarray，輸出 DTO，便於測試。
  - 深度正規化到 [0,1]（相對深度），實際 Z 尺度由 CameraIntrinsics.depth_near/far
    在反投影時還原（C-3）。
"""

from __future__ import annotations

import logging

import cv2
import numpy as np

from src.core.contracts import RGBDFrame, CameraIntrinsics

logger = logging.getLogger(__name__)

# 統一後的 depth 語意：值大 = 遠（metric 慣例）。
DEPTH_CONVENTIONS = ("auto", "disparity", "metric")
_DISPARITY_EPS = 1e-3   # 視差→深度 1/(d+eps) 的防除零常數


def decode_image(data: bytes, flags: int) -> np.ndarray:
    """將位元組解碼為 ndarray（cv2.imdecode）。失敗則拋 ValueError。"""
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, flags)
    if img is None:
        raise ValueError("影像解碼失敗：格式不支援或檔案損毀。")
    return img


def _detect_is_disparity(depth01: np.ndarray) -> bool:
    """
    啟發式判定正規化深度圖 [0,1] 是否為 disparity（視差：近=亮、值大）。

    判據（保守、可解釋）：disparity 圖的近物（大值）通常佔比小、直方圖右偏
    （少數很亮的近物 + 大片較暗背景）。右偏代表少數高值離群把平均拉高，
    故 mean > median（skew = mean - median > 0），且高值像素佔比小。
    判不準時預設當 disparity（ML 模型輸出佔多數）。

    同時印出直方圖摘要供日後 trace 誤判（使用者要求）。
    """
    mean = float(depth01.mean())
    median = float(np.median(depth01))
    # 偏態指標：(mean - median) 為正代表右偏（少數高值離群），偏向 disparity。
    skew_hint = mean - median
    high_frac = float((depth01 > 0.7).mean())   # 高值（近物）像素佔比
    # 右偏（少數亮近物拉高平均）且高值像素稀少 → 判為 disparity。
    is_disparity = (skew_hint > 0.0) and (high_frac < 0.35)

    logger.info(
        "[depth auto] mean=%.4f median=%.4f skew(mean-median)=%.4f "
        "high_frac(>0.7)=%.4f → 判定=%s",
        mean, median, skew_hint, high_frac,
        "disparity" if is_disparity else "metric",
    )
    return is_disparity


def normalize_depth_semantics(depth01: np.ndarray, depth_convention: str) -> np.ndarray:
    """
    將正規化深度 [0,1] 統一成 metric 語意（值大=遠），回傳重正規化的 [0,1]。

    - metric    ：不變（假設輸入近=暗、遠=亮）。
    - disparity ：視差→深度 1/(d+eps)，再重正規化回 [0,1]。
    - auto      ：以 _detect_is_disparity 判定後套上述其一。
    """
    if depth_convention not in DEPTH_CONVENTIONS:
        raise ValueError(
            f"depth_convention 須為 {DEPTH_CONVENTIONS} 之一，收到: {depth_convention}"
        )

    convention = depth_convention
    if convention == "auto":
        convention = "disparity" if _detect_is_disparity(depth01) else "metric"

    if convention == "metric":
        return depth01

    # disparity → metric：近(大視差) 應變成小 Z，1/(d+eps) 達成反轉。
    inv = 1.0 / (depth01 + _DISPARITY_EPS)
    inv_min, inv_max = float(inv.min()), float(inv.max())
    rng = inv_max - inv_min
    if rng <= 0.0:
        return np.zeros_like(depth01, dtype=np.float32)
    return ((inv - inv_min) / rng).astype(np.float32)


def load_rgbd_from_bytes(
    rgb_bytes: bytes,
    depth_bytes: bytes,
    max_pixels: int = 500_000,
    depth_convention: str = "auto",
) -> RGBDFrame:
    """
    從上傳的 RGB 與 Depth 影像位元組建立 RGBDFrame（FR-001）。

    支援：
      RGB:   PNG / JPG / BMP（任意 3 通道）
      Depth: PNG 8/16bit、TIFF、單通道灰階（保留原位元深度）

    正規化：
      深度 → float32，若 max > 1 則除以 max 壓到 [0,1]（相對深度）。
      RGB/Depth 解析度不一致時，雙線性縮放 Depth 對齊 RGB。

    max_pixels：輸出網格頂點數上限（即 H×W），超過時等比例縮圖。
      預設 500,000（約 700×700），對應 .glb ≤ ~30 MB，瀏覽器可流暢載入。
      設為 0 停用限制（僅限後端測試用途）。

    depth_convention：深度語意，"auto"|"disparity"|"metric"（預設 auto）。
      統一成 metric（值大=遠）後送進 pipeline，避免 disparity 圖造成深度反轉。
    """
    # RGB（BGR → RGB）
    color_bgr = decode_image(rgb_bytes, cv2.IMREAD_COLOR)
    color_rgb = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)

    # Depth（保留位元深度 + 灰階）
    depth_raw = decode_image(depth_bytes, cv2.IMREAD_ANYDEPTH | cv2.IMREAD_GRAYSCALE)

    depth_f32 = depth_raw.astype(np.float32)
    max_val = float(depth_f32.max())
    if max_val > 1.0:
        depth_f32 /= max_val

    # depth 語意統一（在 resize 前對原始值轉換較穩定）→ 一律 metric（值大=遠）
    depth_f32 = normalize_depth_semantics(depth_f32, depth_convention)

    # 解析度對齊（先對齊再降採樣，確保比例一致）
    h_rgb, w_rgb = color_rgb.shape[:2]
    h_dep, w_dep = depth_f32.shape[:2]
    if (h_rgb, w_rgb) != (h_dep, w_dep):
        depth_f32 = cv2.resize(
            depth_f32, (w_rgb, h_rgb), interpolation=cv2.INTER_LINEAR
        )

    # 降採樣：超過 max_pixels 時等比例縮圖（保持寬高比）
    if max_pixels > 0:
        h, w = color_rgb.shape[:2]
        total = h * w
        if total > max_pixels:
            scale = (max_pixels / total) ** 0.5
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            color_rgb = cv2.resize(color_rgb, (new_w, new_h), interpolation=cv2.INTER_AREA)
            depth_f32 = cv2.resize(depth_f32, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    return RGBDFrame(color=color_rgb, depth=depth_f32)


def estimate_intrinsics(
    frame: RGBDFrame,
    fov_deg: float = 60.0,
    depth_near: float = 1.0,
    depth_far: float = 4.0,
) -> CameraIntrinsics:
    """
    依圖片解析度與水平 FOV 估算相機內參。

    fx = w / (2 * tan(FOV/2))；光心居中。
    depth_near/far 控制 3D 視差強度（C-3），由呼叫端依需求調整。
    """
    h, w = frame.color.shape[:2]
    fx = fy = w / (2.0 * np.tan(np.radians(fov_deg / 2.0)))
    return CameraIntrinsics(
        fx=fx, fy=fy, cx=w / 2.0, cy=h / 2.0,
        width=w, height=h,
        depth_near=depth_near, depth_far=depth_far,
    )
