# Phase 4 規劃 — C：disocclusion 學習式補繪（LDI / depth-aware inpainting）

> 狀態：**規劃中（尚未動工）**。本檔是調研 + 落地計畫，供開工前對齊。
> 前情：Phase 3 已確認輕量視差路線的殘影是本質天花板（A 邊界衰減 + B depth-aware 退步重採已到頂），
> 完整解 disocclusion 必須有「真的把被遮擋區畫出來」的補繪能力 → 即本 Phase 的 C。

## 目標（要解什麼）

- 視角移動時，前景背後**原圖沒拍到**的區域被露出（disocclusion）。輕量 shader 只能拉伸/取鄰色 → 殘影、玻璃鬼影、物件撥離。
- C 的目標：在 mesh / 進階路線上，對這些露出區**合成合理的色彩與深度**，使中大角度視差也不穿幫。
- 明確**不**動輕量預設路線（/parallax + ParallaxViewer）——C 是重運算，屬 mesh/匯出路線，與輕量路線並存。

## 調研結論（業界現況，2020 → 2025）

disocclusion 補繪有三代做法，成本/品質/維護性差異極大：

### 第 1 代（2020）：Context-aware Layered Depth Inpainting（原始引用）
- 論文 [Shih et al., CVPR 2020](https://arxiv.org/abs/2004.04727)；repo [vt-vl-lab/3d-photo-inpainting](https://github.com/vt-vl-lab/3d-photo-inpainting)。
- 沿 depth 斷崖切多層 LDI，學習式模型逐層補色 + 補深，輸出 mesh(PLY)/環繞影片。
- **現實問題**：Python 3.7 / PyTorch 1.4 / CUDA 10.1，**已不維護**；約 2–3 分鐘/張；輸出偏向預錄影片而非互動。
- 結論：**不建議原樣整合**（依賴地獄、環境難重現）。其「LDI 分層 + 補繪」的**思想**仍是基礎，但實作該用現代元件重組。

### 第 2 代（2021）：SLIDE — Soft Layering + depth-aware inpainting
- [SLIDE, ICCV 2021](https://ar5iv.labs.arxiv.org/html/2109.01068)：軟分層保留細節、depth-aware 訓練。概念參考，無方便整合的官方輕量包。

### 第 3 代（2024–2025）：基礎模型 + warp + 擴散補繪 / Gaussian splatting
- 深度改用基礎模型：[Depth-Anything-V2, NeurIPS 2024](https://github.com/DepthAnything/Depth-Anything-V2)（取代手刻深度，細節/穩定度大幅提升；最小 ViT-S 版可 CPU/小 GPU 跑）。
- 露出區補繪改用**擴散式 inpainting**：把「warp 後產生的破洞遮罩」交給 [diffusers 的 SD/SDXL inpainting pipeline](https://huggingface.co/docs/diffusers/using-diffusers/inpaint)（白=要補、黑=保留），prompt-free 也能補。
- 更前沿：單圖→3D 直接走 Gaussian splatting / 多視角擴散（[DepthSplat CVPR2025、MonoSplat CVPR2025、CausNVS 2025](https://arxiv.org/pdf/2509.06579)），品質最好但工程量最大、產物與現有 mesh/.glb 路線差距大。

## 本專案的關鍵優勢：接口早已備好

C 不需重寫架構，現有 seam 直接吻合（Phase 3 + MVP 設計就預留了）：

| 需求 | 既有接口 | 位置 |
|---|---|---|
| 單張 RGB → depth（第 3 代深度） | `DepthEstimator`（abstract + NoOp + provider） | [backend/depth_estimator.py](backend/depth_estimator.py) |
| 露出區補色補深（補繪器） | `AbstractInpainter.fill()`；註解已寫「LaMaInpainter 佔位，整合參照 PSM Phase 4」 | [src/core/inpainting.py](src/core/inpainting.py) |
| GPU OOM 自動降級 | `VRAMExhaustedError` + `VramStrategy(PERSISTENT/LAZY)` | [src/core/inpainting.py](src/core/inpainting.py) |
| 管線編排（偵測→補繪→建面） | `Orchestrator.process()`；primary/fallback 注入 | [src/app/orchestrator.py](src/app/orchestrator.py) |
| 端點 | `/synthesize`（mesh 路線，不動 /parallax） | [backend/app.py](backend/app.py) |

→ 整合 C = **新增具體實作類別 + 注入**，端點與前端幾乎不動。這正是當初分層的回報。

## 為什麼最終目標是 3DGS，而不是「warp + 2D 擴散補洞」

使用者問「純本地、品質足夠好，直接上擴散補繪是否最優」。調研後的誠實結論：**不是**。

- 「mesh warp 後破洞 → 2D 擴散 inpaint 補洞」是**逐視角、2D** 的補丁：每個角度補出的內容彼此不一致，
  連續拖曳變視角時會**閃爍/漂移（temporal flicker）**，且仍困在「2.5D 只有一層」的根。
- 2025 現行最優是跳出「補洞」框架，直接把單張圖重建成**有體積的 3D 表示（3D Gaussian Splatting）**：
  用擴散先驗**一次性生成整個 3D 場景**，被遮擋區在生成當下就被腦補進 3D → **天生跨視角一致、無閃爍**，
  這才是「足夠好品質 + 純本地（本機 GPU 可跑）」的真正解。參考
  [DepthSplat](https://arxiv.org/pdf/2411.14384)、[MonoSplat CVPR2025](https://www.nature.com/articles/s41598-025-03200-7)、
  [單圖+擴散去噪生成完整 splats 2025](https://arxiv.org/html/2508.21542v1)。

## 定案路線（使用者裁示）：C1 墊底 → 3DGS 換代（雙軌）

> 使用者裁示：「**C1 墊底再換上 3DGS**；設計完流程先停，需先 compact 再執行以提高效能。」
> 本機**有 GPU**。本檔只到流程設計為止，**不在本回合動工**。

### 軌道一 — C1：depth-aware 古典補繪（先落地、墊底、零換代風險）
- 走現有 mesh 路線、**沿用既有接口**：新增 `DepthAwareInpainter(AbstractInpainter)`，注入 `Orchestrator` 的 primary
  （取代目前的 Telea；Telea 續留 fallback）。
- 演算法照 **DIBR 原則**：對 disocclusion 露出區建遮罩，補色補深時**只取背景側鄰域、用 depth 排除前景**，
  避免前景色糊進洞（解掉房間圖「床上冒櫃子木色」、花瓶窗景的物件撥離）。
- 純 CPU、**零 GPU 依賴、不碰 requirements 重依賴**、沿用既有 `VRAMExhaustedError` 降級鏈。
- 驗收：與現有 Telea 對比，中角度露出區前景滲入明顯改善；/parallax 輕量路線**零改動**。
- 定位：**墊底保底**——在 3DGS 成熟前，mesh 匯出路線就靠它把殘影壓到可接受。

### 軌道二 — 3DGS 換代（最終目標、換代級、品質天花板）
這是「足夠好品質」的真正去處，但屬**換代**，與 C1 是兩條獨立的路：

- **產物換代**：輸出由 `.glb` mesh → **`.ply` / splat**。
- **前端換代**：Three.js 的 GLTFLoader → **3DGS 渲染器**（候選 `@mkkellogg/gaussian-splats-3d` 或 Three.js splat 方案）。
- **接口取捨**：3DGS **不補洞**（生成時就把遮擋區建進 3D），故當初預留的 `AbstractInpainter` 補洞 seam
  在 3DGS 路線**用不上**；但 `DepthEstimator`（單張 RGB→depth）仍可作為部分 3DGS 管線的前置。
- **端點**：新增獨立端點（如 `/splat`），與 /synthesize（mesh）、/parallax（輕量）三者並存，互不破壞。
- **依賴**：torch + 3DGS 生成模型權重，重、延遲數十秒級、吃 VRAM；一律**選用安裝 + import 失敗優雅退回**。
- **成熟度風險**：這些 2025 repo 的工程成熟度不如 diffusers 穩定，整合偏研究性——故先 spike/原型再決定正式換代。

### 推進順序
1. **先做 C1**：拿到可驗收的殘影改善、保住 mesh 路線（低風險、立即見效）。
2. **並行 3DGS spike**：本機 GPU 跑一張圖的單圖→splat 管線 + 前端試渲染，驗品質/延遲/可行性。
3. spike 通過 → 規劃 3DGS 正式換代（`/splat` 端點 + 前端 splat 渲染器 + 選用安裝）。

## 設計原則（沿用全專案）
- 無狀態後端、策略注入；C1 是「換實作不換接口」，3DGS 是「新增並存端點 + 前端渲染器」，兩者都不破壞既有路徑。
- 輕量預設路線（/parallax）**全程零改動**。
- 重依賴（torch / 3DGS 模型權重）一律**選用安裝 + import 失敗優雅退回**，不破壞基礎部署。
- 玻璃/半透明：depth/單視角資訊本就不足，即使 3DGS 也有極限——標為已知限制，不過度承諾。

## 開工前狀態（本回合到此為止）
- 流程已設計定案（C1 墊底 + 3DGS 換代雙軌）。**使用者要求先 compact 再執行**，故本回合**不寫程式碼**。
- 下一個 session 接手點：**從軌道一 C1 的 `DepthAwareInpainter` 實作開始**（最低風險、立即見效），3DGS spike 並行。
- 環境已確認：本機有 GPU（3DGS 軌道可實跑）。
