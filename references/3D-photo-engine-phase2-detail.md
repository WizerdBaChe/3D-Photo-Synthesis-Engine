# Phase 2 詳細設計紀錄 — 診斷可觀測性 + 3D 邊長剔除 + 受限視差相機

## 為什麼需要這個 Phase

Step 1 修完後實機：正面乾淨，但一拖到側面就大量放射狀長條。當時無法判斷成因
（斷崖閾值？修補斜坡？2.5D 本質？），因為**管線沒有任何中間產物可檢查**——
這是本 Phase 的第一個動作：先建可觀測性，再談修。

## 診斷工具 scripts/inspect_pipeline.py

- 獨立 CLI，吃 RGB/depth 檔，重用 backend/src.core 元件（不複製管線），把
  Orchestrator.process 的步驟攤開以擷取中間張量。**刻意不在 /synthesize 加
  debug 分支**——最小資源、與請求路徑解耦、可離線直接跑。
- Dump：01 正規化深度、02 斷崖遮罩疊圖（紅）、03 修補後深度、04 mesh 統計
  （頂點/面數 + 3D 邊長 p50/p90/p95/p99/p99.9 + max + 直方圖）。
- 支援 --max-edge-ratio 以比較剔除前後。

## 放射線根因（量出來的結論）

對房間圖（935×534，auto 判定 metric，正確）：

| 指標 | 值 | 意義 |
|---|---|---|
| 斷崖遮罩覆蓋 | 0.16%（780 px） | 幾乎全漏——平滑 ML depth 無銳利斷崖，只有緩坡 |
| 邊長 p50 | 0.0061 | 主體尺度 |
| 邊長 p99 | 0.0915（15×median） | 主體仍緊密 |
| 邊長 max | 3.53（**577×median**） | 放射線：被拉成長條的三角形 |
| 直方圖 | 2.97M 在最小 bin、~3500 散在長尾 | 雙峰：主體 + 放射線長尾 |

**結論**：斷崖遮罩（相鄰像素深度差）在平滑 ML depth 上已到天花板——真正的
前/背景落差被修補糊成跨多像素緩坡，每像素差 < 門檻，切不到。放射線本質是
「深度落差沿光心射線拉伸的三角形」，其 3D 邊長遠大於主體，是與視角無關的
量化指紋。

## 解法：3D 邊長剔除（geometry.py）

- GeometryProcessor 加 max_edge_ratio（None=關，預設）。build_topology 在組面後、
  算法線前，加 Step 5b：_cull_long_edge_faces。
- 演算法：每面三邊 3D 長度 → 取全體邊長中位數為基準（對長尾離群穩健）→
  任一邊 > max_edge_ratio × median 即剔除該面。全向量化。
- 為何用中位數而非平均：放射線本身是離群，平均會被拉高、門檻失準；中位數穩健。

### 門檻校準（房間圖實測）

| k | 面數 | 剔除 | max/median 後 |
|---|---|---|---|
| off | 992,632 | — | 576.9× |
| 50 | 990,942 | 0.17% | 50× |
| 30 | 987,695 | 0.50% | 30× |
| 15 | 976,756 | 1.6% | 15× |

選 30：落在直方圖空隙、max→0.18、只砍 0.5%、p50/p99 主體不動。API 預設 30。
風險：對深度尺度/構圖差異大的圖未必普適；過低會在真實深邊界留洞——需更多
樣本驗證（已列 TODO）。

## 受限視差相機（viewer.ts）

- 移除 OrbitControls（繞球 = Google Earth 感，且直視 2.5D 側面露餡）。
- 改「滑鼠位置驅動視差」：相機固定影像正前方中央、lookAt(center)；pointermove
  把游標正規化 [-1,1] → 相機 X/Y 小幅平移 + lookAt 反向小偏移（tilt）。
- pointerleave / 無輸入 → pointer 歸零，smoothed.lerp(damping=0.08) 平滑滑回正面。
- 幅度依 frameObject 的 maxDim 自適應：panAmount=maxDim*0.06、tiltOffset=maxDim*0.04、
  maxTiltDeg≈6。確保不同尺寸照片視差一致、且不會繞到看見側面破洞。
- 可調點：panAmount / maxTiltDeg（手感強弱）。

## 驗證

- pytest 63 passed（原 60 + TestEdgeLengthCulling 3 個：預設關不影響、開啟剔除拉伸面、均勻 mesh 不誤刪）。
- 前端 tsc && vite build 通過（OrbitControls 移除無殘留 import）。
- 端到端 TestClient /synthesize（預設 k=30）：200、987,695 面、29.8 MB .glb。

## 與 Step 1 的關係 / 留給 Step 4

- near/far 仍只影響 DIBR mapping、depth 仍 normalize [0,1]（Step 1 假設不變）。
- inspect_pipeline 的邊長分布可顯化 near/far 對拉伸的影響，作為 Step 4（視差強度
  系統性收斂）的量化依據。
