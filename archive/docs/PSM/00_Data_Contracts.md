# PSM 設計文件： 邊緣判定與網格剔除介面
**文件版本**：v1.0 (2026-05-27)
**針對環境**：Python 3.10+, NumPy, OpenCV

## 1. 邊緣判定策略介面 (Edge Detection Policy)

```python
from abc import ABC, abstractmethod
import numpy as np

class EdgeDetectionPolicy(ABC):
    @abstractmethod
    def compute_mask(self, depth_matrix: np.ndarray) -> np.ndarray:
        """
        輸入：Shape (H, W), dtype: np.float32
        輸出：Shape (H, W), dtype: np.bool_ (True 代表斷層邊緣)
        """
        pass

class SobelEdgeDetector(EdgeDetectionPolicy):
    """
    動態 Sobel 邊緣偵測器 (基於分位數)
    """
    def __init__(self, percentile: float = 95.0):
        # 預設將梯度強度落在前 5% 的像素視為邊緣
        self.percentile = percentile

    def compute_mask(self, depth_matrix: np.ndarray) -> np.ndarray:
        # 實作指導 (PSM 規範算法邏輯)：
        # 1. cv2.Sobel 提取 X, Y 梯度，計算 Magnitude (強度)。
        # 2. threshold_value = np.percentile(Magnitude, self.percentile)
        # 3. 回傳 (Magnitude > threshold_value) 的布林遮罩。
        pass
```