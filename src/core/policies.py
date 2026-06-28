"""
邊緣判定策略層 (Edge Detection Policies)
=========================================
設計依據：DD-005（策略模式）、DD-006（百分位數動態閾值）

規範：
- 所有策略繼承 EdgeDetectionPolicy。
- GeometryProcessor 在初始化時注入策略實例（依賴注入）。
- 新增演算法時，直接繼承此 ABC，無需修改幾何引擎底層（OCP 開閉原則）。
"""

from abc import ABC, abstractmethod

import cv2
import numpy as np


class EdgeDetectionPolicy(ABC):
    """
    邊緣判定策略抽象介面。

    唯一職責：接收深度矩陣，回傳標記斷邊位置的布林遮罩。
    """

    @abstractmethod
    def compute_mask(self, depth_matrix: np.ndarray) -> np.ndarray:
        """
        輸入：Shape (H, W), dtype: np.float32 — 正規化深度圖
        輸出：Shape (H, W), dtype: np.bool_   — True 代表深度斷崖邊緣
        """
        pass


class SobelEdgeDetector(EdgeDetectionPolicy):
    """
    動態 Sobel 邊緣偵測器（DD-006 決策實作）。

    核心機制：以 NumPy 計算整張梯度矩陣的第 N 百分位數作為動態閾值，
    確保系統能自適應任意場景的深度尺度，只切斷「最劇烈前 (100-percentile)%」的斷崖。

    Args:
        percentile: 梯度幅度的百分位數門檻（預設 95.0，即僅最強 5% 視為斷崖）。
    """

    def __init__(self, percentile: float = 95.0):
        if not (0.0 <= percentile <= 100.0):
            raise ValueError(f"percentile 需介於 0 ~ 100，收到: {percentile}")
        self.percentile = percentile

    def compute_mask(self, depth_matrix: np.ndarray) -> np.ndarray:
        """
        1. 以 Sobel 算子提取 X、Y 梯度，合成幅度圖。
        2. 取第 percentile 百分位數作為動態閾值。
        3. 幅度超過閾值的像素標記為 True（斷崖）。
        """
        # Step 1: Sobel 梯度（使用 64F 防止溢位）
        grad_x = cv2.Sobel(depth_matrix, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(depth_matrix, cv2.CV_64F, 0, 1, ksize=3)
        magnitude = np.sqrt(grad_x ** 2 + grad_y ** 2).astype(np.float32)

        # Step 2: 動態百分位數閾值（自適應各種場景深度尺度）
        threshold_value = float(np.percentile(magnitude, self.percentile))

        # Step 3: 布林遮罩（幅度超過閾值 → 斷崖邊緣）
        return (magnitude > threshold_value).astype(np.bool_)


class DepthDiscontinuityPolicy(EdgeDetectionPolicy):
    """
    深度不連續斷崖偵測器（預設策略，取代純 Sobel）。

    動機：
      純 Sobel 百分位是「相對」閾值（永遠切最陡的固定比例），對平滑的 ML
      推估 depth（經雙線性 resize、無真實斷崖）會切錯位置——真正的前/背景
      邊界沒被切、雜訊緩坡反被切，導致反投影把深度不連續處沿光心射線拉成
      放射狀長條。

    兩階段判定（絕對深度差為主、Sobel 為輔）：
      1. 候選邊界（主）：相鄰像素深度差 > 場景深度範圍的 abs_diff_ratio 比例
         即視為候選斷崖。以「場景範圍的比例」自適應任意深度尺度，又是
         「絕對」差異，不會像百分位那樣強制切固定比例。
      2. Sobel refinement（輔，可關）：以 Sobel 梯度的百分位門檻與候選取交集，
         去除候選中的緩坡雜訊、保留真正陡峭的不連續。

    use_sobel_refinement=False 時退化為「純絕對深度差」版本，便於在 noisy 圖上
    做 quick bisect——若關閉 Sobel 後 artefact 消失，即可定位問題出在 refinement。

    Args:
        abs_diff_ratio:        相鄰像素深度差門檻（佔場景深度範圍的比例，預設 0.04）。
        use_sobel_refinement:  是否啟用 Sobel 細化（預設 True）。
        sobel_percentile:      Sobel 細化的梯度百分位門檻（預設 90.0）。
    """

    def __init__(
        self,
        abs_diff_ratio: float = 0.04,
        use_sobel_refinement: bool = True,
        sobel_percentile: float = 90.0,
    ):
        if not (0.0 < abs_diff_ratio <= 1.0):
            raise ValueError(f"abs_diff_ratio 需介於 (0, 1]，收到: {abs_diff_ratio}")
        if not (0.0 <= sobel_percentile <= 100.0):
            raise ValueError(f"sobel_percentile 需介於 0 ~ 100，收到: {sobel_percentile}")
        self.abs_diff_ratio = abs_diff_ratio
        self.use_sobel_refinement = use_sobel_refinement
        self.sobel_percentile = sobel_percentile

    def compute_mask(self, depth_matrix: np.ndarray) -> np.ndarray:
        depth = depth_matrix.astype(np.float32)

        # --- 階段 1（主）：絕對深度差候選邊界 ---
        # 場景深度範圍（峰對峰），作為自適應的絕對門檻基準。
        depth_range = float(depth.max() - depth.min())
        if depth_range <= 0.0:
            # 全平深度圖：無任何斷崖。
            return np.zeros(depth.shape, dtype=np.bool_)
        abs_threshold = self.abs_diff_ratio * depth_range

        # 相鄰像素深度差（左右、上下）。對每個像素，只要其任一方向的鄰居
        # 深度差超過門檻，即標記為候選斷崖（兩側像素都標，確保整道斷崖被切）。
        candidate = np.zeros(depth.shape, dtype=np.bool_)
        diff_x = np.abs(np.diff(depth, axis=1)) > abs_threshold  # (H, W-1)
        candidate[:, :-1] |= diff_x
        candidate[:, 1:]  |= diff_x
        diff_y = np.abs(np.diff(depth, axis=0)) > abs_threshold  # (H-1, W)
        candidate[:-1, :] |= diff_y
        candidate[1:, :]  |= diff_y

        if not self.use_sobel_refinement:
            return candidate

        # --- 階段 2（輔，可關）：Sobel 梯度細化 ---
        # 僅保留「候選邊界 ∩ 梯度夠陡」者，剔除緩坡雜訊。
        grad_x = cv2.Sobel(depth, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(depth, cv2.CV_64F, 0, 1, ksize=3)
        magnitude = np.sqrt(grad_x ** 2 + grad_y ** 2)
        # 只在候選像素上取百分位，避免大片平坦區把門檻拉到 0。
        cand_mag = magnitude[candidate]
        if cand_mag.size == 0:
            return candidate
        sobel_threshold = float(np.percentile(cand_mag, self.sobel_percentile))
        steep = magnitude >= sobel_threshold
        return (candidate & steep).astype(np.bool_)
