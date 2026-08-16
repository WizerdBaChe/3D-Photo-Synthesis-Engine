"""
3DGS spike — 環境 gate① 檢查
============================
在隔離的 .venv-3dgs 內執行，確認 torch 真能驅動本機 RTX 5070（sm_120 / Blackwell）。

通過標準：
  - torch.cuda.is_available() == True
  - device capability == (12, 0)   ← sm_120，穩定輪不支援，須 cu128/nightly
  - 能在 GPU 上實際配置 + 矩陣乘（不只是偵測到卡，而是 kernel 真能跑）

任一不過 → 先解 torch/CUDA 安裝，再往 Flash3D 推論前進。

執行：
  spike/3dgs/.venv-3dgs/Scripts/python.exe spike/3dgs/check_env.py
"""

from __future__ import annotations

import sys


def main() -> int:
    try:
        import torch
    except ImportError:
        print("[FAIL] torch 未安裝。請先：")
        print("  pip install torch torchvision --index-url "
              "https://download.pytorch.org/whl/cu128")
        return 1

    print(f"torch            : {torch.__version__}")
    print(f"torch CUDA build : {torch.version.cuda}")
    print(f"cuda.is_available: {torch.cuda.is_available()}")

    if not torch.cuda.is_available():
        print("[FAIL] CUDA 不可用——torch 看不到 GPU。檢查驅動 / 是否裝到 CPU-only wheel。")
        return 1

    name = torch.cuda.get_device_name(0)
    cap = torch.cuda.get_device_capability(0)
    total_gb = torch.cuda.get_device_properties(0).total_memory / (1024**3)
    print(f"device           : {name}")
    print(f"capability       : sm_{cap[0]}{cap[1]}  {cap}")
    print(f"total VRAM       : {total_gb:.2f} GiB")

    if cap < (12, 0):
        print(f"[WARN] capability {cap} < (12,0)；本機應為 sm_120，確認沒抓錯 GPU。")

    # 真正在 GPU 上跑一個 kernel——偵測到卡 ≠ kernel 能編譯執行（sm_120 的關鍵驗證）。
    try:
        a = torch.randn(2048, 2048, device="cuda")
        b = torch.randn(2048, 2048, device="cuda")
        c = (a @ b).sum().item()
        torch.cuda.synchronize()
        peak_mb = torch.cuda.max_memory_allocated() / (1024**2)
        print(f"matmul on GPU    : OK (sum={c:.1f}, peak={peak_mb:.1f} MiB)")
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] GPU kernel 執行失敗（多半是 sm_120 無對應 kernel）：{e}")
        print("  → 需要 cu128 或更新的 nightly wheel。")
        return 1

    print("\n[PASS] gate① 通過：torch 能在 sm_120 上實際運算。可進 Flash3D 推論。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
