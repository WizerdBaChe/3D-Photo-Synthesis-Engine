"""
深度估算接口 (Depth Estimator)
==================================
為「只上傳一張 RGB → 自動估算 depth → 合成 3D」的未來功能預留可插拔接口。

本檔**不引入任何模型或重依賴**，僅定義抽象介面與一個 NoOp 佔位實作。
未來要支援單張 RGB 估深時，新增具體實作（例如 MiDaS / Depth-Anything / 外部 API），
並在 get_depth_estimator() 換成該實作即可，**端點與前端皆不需更動**。

語意約定：estimate() 回傳 [0,1] 正規化、值大=遠（metric）的 float32 depth，
與 backend.rgbd_loader.normalize_depth_semantics 的輸出一致，可直接餵入後續管線。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class DepthEstimatorUnavailable(RuntimeError):
    """未啟用 / 未安裝深度估算實作時拋出，端點據此回 422。"""


class DepthEstimator(ABC):
    """單張 RGB → 深度圖的抽象介面。"""

    @abstractmethod
    def estimate(self, rgb: np.ndarray) -> np.ndarray:
        """
        由 RGB 影像（H×W×3, uint8）估算深度。

        回傳：float32, H×W, 值域 [0,1]，值大=遠（metric 語意）。
        未啟用時應拋 DepthEstimatorUnavailable。
        """
        raise NotImplementedError


class NoOpDepthEstimator(DepthEstimator):
    """預設佔位：未接任何模型，呼叫即表示「估算未啟用」。"""

    def estimate(self, rgb: np.ndarray) -> np.ndarray:  # noqa: ARG002
        raise DepthEstimatorUnavailable(
            "自動深度估算尚未啟用，請一併上傳 depth 圖。"
        )


# 單例 provider：未來注入具體實作只需改這裡（端點透過 get_depth_estimator 取得）。
_estimator: DepthEstimator = NoOpDepthEstimator()


def get_depth_estimator() -> DepthEstimator:
    """取得目前的深度估算器（預設 NoOp）。"""
    return _estimator


def set_depth_estimator(estimator: DepthEstimator) -> None:
    """替換深度估算器（供未來接模型 / 測試注入用）。"""
    global _estimator
    _estimator = estimator
