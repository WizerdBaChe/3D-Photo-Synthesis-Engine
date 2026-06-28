"""
FastAPI 應用 (Web 後端進入點)
================================
端點：
  GET  /            → 健康檢查
  POST /synthesize  → 上傳 RGB + Depth，回傳 .glb 3D 網格

啟動：
  uvicorn backend.app:app --reload          （開發）
  uvicorn backend.app:app --host 0.0.0.0 --port 8000  （部署）

架構：
  瀏覽器上傳 RGB-D → 此後端跑純 NumPy 合成管線 → 回傳 .glb →
  前端 Three.js 載入並在 WebGL 即時互動旋轉（渲染全在客戶端）。
  後端無狀態、無 GUI、無 Open3D、無子進程，可水平擴展與容器化部署。
"""

from __future__ import annotations

import base64
import io
import logging

import cv2
import numpy as np
from fastapi import FastAPI, File, HTTPException, UploadFile, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from src.core.policies import SobelEdgeDetector, DepthDiscontinuityPolicy
from src.core.geometry import GeometryProcessor
from src.core.inpainting import TeleaInpainter, DepthAwareInpainter
from src.app.orchestrator import Orchestrator

from backend.rgbd_loader import (
    load_rgbd_from_bytes,
    estimate_intrinsics,
    decode_image,
    normalize_depth_semantics,
)
from backend.depth_estimator import get_depth_estimator, DepthEstimatorUnavailable
from backend.gltf_export import mesh_to_glb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backend")

app = FastAPI(
    title="3D Photo Synthesis Engine",
    description="將 RGB + 深度圖合成為可互動的 3D 照片（如 Facebook 3D Photo）。",
    version="2.0",
)

# 開發階段允許前端 (Vite dev server) 跨來源呼叫。
# 部署時應將 allow_origins 收斂為實際前端網域。
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def health() -> dict:
    """健康檢查與服務資訊。"""
    return {"status": "ok", "service": "3D Photo Synthesis Engine", "version": "2.0"}


@app.post("/synthesize")
async def synthesize(
    rgb:   UploadFile = File(..., description="RGB 彩色圖（PNG/JPG）"),
    depth: UploadFile = File(..., description="深度圖（PNG 8/16bit、TIFF）"),
    percentile:  float = Query(95.0, ge=0.0, le=100.0, description="legacy Sobel 斷邊百分位閾值"),
    fov_deg:     float = Query(60.0, gt=0.0, lt=180.0, description="水平 FOV（度）"),
    depth_near:  float = Query(1.0, gt=0.0, description="近平面 Z（視差強度）"),
    depth_far:   float = Query(4.0, gt=0.0, description="遠平面 Z（視差強度）"),
    max_pixels:  int   = Query(500_000, ge=0, description="網格頂點上限（H×W），0=停用限制"),
    depth_convention: str = Query("auto", description="深度語意：auto|disparity|metric"),
    edge_policy: str   = Query("discontinuity", description="斷崖策略：discontinuity（預設）|sobel（legacy）"),
    max_edge_ratio: float = Query(30.0, gt=0.0, description="3D 邊長剔除門檻（×中位邊長），剔除放射狀拉伸面；設大值可實質關閉"),
):
    """
    合成端點：上傳 RGB + Depth，回傳 .glb 3D 網格。

    流程：解碼 → 估算內參 → 邊緣偵測 → 雙重修補 → 反投影建面 → glTF 序列化。
    """
    if depth_far <= depth_near:
        raise HTTPException(422, "depth_far 必須大於 depth_near。")

    try:
        rgb_bytes   = await rgb.read()
        depth_bytes = await depth.read()
        frame = load_rgbd_from_bytes(
            rgb_bytes, depth_bytes, max_pixels=max_pixels,
            depth_convention=depth_convention,
        )
        h, w = frame.color.shape[:2]
        logger.info(f"影像載入完成：{w}×{h}（max_pixels={max_pixels}, depth_convention={depth_convention}）")
    except ValueError as e:
        raise HTTPException(422, f"影像載入失敗：{e}")

    intrinsics = estimate_intrinsics(
        frame, fov_deg=fov_deg, depth_near=depth_near, depth_far=depth_far
    )
    # 斷崖策略：預設 DepthDiscontinuityPolicy（絕對深度差為主），legacy Sobel 可選回。
    if edge_policy == "sobel":
        policy = SobelEdgeDetector(percentile=percentile)
    else:
        policy = DepthDiscontinuityPolicy()
    geo = GeometryProcessor(intrinsics, policy, max_edge_ratio=max_edge_ratio)
    telea = TeleaInpainter(inpaint_radius=3)
    orch = Orchestrator(
        geo_processor=geo,
        # Phase 4 C1：DIBR depth-aware 為主修補器（只取背景、排前景，純 CPU）。
        primary_inpainter=DepthAwareInpainter(),
        fallback_inpainter=telea,   # 降級備案（DepthAware 不會拋 OOM，僅為架構一致保留）
    )

    try:
        mesh = orch.process(frame)
    except Exception as e:
        logger.exception("合成管線發生錯誤")
        raise HTTPException(500, f"合成失敗：{e}")

    glb = mesh_to_glb(mesh)
    logger.info(f"合成完成：{mesh.vertex_count} 頂點 / {mesh.face_count} 面 / {len(glb)} bytes")

    return StreamingResponse(
        io.BytesIO(glb),
        media_type="model/gltf-binary",
        headers={
            "Content-Disposition": 'inline; filename="photo3d.glb"',
            "X-Vertex-Count": str(mesh.vertex_count),
            "X-Face-Count": str(mesh.face_count),
        },
    )


