"""
管線中間產物檢視工具 (Pipeline Inspector)
=============================================
獨立 CLI 診斷腳本：吃一組 RGB / depth 圖檔，跑完整合成管線，把每個階段的
中間產物 dump 成檔案，方便定位「放射狀線條」等 artefact 的成因。

與 /synthesize 解耦——不啟動 web server、不影響請求路徑，純離線診斷。
重用 backend / src.core 既有元件，不複製管線邏輯（只是把 Orchestrator.process
的步驟攤開以擷取中間張量）。

用法：
    .venv/Scripts/python scripts/inspect_pipeline.py \
        --rgb samples/RGB_TEST.jpg --depth samples/DEPTH_TEST.png \
        --out debug_out

dump 產物：
    01_norm_depth.png      正規化後深度（normalize_depth_semantics + resize 對齊後）
    02_cliff_mask.png      斷崖遮罩疊在深度上（紅 = 被切的斷崖像素）
    03_inpainted_depth.png Telea 修補後深度（看修補斜坡 artefact）
    04_mesh_stats.json     頂點/面數 + 3D 邊長百分位與直方圖（放射線的量化指紋）
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import cv2
import numpy as np

# 確保可從 repo root import（腳本可能在任意 cwd 被呼叫）
import sys
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from backend.rgbd_loader import load_rgbd_from_bytes, estimate_intrinsics
from src.core.geometry import GeometryProcessor
from src.core.inpainting import TeleaInpainter
from src.core.policies import DepthDiscontinuityPolicy

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("inspect")


def _depth_to_u8(depth01: np.ndarray) -> np.ndarray:
    """正規化深度 [0,1] → 8bit 灰階（近全平時避免除零）。"""
    d = depth01.astype(np.float32)
    lo, hi = float(d.min()), float(d.max())
    rng = hi - lo
    if rng <= 1e-12:
        return np.zeros(d.shape, dtype=np.uint8)
    return (((d - lo) / rng) * 255.0).astype(np.uint8)


def _edge_lengths_3d(vertices: np.ndarray, faces: np.ndarray) -> np.ndarray:
    """每個三角面三邊在 3D 的長度，攤平成 (3F,) 向量。"""
    if faces.shape[0] == 0:
        return np.empty((0,), dtype=np.float64)
    v0 = vertices[faces[:, 0]].astype(np.float64)
    v1 = vertices[faces[:, 1]].astype(np.float64)
    v2 = vertices[faces[:, 2]].astype(np.float64)
    e01 = np.linalg.norm(v1 - v0, axis=1)
    e12 = np.linalg.norm(v2 - v1, axis=1)
    e20 = np.linalg.norm(v0 - v2, axis=1)
    return np.concatenate([e01, e12, e20])


def inspect(rgb_path: Path, depth_path: Path, out_dir: Path,
            max_pixels: int, depth_convention: str,
            depth_near: float, depth_far: float, fov_deg: float,
            max_edge_ratio: float | None = None) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)

    rgb_bytes = rgb_path.read_bytes()
    depth_bytes = depth_path.read_bytes()

    # --- 載入 + depth 語意統一（auto 啟發式 log 會在此印出）---
    frame = load_rgbd_from_bytes(
        rgb_bytes, depth_bytes, max_pixels=max_pixels,
        depth_convention=depth_convention,
    )
    h, w = frame.color.shape[:2]
    logger.info("載入完成：%dx%d，convention=%s", w, h, depth_convention)

    # 01: 正規化深度
    cv2.imwrite(str(out_dir / "01_norm_depth.png"), _depth_to_u8(frame.depth))

    # --- 斷崖遮罩（與 build_topology 內重算的一致）---
    policy = DepthDiscontinuityPolicy()
    cliff = policy.compute_mask(frame.depth)
    cliff_frac = float(cliff.mean())
    logger.info("斷崖遮罩：%d 像素 (%.2f%%)", int(cliff.sum()), cliff_frac * 100)

    # 02: 斷崖疊圖（紅）
    overlay = cv2.cvtColor(_depth_to_u8(frame.depth), cv2.COLOR_GRAY2BGR)
    overlay[cliff] = (0, 0, 255)
    cv2.imwrite(str(out_dir / "02_cliff_mask.png"), overlay)

    # --- 修補（破洞語意：frame.mask 給 inpainter）---
    frame.mask = cliff
    telea = TeleaInpainter(inpaint_radius=3)
    repaired = telea.fill(frame)

    # 03: 修補後深度
    cv2.imwrite(str(out_dir / "03_inpainted_depth.png"), _depth_to_u8(repaired.depth))

    # --- 反投影 + 建面（不開邊長剔除，量測原始分布）---
    intr = estimate_intrinsics(
        repaired, fov_deg=fov_deg, depth_near=depth_near, depth_far=depth_far
    )
    geo = GeometryProcessor(intr, policy, max_edge_ratio=max_edge_ratio)
    points = geo.unproject_to_points(repaired.depth)
    mesh = geo.build_topology(points, repaired)
    logger.info("max_edge_ratio=%s → 面數=%d", max_edge_ratio, int(mesh.face_count))

    # --- 3D 邊長統計（放射線指紋）---
    el = _edge_lengths_3d(mesh.vertices, mesh.faces)
    pct = {f"p{p}": float(np.percentile(el, p)) for p in (50, 90, 95, 99, 99.9)} if el.size else {}
    median = pct.get("p50", 0.0)
    stats = {
        "image": {"width": w, "height": h, "convention": depth_convention,
                  "depth_near": depth_near, "depth_far": depth_far, "fov_deg": fov_deg},
        "cliff_mask_fraction": cliff_frac,
        "vertices": int(mesh.vertex_count),
        "faces": int(mesh.face_count),
        "edge_length_percentiles": pct,
        "edge_length_max": float(el.max()) if el.size else 0.0,
        # 長尾比值：p99/median、max/median 越大 = 放射線越嚴重
        "p99_over_median": (pct.get("p99", 0.0) / median) if median > 0 else None,
        "max_over_median": (float(el.max()) / median) if (el.size and median > 0) else None,
        # 直方圖（log-spaced bins，顯示長尾）
        "edge_length_histogram": _histogram(el),
    }
    (out_dir / "04_mesh_stats.json").write_text(
        json.dumps(stats, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("邊長 p50=%.4f p99=%.4f max=%.4f (p99/median=%.1fx, max/median=%.1fx)",
                pct.get("p50", 0.0), pct.get("p99", 0.0), stats["edge_length_max"],
                stats["p99_over_median"] or 0.0, stats["max_over_median"] or 0.0)
    logger.info("dump 完成 → %s", out_dir)
    return stats


def _histogram(el: np.ndarray, bins: int = 20) -> dict:
    if el.size == 0:
        return {}
    counts, edges = np.histogram(el, bins=bins)
    return {"counts": counts.tolist(), "bin_edges": [float(e) for e in edges]}


def main() -> None:
    ap = argparse.ArgumentParser(description="3D Photo 合成管線中間產物檢視工具")
    ap.add_argument("--rgb", required=True, type=Path)
    ap.add_argument("--depth", required=True, type=Path)
    ap.add_argument("--out", type=Path, default=Path("debug_out"))
    ap.add_argument("--max-pixels", type=int, default=500_000)
    ap.add_argument("--depth-convention", default="auto",
                    choices=("auto", "disparity", "metric"))
    ap.add_argument("--depth-near", type=float, default=1.0)
    ap.add_argument("--depth-far", type=float, default=4.0)
    ap.add_argument("--fov-deg", type=float, default=60.0)
    ap.add_argument("--max-edge-ratio", type=float, default=None,
                    help="3D 邊長剔除門檻（×中位邊長）；不給=關閉")
    args = ap.parse_args()

    inspect(args.rgb, args.depth, args.out, args.max_pixels,
            args.depth_convention, args.depth_near, args.depth_far, args.fov_deg,
            max_edge_ratio=args.max_edge_ratio)


if __name__ == "__main__":
    main()
