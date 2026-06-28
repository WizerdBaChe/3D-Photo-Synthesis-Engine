# Phase 3 詳細紀錄 — 架構轉向：深度位移視差著色器

## 為何走錯路（覆盤，刻意保留供未來警惕）

Phase 1/2 花了大量心力在「逐像素反投影 → 1M 面 mesh → 邊長剔除 → 30MB .glb → 前端 GLTF 載入」。
實機後使用者一次點出 5 個問題，全部回到**同一個架構誤判**：

- 我們把「Facebook 3D Photo」理解成「重建真實 3D 幾何」，於是做 pinhole 反投影、斷崖遮罩、
  inpainting、邊長剔除……每一步都在補前一步的洞（放射線 → 斷崖遮罩 → 邊長剔除）。
- 但業界網頁版 FB 3D Photo 的常見實作根本不是 mesh：是**一張平面 quad + depth map 在
  fragment shader 做 UV 位移**（~50 行 shader）。近處位移大、遠處小，造成視差錯覺。
- 教訓：**先做 30 分鐘調研（市面上怎麼做）再決定架構**，比埋頭實作再回頭修划算太多。
  Phase 2 的「先建可觀測性再修」方向對，但對象（mesh 管線）本身就不該是主路徑。

5 點 → 根因對照：

| 使用者回報 | mesh 路徑根因 | 位移著色器為何解掉 |
|---|---|---|
| #2 像美術畫作 | Telea inpainting 把平滑 ML depth 邊界抹成垂直條紋 | 不做 inpainting、像素只平移、邊緣銳利 |
| #3 視點太遠 | mesh 需相機退到能框住 3D box | 正交相機、平面內假視差，無相機距離 |
| #5 前端 10 秒+ | 30MB .glb 下載 + GLTF parse | 1.9MB 兩張 PNG，近即時 |
| #1 跟隨慢/弱 | hover + damping 0.08、幅度小 | 拖曳 + dragScale 2.2 + damping 0.18 |
| #4 有無現成可學 | （無，全手刻） | 採 Codrops / Alan Zucconi 標準做法 |

## 架構：兩者並存

- **預設＝視差**（輕量、快、無 artefact）：前端 `ParallaxViewer`，後端 `/parallax`。
- **進階＝mesh**（可匯出 .glb）：保留 Phase 1/2 全部成果，`viewer.ts` / `/synthesize` /
  反投影管線**零改動**，只是不再是預設。使用者可在 UI 切換。

## 後端

- `/parallax`：吃 RGB + **選填** depth。有 depth → 共用 `load_rgbd_from_bytes` 的正規化
  （值大=遠 metric）；無 depth → 呼叫 `DepthEstimator`（預設 NoOp → 422）。
  回 JSON `{width,height,rgb,depth}`，rgb/depth 為 `data:image/png;base64`。
- `DepthEstimator`（backend/depth_estimator.py）：抽象介面 `estimate(rgb)->[0,1] depth`、
  `NoOpDepthEstimator` 佔位、`get/set_depth_estimator` provider。
  **本次不引入任何模型或依賴**；未來接 MiDaS / Depth-Anything / 外部 API 只需 set 一次，
  端點與前端不動。

## 前端：位移著色器

- `ParallaxViewer`：`OrthographicCamera` + 覆蓋畫面 quad + `ShaderMaterial`。
- fragment 核心：`offset = uMouse * (0.5 - depth) * uIntensity; color = texture2D(uImage, uv + offset)`。
  以 0.5 為中性面：比中性近（往觀者）與比中性遠 反向位移，立體感更強。
- 拖曳互動：pointerdown 記起點 → pointermove 累積位移正規化（dragScale 放大、clamp [-1,1]）
  → pointerup/leave 歸零、damping lerp 回正。
- `contain` 縮放：依視窗與影像長寬比調整正交相機框，照片完整入框不變形。

## 已知限制 / 待修：拖曳殘影（鬼影）

- 現象：拖到較大角度時，近景物件邊緣冒出本不該出現的鄰區內容（房間圖：床面冒出右側櫃子的
  木色）。
