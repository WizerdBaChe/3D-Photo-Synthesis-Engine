"""
階層三效能基準測試：端到端 SLA 驗證
(run_benchmarks.py)
=====================================
驗證目標（02_verification_testing.md §4.2）：
  ┌──────────────────────────────┬──────────┬──────────┐
  │ 指標                          │ 測試解析度 │ 合格門檻  │
  ├──────────────────────────────┼──────────┼──────────┤
  │ 幾何預處理（斷邊 + 建網格）     │ 1080p   │ < 0.5s   │
  │ Telea 修補（RGB + Depth）     │ 1080p   │ < 1.0s   │
  │ 反投影 + 拓樸建立              │ 1080p   │ < 0.5s   │
  └──────────────────────────────┴──────────┴──────────┘

執行方式：
  python tests/benchmark/run_benchmarks.py
  python tests/benchmark/run_benchmarks.py --resolution 512   （快速模式）
  python tests/benchmark/run_benchmarks.py --all              （全部三種解析度）

結果輸出：
  - Console 彩色報告（PASS / FAIL / REGRESSION）
  - benchmark_report.json（供 CI 存檔）
"""

from __future__ import annotations
import argparse
import json
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Tuple

import numpy as np

# 確保從專案根目錄可正常 import
ROOT_DIR = Path(__file__).resolve().parent.parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.core.contracts import RGBDFrame, CameraIntrinsics
from src.core.geometry import GeometryProcessor
from src.core.inpainting import TeleaInpainter
from src.core.policies import SobelEdgeDetector


# ---------------------------------------------------------------------------
# 輸出顏色（終端機 ANSI）
# ---------------------------------------------------------------------------

GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


# ---------------------------------------------------------------------------
# 資料結構
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkResult:
    name:        str
    resolution:  str
    elapsed_sec: float
    threshold:   float
    regression_threshold: float   # = threshold * 0.8
    status:      str              # "PASS" / "FAIL" / "REGRESSION"
    note:        str = ""

    @classmethod
    def evaluate(cls, name: str, resolution: str, elapsed: float, threshold: float) -> "BenchmarkResult":
        regression = threshold * 0.8
        if elapsed < regression:
            status = "REGRESSION"   # 低於 80% 門檻（效能比預期差）
        elif elapsed <= threshold:
            status = "PASS"
        else:
            status = "FAIL"
        return cls(
            name=name,
            resolution=resolution,
            elapsed_sec=round(elapsed, 4),
            threshold=threshold,
            regression_threshold=round(regression, 4),
            status=status,
        )


# ---------------------------------------------------------------------------
# 合成測試資料生成
# ---------------------------------------------------------------------------

def make_synthetic_frame(width: int, height: int) -> RGBDFrame:
    """
    生成具有真實感的合成 RGB-D 幀：
      - color：隨機雜訊（模擬真實紋理）
      - depth：梯度深度圖（帶有斷崖，模擬真實場景）
    """
    rng = np.random.default_rng(seed=42)

    color = rng.integers(0, 255, (height, width, 3), dtype=np.uint8)

    # 深度：基礎平面 + 中央凸起 + 隨機斷崖
    yy, xx = np.mgrid[0:height, 0:width]
    depth  = (xx / width).astype(np.float32) * 0.5 + 0.1
    # 模擬中央物件（近景）
    cy, cx = height // 2, width // 2
    dist   = np.sqrt(((yy - cy) / height) ** 2 + ((xx - cx) / width) ** 2)
    depth  += (0.4 * np.exp(-dist * 8)).astype(np.float32)

    return RGBDFrame(color=color, depth=depth)


def make_intrinsics(width: int, height: int) -> CameraIntrinsics:
    """估算相機內參（FOV 60°，光心居中）。"""
    fx = fy = width / (2.0 * np.tan(np.radians(30.0)))
    return CameraIntrinsics(fx=fx, fy=fy, cx=width / 2.0, cy=height / 2.0,
                            width=width, height=height)


# ---------------------------------------------------------------------------
# 各項基準測試函式
# ---------------------------------------------------------------------------

