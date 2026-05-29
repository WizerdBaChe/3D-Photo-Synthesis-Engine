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
