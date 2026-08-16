"""
3DGS spike — Flash3D 離線單圖 → .ply（場景級 3D Gaussian Splatting）
====================================================================
依 Flash3D 官方 HF Space（einsafutdinov/flash3d）的推論流程改寫成 CLI：
  讀一張 RGB → preprocess(resize+pad) → GaussianPredictor 推論 → save_ply。

前置（見 README.md）：
  1) gate①：spike/3dgs/.venv-3dgs 已裝 torch cu128，check_env.py 通過。
  2) 已 clone Flash3D 原始碼到 spike/3dgs/flash3d/ 並裝其 requirements。
  3) 權重由 HF Hub 自動下載（einsafutdinov/flash3d）。

執行：
  spike\3dgs\.venv-3dgs\Scripts\python.exe spike\3dgs\run_flash3d.py samples\RGB_TEST.jpg

輸出：
  spike/3dgs/out/<stem>.ply  + 主控台印出峰值 VRAM / 推論秒數 / Gaussian 數。
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

SPIKE_DIR = Path(__file__).resolve().parent
FLASH3D_DIR = SPIKE_DIR / "flash3d"
OUT_DIR = SPIKE_DIR / "out"


def _fail(msg: str) -> "NoReturn":  # type: ignore[name-defined]
    print(f"[FAIL] {msg}")
    sys.exit(1)


def main() -> int:
    ap = argparse.ArgumentParser(description="Flash3D 單圖 → .ply spike")
    ap.add_argument("image", type=Path, help="輸入 RGB 圖路徑")
    ap.add_argument("--num-gauss", type=int, default=2,
                    help="每像素 Gaussian 層數（HF demo 預設 2；OOM 時調降）")
    ap.add_argument("--out", type=Path, default=None, help="輸出 .ply 路徑")
    args = ap.parse_args()

    if not args.image.exists():
        _fail(f"找不到輸入圖：{args.image}")
    if not FLASH3D_DIR.exists():
        _fail(f"尚未 clone Flash3D 到 {FLASH3D_DIR}（見 README 第 1 步）。")

    # 讓 Flash3D 原始碼可被 import。
    sys.path.insert(0, str(FLASH3D_DIR))

    try:
        import torch
        import torchvision.transforms as TT
        import torchvision.transforms.functional as TTF
        from omegaconf import OmegaConf
        from PIL import Image
        from huggingface_hub import hf_hub_download
    except ImportError as e:
        _fail(f"缺套件：{e}。請在 .venv-3dgs 裝 torch cu128 + Flash3D requirements。")

    if not torch.cuda.is_available():
        _fail("CUDA 不可用（gate① 未過）。先跑 check_env.py。")

    # Flash3D 模組（clone 後才在 sys.path 上）。
    try:
        from networks.gaussian_predictor import GaussianPredictor
        from util.export_param import save_ply
    except ImportError as e:
        _fail(f"無法 import Flash3D 模組：{e}。確認 clone 完整、且版本與本腳本相容。")

    device = "cuda"
    repo = "einsafutdinov/flash3d"

    print(f"[*] 下載/載入權重自 HF Hub：{repo}")
    cfg_path = hf_hub_download(repo, "config_re10k_v1.yaml")
    ckpt_path = hf_hub_download(repo, "model_re10k_v1.pth")
    cfg = OmegaConf.load(cfg_path)

    model = GaussianPredictor(cfg)
    ckpt = torch.load(ckpt_path, map_location=device)
    model.load_state_dict(ckpt["model"] if "model" in ckpt else ckpt, strict=False)
    model.to(device).eval()

    # --- preprocess：resize(bicubic) + pad border（照 HF demo）---
    img = Image.open(args.image).convert("RGB")
    h, w = cfg.dataset.height, cfg.dataset.width
    pad = cfg.dataset.pad_border_aug
    t = TTF.resize(img, (h, w), interpolation=TTF.InterpolationMode.BICUBIC)
    t = TT.ToTensor()(t)
    if pad:
        t = TT.Pad((pad, pad))(t)
    t = t.unsqueeze(0).to(device)

    inputs = {("color_aug", 0, 0): t}

    # --- 推論 + 量測 ---
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    t0 = time.time()
    with torch.no_grad():
        outputs = model(inputs)
    torch.cuda.synchronize()
    dt = time.time() - t0
    peak_gb = torch.cuda.max_memory_allocated() / (1024**3)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.out or (OUT_DIR / f"{args.image.stem}.ply")
    save_ply(outputs, str(out_path), num_gauss=args.num_gauss)

    size_mb = out_path.stat().st_size / (1024**2) if out_path.exists() else 0.0
    print("\n==== Flash3D spike 結果 ====")
    print(f"輸入圖         : {args.image}  → resize {w}x{h} (+pad {pad})")
    print(f"推論秒數       : {dt:.2f} s")
    print(f"峰值 VRAM      : {peak_gb:.2f} GiB / 8 GiB")
    print(f"輸出 .ply      : {out_path}  ({size_mb:.1f} MiB)")
    print("\n下一步：把 .ply 拖進 https://antimatter15.com/splat/ 或 SuperSplat 檢視（gate②）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
