"""
MeshData → glTF (.glb) 匯出 (glTF Exporter)
=============================================
將平台無關的 MeshData 序列化為自包含的二進位 glTF（.glb），
供前端 Three.js GLTFLoader 直接載入。

選用 .glb 而非 JSON 的理由：
  - 二進位 buffer 緊湊（位置/索引/顏色/法線皆為原生 typed array），
    傳輸量遠小於 JSON 數字陣列，且 Three.js 原生支援、零額外解析。
  - 單一檔案、無外部依賴，方便快取與 CDN 部署。

僅依賴標準庫 struct/json + numpy，不需任何 glTF 套件。
"""

from __future__ import annotations

import json
import struct

import numpy as np

from src.core.contracts import MeshData

# glTF 常數
_FLOAT = 5126
_UNSIGNED_INT = 5125
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
_TRIANGLES = 4


def _pad4(b: bytes, pad_byte: bytes = b"\x00") -> bytes:
    """將位元組補齊到 4 bytes 對齊（glTF 規範要求）。"""
    rem = len(b) % 4
    return b if rem == 0 else b + pad_byte * (4 - rem)


def mesh_to_glb(mesh: MeshData) -> bytes:
    """
    將 MeshData 編碼為 .glb 二進位（glTF 2.0）。

    包含：
      - POSITION（頂點，float32 ×3）
      - COLOR_0（頂點色，float32 ×3）
      - NORMAL（頂點法線，float32 ×3；若無則略過，由前端計算）
      - indices（三角面，uint32 ×3）
    回傳：完整 .glb 位元組串，可直接作為 HTTP response body。
    """
    positions = np.ascontiguousarray(mesh.vertices, dtype=np.float32)
    indices   = np.ascontiguousarray(mesh.faces.reshape(-1), dtype=np.uint32)
    colors    = np.ascontiguousarray(mesh.colors, dtype=np.float32)
    has_normals = mesh.normals is not None
    if has_normals:
        normals = np.ascontiguousarray(mesh.normals, dtype=np.float32)

    # --- 組裝二進位 buffer：依序放入各 bufferView，記錄 offset/length ---
    chunks = []
    views = []      # (byteOffset, byteLength, target)
    offset = 0

    def add(data: bytes, target: int) -> int:
        nonlocal offset
        view_index = len(views)
        views.append((offset, len(data), target))
        chunks.append(data)
        offset += len(data)
        return view_index

    pos_view = add(positions.tobytes(), _ARRAY_BUFFER)
    col_view = add(colors.tobytes(), _ARRAY_BUFFER)
    nrm_view = add(normals.tobytes(), _ARRAY_BUFFER) if has_normals else None
    idx_view = add(indices.tobytes(), _ELEMENT_ARRAY_BUFFER)

    bin_blob = _pad4(b"".join(chunks))

    # --- accessors（描述每個 bufferView 的型別與範圍）---
    pos_min = positions.min(axis=0).tolist()
    pos_max = positions.max(axis=0).tolist()

    accessors = [
        {  # 0: POSITION
            "bufferView": pos_view, "componentType": _FLOAT,
            "count": int(positions.shape[0]), "type": "VEC3",
            "min": pos_min, "max": pos_max,
        },
        {  # 1: COLOR_0
            "bufferView": col_view, "componentType": _FLOAT,
            "count": int(colors.shape[0]), "type": "VEC3",
        },
    ]
    attributes = {"POSITION": 0, "COLOR_0": 1}

    if has_normals:
        accessors.append({  # NORMAL
            "bufferView": nrm_view, "componentType": _FLOAT,
            "count": int(normals.shape[0]), "type": "VEC3",
        })
        attributes["NORMAL"] = len(accessors) - 1

    idx_accessor = len(accessors)
    accessors.append({  # indices
        "bufferView": idx_view, "componentType": _UNSIGNED_INT,
        "count": int(indices.shape[0]), "type": "SCALAR",
    })

    buffer_views = [
        {"buffer": 0, "byteOffset": o, "byteLength": l, "target": t}
        for (o, l, t) in views
    ]

    gltf = {
        "asset": {"version": "2.0", "generator": "3D-Photo-Synthesis-Engine"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{
            "primitives": [{
                "attributes": attributes,
                "indices": idx_accessor,
                "mode": _TRIANGLES,
            }]
        }],
        "buffers": [{"byteLength": len(bin_blob)}],
        "bufferViews": buffer_views,
        "accessors": accessors,
    }

    json_blob = _pad4(json.dumps(gltf, separators=(",", ":")).encode("utf-8"), b" ")

    # --- GLB 容器：header + JSON chunk + BIN chunk ---
    def chunk(data: bytes, ctype: int) -> bytes:
        return struct.pack("<II", len(data), ctype) + data

    json_chunk = chunk(json_blob, 0x4E4F534A)   # "JSON"
    bin_chunk  = chunk(bin_blob, 0x004E4942)     # "BIN\0"
    total_len = 12 + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", 0x46546C67, 2, total_len)  # "glTF", version 2

    return header + json_chunk + bin_chunk
