"""
階層二整合測試：FastAPI 後端 /synthesize 端點
(test_backend_api.py)
================================================
驗證：
  - 健康檢查端點正常
  - 上傳合成 RGB + Depth → 回傳合法 .glb（magic、版本、含網格）
  - 缺少欄位 / 壞影像 → 適當錯誤碼
  - depth_far <= depth_near → 422
"""

import base64
import io
import struct

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)


def _png_bytes(img: np.ndarray) -> bytes:
    """將 ndarray 編碼為 PNG bytes。"""
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


@pytest.fixture
def rgb_png() -> bytes:
    img = (np.random.rand(48, 48, 3) * 255).astype(np.uint8)
    return _png_bytes(img)


@pytest.fixture
def depth_png() -> bytes:
    # 前景近 / 背景遠，製造深度斷崖（16-bit 深度）
    d = np.full((48, 48), 50000, dtype=np.uint16)
    d[16:32, 16:32] = 5000
    return _png_bytes(d)


class TestHealth:
    def test_root_ok(self):
        r = client.get("/")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"


class TestSynthesize:

    def test_returns_valid_glb(self, rgb_png, depth_png):
        r = client.post(
            "/synthesize",
            files={
                "rgb":   ("rgb.png", rgb_png, "image/png"),
                "depth": ("depth.png", depth_png, "image/png"),
            },
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "model/gltf-binary"

        glb = r.content
        # GLB header: magic "glTF", version 2, total length
        magic, version, length = struct.unpack("<III", glb[:12])
        assert magic == 0x46546C67, "GLB magic 不正確"
        assert version == 2
        assert length == len(glb), "GLB 宣告長度應等於實際長度"

        # 網格非空
        assert int(r.headers["X-Vertex-Count"]) == 48 * 48
        assert int(r.headers["X-Face-Count"]) > 0

    def test_tearing_reduces_faces(self, rgb_png, depth_png):
        """有深度斷崖時，面數應少於完整網格（撕裂生效）。"""
        r = client.post(
            "/synthesize",
            files={
                "rgb":   ("rgb.png", rgb_png, "image/png"),
                "depth": ("depth.png", depth_png, "image/png"),
            },
        )
        full = (48 - 1) * (48 - 1) * 2
        assert int(r.headers["X-Face-Count"]) < full

    def test_missing_depth_returns_422(self, rgb_png):
        r = client.post(
            "/synthesize",
            files={"rgb": ("rgb.png", rgb_png, "image/png")},
        )
        assert r.status_code == 422

    def test_corrupt_image_returns_422(self):
        r = client.post(
            "/synthesize",
            files={
                "rgb":   ("rgb.png", b"not-an-image", "image/png"),
                "depth": ("depth.png", b"also-garbage", "image/png"),
            },
        )
        assert r.status_code == 422

    def test_invalid_depth_range_returns_422(self, rgb_png, depth_png):
        r = client.post(
            "/synthesize?depth_near=5.0&depth_far=2.0",
            files={
                "rgb":   ("rgb.png", rgb_png, "image/png"),
                "depth": ("depth.png", depth_png, "image/png"),
            },
        )
        assert r.status_code == 422


class TestParallax:
    """輕量視差端點：回 RGB + 正規化 depth 兩張 base64 PNG，不產 mesh。"""

    def test_returns_two_images(self, rgb_png, depth_png):
        r = client.post(
            "/parallax",
            files={
                "rgb":   ("rgb.png", rgb_png, "image/png"),
                "depth": ("depth.png", depth_png, "image/png"),
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["width"] == 48 and body["height"] == 48
        assert body["rgb"].startswith("data:image/png;base64,")
        assert body["depth"].startswith("data:image/png;base64,")

    def test_depth_is_grayscale_normalized(self, rgb_png, depth_png):
        """回傳 depth 應為單通道、值域涵蓋近~遠（正規化後對比明顯）。"""
        r = client.post(
            "/parallax",
            files={
                "rgb":   ("rgb.png", rgb_png, "image/png"),
                "depth": ("depth.png", depth_png, "image/png"),
            },
        )
        b64 = r.json()["depth"].split(",", 1)[1]
        raw = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        img = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
        assert img.ndim == 2, "depth 應為單通道灰階"
        assert int(img.max()) - int(img.min()) > 50, "正規化後應有明顯深度對比"

    def test_missing_depth_without_estimator_returns_422(self, rgb_png):
        """無 depth 且估算器未啟用（預設 NoOp）→ 422。"""
        r = client.post(
            "/parallax",
            files={"rgb": ("rgb.png", rgb_png, "image/png")},
        )
        assert r.status_code == 422

    def test_missing_depth_with_estimator_succeeds(self, rgb_png):
        """注入估算器後，僅 RGB 也能取得 depth（驗可插拔接口）。"""
        from backend.depth_estimator import (
            DepthEstimator,
            set_depth_estimator,
            NoOpDepthEstimator,
        )

        class _DummyEstimator(DepthEstimator):
            def estimate(self, rgb):
                h, w = rgb.shape[:2]
                # 簡單漸層當佔位深度
                return np.linspace(0, 1, w, dtype=np.float32)[None, :].repeat(h, 0)

        set_depth_estimator(_DummyEstimator())
        try:
            r = client.post(
                "/parallax",
                files={"rgb": ("rgb.png", rgb_png, "image/png")},
            )
            assert r.status_code == 200, r.text
            assert r.json()["depth"].startswith("data:image/png;base64,")
        finally:
            set_depth_estimator(NoOpDepthEstimator())


class TestLDI:
    """LDI 分層補洞端點：回多層 RGBA+depth（base64 PNG），不產 mesh。"""

    def test_returns_layers(self, rgb_png, depth_png):
        r = client.post(
            "/ldi?num_layers=2",
            files={
                "rgb":   ("rgb.png", rgb_png, "image/png"),
                "depth": ("depth.png", depth_png, "image/png"),
            },
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["width"] == 48 and body["height"] == 48
        assert body["num_layers"] == len(body["layers"]) >= 2
        for layer in body["layers"]:
            assert layer["color"].startswith("data:image/png;base64,")
            assert layer["depth"].startswith("data:image/png;base64,")
            assert layer["alpha"].startswith("data:image/png;base64,")
            assert 0.0 <= layer["depth_min"] <= layer["depth_max"] <= 1.0 + 1e-6

    def test_background_layer_alpha_opaque(self, rgb_png, depth_png):
        """最遠背景底層 alpha 應全不透明（任何視差量不露黑洞）。"""
        r = client.post(
            "/ldi?num_layers=2",
            files={
                "rgb":   ("rgb.png", rgb_png, "image/png"),
                "depth": ("depth.png", depth_png, "image/png"),
            },
        )
        b64 = r.json()["layers"][-1]["alpha"].split(",", 1)[1]
        raw = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
        alpha = cv2.imdecode(raw, cv2.IMREAD_UNCHANGED)
        assert alpha.ndim == 2
        assert int(alpha.min()) == 255, "背景底層應全不透明"

    def test_three_layers(self, rgb_png, depth_png):
        r = client.post(
            "/ldi?num_layers=3",
            files={
                "rgb":   ("rgb.png", rgb_png, "image/png"),
                "depth": ("depth.png", depth_png, "image/png"),
            },
        )
        assert r.status_code == 200, r.text
        assert r.json()["num_layers"] >= 2

    def test_missing_depth_without_estimator_returns_422(self, rgb_png):
        """無 depth 且估算器未啟用（預設 NoOp）→ 422（CI 無 torch 也綠）。"""
        r = client.post(
            "/ldi",
            files={"rgb": ("rgb.png", rgb_png, "image/png")},
        )
        assert r.status_code == 422

    def test_corrupt_image_returns_422(self):
        r = client.post(
            "/ldi",
            files={
                "rgb":   ("rgb.png", b"not-an-image", "image/png"),
                "depth": ("depth.png", b"garbage", "image/png"),
            },
        )
        assert r.status_code == 422