- 成因：`texture2D(uImage, uv + offset)` 在**深度劇變處**會把近景像素的取樣座標推進鄰格，
  取到的是隔壁不同深度的像素 → 內容「滲」進來。位移著色器無遮擋（occlusion）資訊，這是其
  固有限制，與 mesh 的「拉伸三角形」是不同機制的同類病（皆因 2.5D 缺背面資料）。
- 修法候選（由輕到重）：
  1. **限制位移幅度上限**（uIntensity / dragScale 上限）→ 鬼影變小，最省。
  2. **邊緣淡出 / clamp**：texture wrap=ClampToEdge（已隱含）、或位移量在影像邊界附近衰減。
  3. **位移量隨深度梯度收斂**：在 depth 梯度大處（物件邊界）降低位移，減少跨界取樣。
  4. （重）位移後 inpaint 露出區，或雙層 quad 視差——非必要不做。
- 本次先做 1+3 的組合（限制幅度 + 依梯度收斂），保持輕量。

## Disocclusion（去遮擋）：業界做法調研與本專案策略

使用者追問「非正面完整圖都會有殘影 / 物件撥離（玻璃、蘆葦後窗、花瓶邊），業界怎麼處理」。
查證結論（含來源）：

- 學名 **disocclusion**：視角一動，原本被前景遮住、原圖根本沒拍到的背景被露出，引擎無資料只能補。
- 三個層級（輕→重）：
  1. **純位移著色器（本路線）**：無遮擋資料，邊界只能拉伸或跨界取樣 → 殘影。緩解 = 邊界衰減 + 限幅。治標。玻璃/半透明最糟（depth 本身不可靠）。
  2. **DIBR depth-aided inpainting**：露出的洞用鄰近**背景**色填，**關鍵是用 depth 區分前/背景、只取背景色、排除前景色**（[Depth-aided inpainting, 2009](https://www.researchgate.net/publication/225251417)）。中等成本、中等效果。
  3. **LDI + 學習式補繪（Facebook / SOTA）**：[Context-aware Layered Depth Inpainting, CVPR 2020](https://github.com/vt-vl-lab/3d-photo-inpainting)——沿 depth 斷崖切多層 LDI，CNN 真的「畫出」被遮擋區的色與深。論文明指 naïve 不是破洞就是拉伸、擴散補繪太糊，只有此法能合成真實紋理。需跑模型、慢、重。

**本專案策略（使用者裁示：A+B 先做、C 規劃）**：
- 取捨核心：位移著色器的賣點就是「輕量即時（~1.9MB / 秒級）」。完整解 disocclusion 需 LDI+CNN，
  等於把剛甩掉的重後端加回來——那其實是 mesh/進階路線該去的方向，不該塞進輕量預設路線。
- **A（已做）**：邊界梯度衰減，並開成 UI 滑桿（uEdgeFalloff 0~20，預設 6）讓使用者實機調甜蜜點。
- **B（已做）**：著色器內 depth-aware 補色——取樣若落在「比原處明顯更近(>0.06)」的像素（前景滲入），
  沿位移反方向小步(≤4)退到「不再更近」的樣本，改填鄰近背景色。是層級 2 的輕量著色器近似，
  維持即時、零後端依賴。半透明/玻璃仍有極限（depth 不可靠，屬本質限制）。
- **C（未來、進階路線）**：LDI + 學習式補繪。**走 mesh/高品質匯出路線**，與「單張 RGB → 自動估深」
  一起做，因兩者都需重運算；正好可共用已預留的 backend/depth_estimator.py 同類注入接口
  （未來新增 `LDIInpaintEstimator` / 整合 vt-vl-lab/3d-photo-inpainting）。

### 本次 Changes（追加 A+B）
- `frontend/src/parallax.ts`: FRAG 加 disocclusion 兩道防線（A 邊界衰減已存在 + B depth-aware 退步重採）；新增 setEdgeFalloff()
- `frontend/index.html` + `main.ts`: 新增「邊界穩定」滑桿（uEdgeFalloff）綁 setEdgeFalloff
