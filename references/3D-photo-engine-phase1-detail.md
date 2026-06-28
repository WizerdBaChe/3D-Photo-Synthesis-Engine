# Phase 1 詳細設計紀錄 — 後端 depth 語意 + 座標系 + 斷崖遮罩

## 問題根因分析（原始四現象）

| 現象 | 根因 | 位置 |
|---|---|---|
| ①③ 放射狀線條 + 缺漏 | Sobel 相對閾值切錯 + linear resize 造邊界斜坡 + 反投影把斷崖拉成射線 | policies.py, rgbd_loader.py, geometry.py |
| ② 人像浮雕凸出 | 2.5D 物理限制 + near/far 當物理尺度而非視差強度 | contracts.py, geometry.py |
| ④ 旋轉像 Google Earth / 三軸怪 | OrbitControls 繞球 + mesh +Y 朝下與世界座標相反 | viewer.ts, geometry.py |

## Bug A：depth 語意

- **disparity**（ML 模型慣例：MiDaS/Depth-Anything）：近=亮（值大），遠=暗
- **metric**（線性物理深度）：近=暗（值小），遠=亮
- 原始 pipeline 完全不區分，統一套 `Z = near + d*(far-near)` → disparity 輸入會深度反轉

### auto 啟發式邏輯
```
mean = depth01.mean()
median = median(depth01)
skew_hint = mean - median          # >0 → right-skewed（少數亮近物拉高平均）
high_frac = (depth01 > 0.7).mean() # 高值（近物）像素佔比
is_disparity = (skew_hint > 0.0) and (high_frac < 0.35)
```
- 右偏（mean>median）+ 高值稀少 → disparity；否則 metric
- 初次校準：房間圖（近暗遠亮，大片亮）→ high_frac 大 → metric ✓
- 一開始寫反（skew<0），測試後修正

### disparity → metric 轉換
```python
inv = 1.0 / (depth01 + 1e-3)   # eps=1e-3 防除零
再正規化回 [0,1]
```

## Bug C：斷崖遮罩失效

- **舊行為**：Orchestrator Phase 1 算 `frame.mask = edge_policy(原始depth)`，build_topology 直接沿用 → mask 是對原始 depth 算的，但建面用修補後 depth，語意錯位
- **Sobel 百分位失效原因**：ML depth 平滑（無真斷崖），`percentile(gradient, 95)` 永遠切「最陡 5%」= 雜訊緩坡，真正的前/背景邊界沒被切

### DepthDiscontinuityPolicy 兩階段設計
```
Stage 1（主）: diff_x = |depth[:,i] - depth[:,i+1]| > abs_diff_ratio * (max-min)
               → 兩側像素都標為候選
Stage 2（輔）: Sobel magnitude >= percentile(candidate_magnitudes, sobel_percentile)
               → 在候選中取更陡者（細化）
```
- `abs_diff_ratio=0.04`（場景深度範圍的 4%）
- `use_sobel_refinement=True`，可設 False 做 quick bisect
- `sobel_percentile=90.0`（只在候選集上取，避免大片平坦壓低門檻）

### 語意分離
- `frame.mask` = 破洞修補遮罩（給 Inpainter 用）
- build_topology 內的斷崖遮罩 = 永遠重算 `edge_policy.compute_mask(repaired_frame.depth)`

## Bug D：座標系

- 原始：Y 朝下（V 向下增長）、Z 朝前（螢幕內）→ 左手系
- glTF 2.0 規範：右手系，+Y 朝上，+Z 朝觀者
- 修正：`Y = -(V-cy)*Z_cam/fy`，`Z = -Z_cam`
- gltf_export 原樣輸出，無需修改

## 測試改動重點

- `test_geometry.py`：Z 期望值全取負；TestBuildTopology 改用 `_ConstMaskPolicy` 注入（build_topology 不再吃 frame.mask）；新增 Y-flip、near-closer-to-viewer、DepthDiscontinuityPolicy 測試集
- `test_rgbd_loader.py`：新建，測三模式 + auto 啟發式

## 實機驗證結果（2026-06-27）

- 正面角度：放射線大幅減少，場景方向正確（天花板上、地板下）
- **殘留問題**：旋轉到側面/大角度時仍出現大量放射狀線條
- 根因尚未分析：可能是 DepthDiscontinuityPolicy 閾值、修補後斜坡、或 2.5D 本質（側面無資料）

## 分支狀態

- 分支：`fix/depth-semantics-coordinate-cliff`（尚未 commit）
- 測試：60 passed