def bench_edge_detection(frame: RGBDFrame, repeat: int = 3) -> float:
    """斷邊偵測（SobelEdgeDetector.compute_mask）平均耗時。"""
    policy = SobelEdgeDetector(percentile=95.0)
    # 預熱
    policy.compute_mask(frame.depth)
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        policy.compute_mask(frame.depth)
        times.append(time.perf_counter() - t0)
    return float(np.median(times))


def bench_unproject(geo: GeometryProcessor, frame: RGBDFrame, repeat: int = 3) -> float:
    """反投影（unproject_to_points）平均耗時。"""
    # 預熱
    geo.unproject_to_points(frame.depth)
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        geo.unproject_to_points(frame.depth)
        times.append(time.perf_counter() - t0)
    return float(np.median(times))


def bench_topology(geo: GeometryProcessor, points: np.ndarray, frame: RGBDFrame, repeat: int = 3) -> float:
    """拓樸建立（build_topology）平均耗時。"""
    frame.mask = SobelEdgeDetector(percentile=95.0).compute_mask(frame.depth)
    # 預熱
    geo.build_topology(points, frame)
    times = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        geo.build_topology(points, frame)
        times.append(time.perf_counter() - t0)
    return float(np.median(times))


def bench_geometry_full(geo: GeometryProcessor, frame: RGBDFrame, repeat: int = 3) -> float:
    """完整幾何預處理（斷邊偵測 + 反投影 + 拓樸）端到端耗時。"""
    policy = SobelEdgeDetector(percentile=95.0)
    times  = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        frame.mask = policy.compute_mask(frame.depth)
        pts  = geo.unproject_to_points(frame.depth)
        geo.build_topology(pts, frame)
        times.append(time.perf_counter() - t0)
    return float(np.median(times))


def bench_telea(frame: RGBDFrame, repeat: int = 3) -> float:
    """Telea 修補（RGB + Depth 雙重修補）平均耗時。"""
    # 製造真實感的破洞遮罩（5% 像素）
    h, w   = frame.depth.shape
    rng    = np.random.default_rng(seed=0)
    mask   = rng.random((h, w)).astype(np.float32) < 0.05
    masked = RGBDFrame(color=frame.color, depth=frame.depth, mask=mask.astype(np.bool_))

    inpainter = TeleaInpainter(inpaint_radius=3)
    # 預熱
    inpainter.fill(masked)
    times = []
    for _ in range(repeat):
        test_frame = RGBDFrame(color=frame.color.copy(), depth=frame.depth.copy(), mask=mask.astype(np.bool_))
        t0 = time.perf_counter()
        inpainter.fill(test_frame)
        times.append(time.perf_counter() - t0)
    return float(np.median(times))


# ---------------------------------------------------------------------------
# 主執行邏輯
# ---------------------------------------------------------------------------

RESOLUTIONS: Dict[str, Tuple[int, int]] = {
    "512":  (512,  512),
    "1024": (1024, 1024),
    "1080": (1920, 1080),
}

# SLA 門檻（秒）
SLA: Dict[str, float] = {
    "geometry_full": 0.5,
    "telea_inpaint":  1.0,
    "edge_detection": 0.2,
    "unproject":      0.2,
    "topology":       0.3,
}


def run_suite(resolution_key: str) -> List[BenchmarkResult]:
    """執行指定解析度的完整基準測試套件。"""
    w, h = RESOLUTIONS[resolution_key]
    label = f"{w}×{h}"
    print(f"\n{CYAN}{BOLD}▶ 解析度：{label}{RESET}")

    frame      = make_synthetic_frame(w, h)
    intrinsics = make_intrinsics(w, h)
    geo        = GeometryProcessor(intrinsics, SobelEdgeDetector(percentile=95.0))

    results: List[BenchmarkResult] = []

    # 1. 完整幾何預處理
    _run_and_record(results, "geometry_full",  label,
                    lambda: bench_geometry_full(geo, make_synthetic_frame(w, h)))

    # 2. 斷邊偵測
    _run_and_record(results, "edge_detection", label,
                    lambda: bench_edge_detection(frame))

    # 3. 反投影
    _run_and_record(results, "unproject",      label,
                    lambda: bench_unproject(geo, frame))

    # 4. 拓樸建立
    pts = geo.unproject_to_points(frame.depth)
    _run_and_record(results, "topology",       label,
                    lambda: bench_topology(geo, pts, make_synthetic_frame(w, h)))

    # 5. Telea 修補
    _run_and_record(results, "telea_inpaint",  label,
                    lambda: bench_telea(make_synthetic_frame(w, h)))

    return results


