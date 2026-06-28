# PSM 設計文件：Phase 4 AI 修補與資源管理
**文件路徑**：`docs/PSM/04_AI_Inpainting_Service.md`
**文件版本**：v1.0 (2026-05-27)
**針對環境**：Python 3.10+, PyTorch, NumPy, OpenCV

## 1. 顯存管理策略列舉 (VRAM Strategy Enum)
定義公開的設定選項，以供外部 GUI 元件綁定。

```python
from enum import Enum

class VramStrategy(Enum):
    PERSISTENT = "persistent" # 效能優先：模型常駐顯存
    LAZY = "lazy"             # 資源友善：推論後立即清空顯存
```

## 2. AI 修補模組實作 (LaMa Inpainter)
此模組繼承自 Phase 3 定義的 `AbstractInpainter`。模組內部封裝了 PyTorch 的 Tensor 轉換，確保對外依舊只吃 `RGBDFrame` 吐 `RGBDFrame`。

```python
import torch
import numpy as np
import gc
# 假設 LaMa 模型架構已於外部定義
# from model import LaMaNetwork 

class LaMaInpainter(AbstractInpainter):
    def __init__(self, model_path: str, strategy: VramStrategy):
        self.model_path = model_path
        self.strategy = strategy
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.model = None
        
        # 若為常駐模式，初始化時直接載入模型
        if self.strategy == VramStrategy.PERSISTENT:
            self._load_model()

    def _load_model(self):
        if self.model is None:
            self.model = LaMaNetwork()
            self.model.load_state_dict(torch.load(self.model_path))
            self.model.to(self.device)
            self.model.eval()

    def _unload_model(self):
        """徹底釋放 PyTorch 佔用的 VRAM"""
        if self.model is not None:
            del self.model
            self.model = None
            gc.collect() # 強制 Python 垃圾回收
            torch.cuda.empty_cache() # 強制 PyTorch 釋放 GPU 記憶體

    def fill(self, frame: RGBDFrame) -> RGBDFrame:
        if frame.mask is None:
            return frame

        try:
            # 1. 資源準備
            if self.strategy == VramStrategy.LAZY:
                self._load_model()

            # 2. NumPy 轉 Tensor (PSM 規範：需處理維度轉換 HWC -> CHW)
            # 略：實作 image_tensor, mask_tensor, depth_tensor

            # 3. 推論 (禁止計算梯度以節省 VRAM)
            with torch.no_grad():
                repaired_color_tensor = self.model(image_tensor, mask_tensor)
                # 實務上 LaMa 原始模型僅支援 RGB。
                # Depth 矩陣需複製為 3 通道輸入，推論後再轉回單通道 float32。
                repaired_depth_tensor = self.model(depth_tensor_3ch, mask_tensor)

            # 4. Tensor 轉回 NumPy 
            # 略：產出 repaired_color_np, repaired_depth_np

            return RGBDFrame(
                color=repaired_color_np,
                depth=repaired_depth_np,
                mask=None
            )

        finally:
            # 無論推論成功或失敗，LAZY 模式必須確保資源被釋放
            if self.strategy == VramStrategy.LAZY:
                self._unload_model()
```

## 3. 管線協調層容錯機制 (Orchestrator Fallback Logic)
主程式必須捕捉 PyTorch 特有的 `RuntimeError`，並切換至 OpenCV (Telea) 作為備案。

```python
# 節錄更新自 Orchestrator 

def __init__(self, geo_processor, primary_inpainter: LaMaInpainter, fallback_inpainter: TeleaInpainter, renderer):
    self.primary_inpainter = primary_inpainter
    self.fallback_inpainter = fallback_inpainter
    # ... 略

def process_and_render(self, frame: RGBDFrame):
    # 1. 幾何斷邊
    frame.mask = self.geo_processor.edge_policy.compute_mask(frame.depth)
    
    # 2. 具備容錯機制的修補
    repaired_frame = None
    try:
        # 嘗試使用高階 AI 模型
        repaired_frame = self.primary_inpainter.fill(frame)
    except RuntimeError as e:
        # 捕捉 CUDA Out of Memory 錯誤
        if "out of memory" in str(e).lower():
            print("警告：VRAM 不足 (OOM)，觸發 Telea 降級修補備案。")
            # 確保殘留的 Tensor 被清空
            torch.cuda.empty_cache() 
            repaired_frame = self.fallback_inpainter.fill(frame)
        else:
            # 其他未知錯誤，向上拋出
            raise e

    # 3. 網格生成與渲染 (同 Phase 3)
    # ... 略
```