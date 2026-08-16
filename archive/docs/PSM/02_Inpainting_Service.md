# PSM 設計文件：遮擋修補服務 (Inpainting Service)
**文件路徑**：`docs/PSM/02_Inpainting_Service.md`
**文件版本**：v1.0 (2026-05-27)
**針對環境**：Python 3.10+, NumPy, OpenCV

## 1. 模組職責
接收帶有破洞遮罩 (`mask`) 的 `RGBDFrame`，執行雙重修補 (Color + Depth)，並回傳一張完整無破洞的 `RGBDFrame` 供幾何引擎建立網格。

## 2. 抽象修補介面 (Abstract Inpainter)
此介面約束了所有修補演算法的行為，確保未來 AI 模型的接入擁有一致的簽章。

```python
from abc import ABC, abstractmethod
import numpy as np

# 假設 RGBDFrame 定義於 PSM/00_Data_Contracts.md
from contracts import RGBDFrame 

class AbstractInpainter(ABC):
    """
    無狀態修補策略介面。
    必須同時處理 color 與 depth 矩陣。
    """
    @abstractmethod
    def fill(self, frame: RGBDFrame) -> RGBDFrame:
        """
        輸入：帶有 mask 的 RGBDFrame (mask 中 True 代表需要修補的區域)
        輸出：全新的 RGBDFrame，其 color 與 depth 已被填補，mask 清空。
        """
        pass
```

## 3. 基礎修補策略實作 (Baseline Strategy: Telea)
使用 OpenCV 內建的 Fast Marching Method 進行運算。此策略作為系統的基準線與降級備案 (Fallback)。

```python
import cv2
import numpy as np

class TeleaInpainter(AbstractInpainter):
    def __init__(self, inpaint_radius: int = 3):
        # 設定 Telea 演算法參考周圍像素的半徑大小
        self.radius = inpaint_radius

    def fill(self, frame: RGBDFrame) -> RGBDFrame:
        # 防呆檢查：若沒有 mask，代表無破洞需修補，直接原樣回傳
        if frame.mask is None or not np.any(frame.mask):
            return frame

        # 由於合約中 mask 是 np.bool_，OpenCV 需要 np.uint8 (0 或 255)
        # 轉換 Mask：True -> 255, False -> 0
        cv2_mask = (frame.mask * 255).astype(np.uint8)

        # 1. 執行 RGB 顏色修補 (輸入 Shape: H, W, 3)
        repaired_color = cv2.inpaint(
            frame.color, 
            cv2_mask, 
            self.radius, 
            cv2.INPAINT_TELEA
        )

        # 2. 執行 Depth 深度修補 (輸入 Shape: H, W, float32)
        # OpenCV 的 inpaint 支援單通道 float32 矩陣直接運算
        repaired_depth = cv2.inpaint(
            frame.depth, 
            cv2_mask, 
            self.radius, 
            cv2.INPAINT_TELEA
        )

        # 3. 回傳全新的 DTO (Data Transfer Object)
        return RGBDFrame(
            color=repaired_color,
            depth=repaired_depth,
            mask=None  # 修補完成，清除遮罩
        )
```

## 4. 管線協調層更新 (Orchestrator Update)
指導實作工程師如何在主程式中把「幾何斷邊」跟「修補」串接起來。

```python
# 節錄自 Orchestrator (定義於 PSM/03_Rendering_Pipeline.md)

def process_and_render(self, frame: RGBDFrame):
    # 1. 邊緣偵測：產生斷邊遮罩
    # edge_mask: shape (H, W), boolean
    edge_mask = self.geo_processor.edge_policy.compute_mask(frame.depth)
    frame.mask = edge_mask 

    # 2. 執行修補：將破洞區塊用背景資訊填滿
    # 這裡目前注入的是 TeleaInpainter，未來可依賴注入 LaMaInpainter
    repaired_frame = self.inpainter.fill(frame)

    # 3. 網格生成：將修補完畢的純淨 RGB-D 反投影為 3D 空間網格
    # 注意：此時的 repaired_frame.mask 為 None，因此建面時不會產生物理破洞
    points = self.geo_processor.unproject_to_points(repaired_frame.depth)
    mesh = self.geo_processor.build_topology(points, repaired_frame)

    # 4. 傳送至渲染引擎
    self.renderer.initialize_scene(mesh)
    self.renderer.run_event_loop()
```