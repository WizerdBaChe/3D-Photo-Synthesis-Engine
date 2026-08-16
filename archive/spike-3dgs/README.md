# Phase 4 軌道二 — 3DGS Spike

> 目的：在本機 GPU 實跑「單圖 → 場景級 3D Gaussian Splatting」，量測品質 / 延遲 / VRAM /
> 安裝可行性，產出 go/no-go 決策。**這是隔離 spike，不污染主線**——所有重依賴、權重、輸出、
> 虛擬環境都在本資料夾且被 `.gitignore`，主 `.venv` 與 `requirements.txt` 一律不動。

完整計畫見 `references/3D-photo-engine-phase4-plan.md` 與 phase-log 的對應 checkpoint。

## 硬體（本機，已確認）

| 項目 | 值 |
|---|---|
| GPU | RTX 5070 Laptop |
| VRAM | 8 GiB（偏緊，場景級 3DGS 可能 OOM） |
| Compute capability | sm_120（Blackwell） |
| Driver | 610.47 |
| CUDA Toolkit（已裝） | v12.8 + v13.0（nvcc 13.0 在 PATH） |
| 主 .venv Python | 3.12.7（純 NumPy/OpenCV，**無 torch**） |

**關鍵相容性**：sm_120 在 PyTorch 穩定輪尚未支援，必須用 **cu128**（或 nightly）wheel。

## 安裝（隔離 venv）

```powershell
# 在 repo 根目錄
py -3.12 -m venv spike\3dgs\.venv-3dgs
spike\3dgs\.venv-3dgs\Scripts\python.exe -m pip install --upgrade pip
spike\3dgs\.venv-3dgs\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
```

## gate① — 環境檢查

```powershell
spike\3dgs\.venv-3dgs\Scripts\python.exe spike\3dgs\check_env.py
```

須見 `[PASS] gate①`（torch 能在 sm_120 上實際 matmul）。不過則先解 torch/CUDA，再往下。

## 候選方法

| 方法 | 場景/物件 | 授權 | 角色 |
|---|---|---|---|
| Flash3D (arXiv 2406.04343) | 場景級 | CC BY-NC（非商用） | spike 主力 |
| NVIDIA Lyra 2.0 | 場景級 | Apache 2.0（可商用） | 商用替代候選 |
| TripoSplat / DiffSplat | 物件級 | MIT | 對照組（不解場景需求） |

## 實測紀錄（待填）

| 項目 | Flash3D | Lyra 2.0 |
|---|---|---|
| gate① torch sm_120 | — | — |
| 安裝是否順利 / 踩雷 | — | — |
| 峰值 VRAM | — | — |
| 推論秒數 | — | — |
| Gaussian 數 / 輸出大小 | — | — |
| 品質（房間圖大洞是否填補、無閃爍） | — | — |
| **go / no-go** | — | — |

截圖存 `out/`（gitignore）。