def _run_and_record(
    results: List[BenchmarkResult],
    name: str,
    label: str,
    fn
) -> None:
    """執行單項測試、記錄結果並即時列印。"""
    threshold = SLA.get(name, 1.0)
    try:
        elapsed = fn()
        result  = BenchmarkResult.evaluate(name, label, elapsed, threshold)
    except Exception as e:
        result = BenchmarkResult(
            name=name, resolution=label, elapsed_sec=-1.0,
            threshold=threshold, regression_threshold=threshold * 0.8,
            status="FAIL", note=str(e)
        )

    _print_result(result)
    results.append(result)


def _print_result(r: BenchmarkResult):
    color = {"PASS": GREEN, "FAIL": RED, "REGRESSION": YELLOW}.get(r.status, RESET)
    icon  = {"PASS": "✅", "FAIL": "❌", "REGRESSION": "⚠️ "}.get(r.status, "？")
    note  = f"  ({r.note})" if r.note else ""
    print(
        f"  {icon} {color}{r.status:<12}{RESET}"
        f"  {r.name:<20}"
        f"  {r.elapsed_sec:>7.4f}s  "
        f"(threshold: {r.threshold}s){note}"
    )


def save_report(all_results: List[BenchmarkResult], path: str = "benchmark_report.json"):
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "results": [asdict(r) for r in all_results],
        "summary": {
            "total": len(all_results),
            "pass":       sum(1 for r in all_results if r.status == "PASS"),
            "fail":       sum(1 for r in all_results if r.status == "FAIL"),
            "regression": sum(1 for r in all_results if r.status == "REGRESSION"),
        }
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\n📄 報告已存至：{path}")


def print_summary(all_results: List[BenchmarkResult]):
    total      = len(all_results)
    n_pass     = sum(1 for r in all_results if r.status == "PASS")
    n_fail     = sum(1 for r in all_results if r.status == "FAIL")
    n_reg      = sum(1 for r in all_results if r.status == "REGRESSION")

    print(f"\n{BOLD}{'─'*60}{RESET}")
    print(f"{BOLD}基準測試摘要{RESET}")
    print(f"  總計：{total}  {GREEN}PASS: {n_pass}{RESET}  {RED}FAIL: {n_fail}{RESET}  {YELLOW}REGRESSION: {n_reg}{RESET}")

    if n_fail > 0:
        print(f"\n{RED}{BOLD}⚠️  有 {n_fail} 項指標低於 SLA 門檻，請檢視 PSM 中的迴圈或記憶體映射實作。{RESET}")
    if n_reg > 0:
        print(f"\n{YELLOW}{BOLD}ℹ️  有 {n_reg} 項指標低於門檻 80%（PERFORMANCE_REGRESSION），建議追蹤。{RESET}")
    if n_fail == 0 and n_reg == 0:
        print(f"\n{GREEN}{BOLD}🎉 所有指標通過 SLA 驗證！{RESET}")

    print(f"{BOLD}{'─'*60}{RESET}")


def main():
    parser = argparse.ArgumentParser(description="3D Synthesis Engine 效能基準測試")
    parser.add_argument("--resolution", choices=["512", "1024", "1080"],
                        default="1080", help="測試解析度（預設 1080p）")
    parser.add_argument("--all", action="store_true",
                        help="執行全部三種解析度")
    parser.add_argument("--output", default="benchmark_report.json",
                        help="報告輸出路徑（預設 benchmark_report.json）")
    args = parser.parse_args()

    print(f"{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}  3D Photo Synthesis Engine — 效能基準測試{RESET}")
    print(f"{BOLD}{'='*60}{RESET}")

    if args.all:
        keys = ["512", "1024", "1080"]
    else:
        keys = [args.resolution]

    all_results: List[BenchmarkResult] = []
    for key in keys:
        all_results.extend(run_suite(key))

    print_summary(all_results)
    save_report(all_results, args.output)

    # CI 用：有 FAIL 則以非零退出碼終止
    has_fail = any(r.status == "FAIL" for r in all_results)
    sys.exit(1 if has_fail else 0)


if __name__ == "__main__":
    main()