def _png_data_url(img_bgr_or_gray: np.ndarray) -> str:
    """將 ndarray 編成 PNG 並包成 base64 data URL（供前端 <img>/Texture 直接使用）。"""
    ok, buf = cv2.imencode(".png", img_bgr_or_gray)
    if not ok:
        raise HTTPException(500, "影像編碼失敗。")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:image/png;base64,{b64}"


@app.post("/parallax")
async def parallax(
    rgb:   UploadFile = File(..., description="RGB 彩色圖（PNG/JPG）"),
    depth: UploadFile | None = File(None, description="深度圖（選填；缺少時嘗試自動估算）"),
    max_pixels: int   = Query(2_000_000, ge=0, description="影像像素上限，0=停用限制"),
    depth_convention: str = Query("auto", description="深度語意：auto|disparity|metric"),
):
    """
    輕量視差端點：回傳 RGB + 正規化深度兩張圖（base64 PNG），供前端在
    fragment shader 做 UV 位移視差（Facebook 3D Photo 式）。**不產生 mesh/.glb**。

    depth 選填：缺少時呼叫可插拔 DepthEstimator（預設未啟用 → 422）。
    回傳 JSON：{ width, height, rgb, depth }（rgb/depth 為 data:image/png;base64 URL）。
    """
    rgb_bytes = await rgb.read()
    try:
        color_bgr = decode_image(rgb_bytes, cv2.IMREAD_COLOR)
    except ValueError as e:
        raise HTTPException(422, f"RGB 載入失敗：{e}")

    h_rgb, w_rgb = color_bgr.shape[:2]

    # 取得正規化深度 [0,1]（值大=遠）：有上傳走 loader，缺少走估算器。
    if depth is not None:
        depth_bytes = await depth.read()
        try:
            depth_raw = decode_image(
                depth_bytes, cv2.IMREAD_ANYDEPTH | cv2.IMREAD_GRAYSCALE
            )
        except ValueError as e:
            raise HTTPException(422, f"深度載入失敗：{e}")
        depth_f32 = depth_raw.astype(np.float32)
        max_val = float(depth_f32.max())
        if max_val > 1.0:
            depth_f32 /= max_val
        depth_f32 = normalize_depth_semantics(depth_f32, depth_convention)
        if (depth_f32.shape[0], depth_f32.shape[1]) != (h_rgb, w_rgb):
            depth_f32 = cv2.resize(
                depth_f32, (w_rgb, h_rgb), interpolation=cv2.INTER_LINEAR
            )
    else:
        try:
            # 估算器約定回 [0,1]、值大=遠，與 loader 輸出語意一致。
            color_rgb = cv2.cvtColor(color_bgr, cv2.COLOR_BGR2RGB)
            depth_f32 = get_depth_estimator().estimate(color_rgb).astype(np.float32)
        except DepthEstimatorUnavailable as e:
            raise HTTPException(422, str(e))
        if (depth_f32.shape[0], depth_f32.shape[1]) != (h_rgb, w_rgb):
            depth_f32 = cv2.resize(
                depth_f32, (w_rgb, h_rgb), interpolation=cv2.INTER_LINEAR
            )

    # 降採樣：超過 max_pixels 時等比例縮圖（與 loader 一致的策略）。
    if max_pixels > 0 and (h_rgb * w_rgb) > max_pixels:
        scale = (max_pixels / (h_rgb * w_rgb)) ** 0.5
        new_w = max(1, int(w_rgb * scale))
        new_h = max(1, int(h_rgb * scale))
        color_bgr = cv2.resize(color_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        depth_f32 = cv2.resize(depth_f32, (new_w, new_h), interpolation=cv2.INTER_LINEAR)

    out_h, out_w = color_bgr.shape[:2]
    depth_u8 = np.clip(depth_f32 * 255.0, 0, 255).astype(np.uint8)

    logger.info(f"視差資料完成：{out_w}×{out_h}（depth={'上傳' if depth else '估算'}）")
    return {
        "width": out_w,
        "height": out_h,
        "rgb": _png_data_url(color_bgr),
        "depth": _png_data_url(depth_u8),
    }
