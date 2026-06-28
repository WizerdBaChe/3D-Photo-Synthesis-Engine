# Phase Checkpoint
- Project: 3D-Photo-Synthesis-Engine
- Phase: Phase 1 – 後端 depth 語意 + 座標系 + 斷崖遮罩修正
- Status: in-progress
- Date: 2026-06-27
- Detail: references/3D-photo-engine-phase1-detail.md

## Goals
- 消除放射狀線條（Bug A/C/D）
- 統一 depth 語意（disparity vs metric）
- 修正 glTF 座標系（Y 朝上、Z 朝觀者）
- 斷崖遮罩改在修補後 depth 重算

## Decisions
- depth_convention=auto：啟發式（右偏+高值稀少→disparity），判定結果+直方圖摘要寫 log
- disparity→metric：1/(d+eps) 反轉後重正規化；eps=1e-3 防除零
- 新增 DepthDiscontinuityPolicy：絕對深度差為主（abs_diff_ratio=0.04）、Sobel refinement 可關（use_sobel_refinement toggle）；舊 SobelEdgeDetector 保留為 legacy
- build_topology 改為一律在修補後 depth 重算斷崖遮罩（frame.mask 僅作破洞修補語意）
- unproject_to_points：Y=-(V-cy)*Z/fy、Z=-Z_cam，輸出 glTF 右手系
- near/far 與視差強度語意收斂留待 Step 4（depth 仍 normalize [0,1]，near/far 只影響 DIBR mapping）
- 目標體驗鎖定：Facebook 3D Photo 式視差；自由 3D 場景為未來新功能/新專案
- API 新增 depth_convention、edge_policy 兩個 query param

## Changes
- `backend/rgbd_loader.py`: 新增 normalize_depth_semantics / _detect_is_disparity；load_rgbd_from_bytes 加 depth_convention 參數
- `src/core/geometry.py`: unproject_to_points 翻 Y/Z；build_topology 移除 frame.mask 沿用，改呼叫 edge_policy.compute_mask(frame.depth)
- `src/core/policies.py`: 新增 DepthDiscontinuityPolicy（兩階段，Sobel 可關）
- `src/app/orchestrator.py`: Phase 1/3 注解分離（破洞語意 vs 斷崖語意）
- `backend/app.py`: import DepthDiscontinuityPolicy；/synthesize 加 depth_convention + edge_policy 參數；預設改用 DepthDiscontinuityPolicy
- `tests/unit/test_geometry.py`: 更新 Z 期望值（取負）；TestBuildTopology 改用 _ConstMaskPolicy 注入；新增 Y flip / near-closer-to-viewer / TestDepthDiscontinuityPolicy 測試
- `tests/unit/test_rgbd_loader.py`: 新增 depth_convention 三模式 + auto 啟發式測試

## Open Questions / TODO
- **殘留放射線**：正面角度已大幅改善，但旋轉到側面/大角度時仍出現大量放射狀 → 根因尚未完整解決。待分析：是 DepthDiscontinuityPolicy 閾值不足？修補後的 depth 邊界仍有斜坡？還是 2.5D 本質限制（側面本就無資料）
- **Step 2**：前端 OrbitControls → 受限視差控制（小角度 pan/tilt，Facebook 3D Photo 手感）
- **Step 4**：near/far → 視差強度語意，文檔明寫假設
- 分支 `fix/depth-semantics-coordinate-cliff` 尚未 commit / PR
- auto 啟發式門檻（high_frac 0.35、skew>0）以少量樣本校準，可能需更多真實圖片驗證


# Phase Checkpoint
- Project: 3D-Photo-Synthesis-Engine
- Phase: Phase 2 – 診斷可觀測性 + 3D 邊長剔除 + Facebook 受限視差相機
- Status: completed
- Date: 2026-06-28
- Detail: references/3D-photo-engine-phase2-detail.md

## Goals
- 補上「中間產物可檢查」（之前缺，無法 trace 放射線成因）
- 根治側面放射狀線條（Step 1 後正面已乾淨、側面仍大量）
- 相機改成 Facebook 3D Photo 式受限視差（取代 Google Earth 式 OrbitControls）

## Decisions
- 可觀測性用獨立 CLI（scripts/inspect_pipeline.py），不在 /synthesize 加 debug 分支——最小資源、與請求路徑解耦
- 放射線根因確認（用工具量出）：平滑 ML depth 無銳利斷崖，斷崖遮罩只切到 0.16% 像素（漏切）；放射線 = 0.5% 被拉成長條的三角形，3D 邊長 max/median=576.9×
- 根治改採「3D 邊長剔除」而非再調斷崖遮罩：與視角、與 2D 斷崖判定無關，量化指紋明確（長尾）
- max_edge_ratio 預設 None（關），API 預設 30；k=30 砍 0.5% 面、max→0.18，主體不動（先量測再開、可 bisect）
- 相機採「滑鼠位置驅動視差」（非拖曳），固定正前方中央、±6° tilt、無法繞側面（同時直接隱藏 2.5D 側面）
- near/far → 視差強度仍留 Step 4，本次不調

## Changes
- `scripts/inspect_pipeline.py`: 新增獨立 CLI，dump 正規化深度/斷崖遮罩疊圖/修補後深度/3D 邊長統計(JSON)
- `src/core/geometry.py`: GeometryProcessor 加 max_edge_ratio 參數；build_topology 加 Step 5b 邊長剔除；新增 _cull_long_edge_faces（向量化）
- `backend/app.py`: /synthesize 加 max_edge_ratio query（預設 30），傳入 GeometryProcessor
- `frontend/src/viewer.ts`: 移除 OrbitControls，改滑鼠位置驅動受限視差（pointermove/leave + damping lerp 回正面）
- `tests/unit/test_geometry.py`: 新增 TestEdgeLengthCulling（預設關不影響、開啟剔除拉伸面、均勻 mesh 不誤刪）
- `samples/`: 使用者房間圖 RGB_TEST.jpg + DEPTH_TEST.png
- `.gitignore`: 加 /debug_out/

## Open Questions / TODO
- 等使用者實機驗收：滑鼠視差手感（panAmount/maxTiltDeg 可調）、側面放射線是否確實消失
- max_edge_ratio=30 對其他圖是否普適（不同 depth 尺度/構圖），需更多樣本驗證；過度剔除會在真實深邊界留洞
- Step 4：near/far → 視差強度語意系統性收斂（dump 已可顯化 near/far 對邊長分布影響）
- 分支 `fix/depth-semantics-coordinate-cliff` 含 Step 1+2，仍未 commit / PR（使用者待確認）
- 前端無單元測試框架，viewer.ts 僅靠 tsc/vite build typecheck


# Phase Checkpoint
- Project: 3D-Photo-Synthesis-Engine
- Phase: Phase 3 – 架構轉向：深度位移視差著色器（取代 mesh 為預設前端）+ disocclusion 緩解
- Status: completed
- Date: 2026-06-28
- Detail: references/3D-photo-engine-phase3-detail.md

## Goals
- 解掉使用者實機回報 5 點（畫作感 / 太遠 / 前端 10 秒 / 跟隨慢 / 有無現成可學）
- 改用業界標準「深度位移視差著色器」為預設輕量路徑；mesh/.glb 降為進階匯出選項（並存）
- 為未來「單張 RGB → 自動估深 → 合成」預留可插拔 DepthEstimator 接口（本次不接模型）

## Decisions
- **關鍵覆盤**：Phase 1/2 走「逐像素反投影成 1M 面 mesh → 30MB .glb」是過度工程；5 點全源於此架構選擇。業界 FB 3D Photo 網頁版 = 平面 quad 上 depth map UV 位移 fragment shader（~50 行），不需 3D 反投影。**早該先調研再實作**（詳見 detail 的「為何走錯路」覆盤）
- 兩者並存：視差為預設（快、輕、無 artefact）；mesh 保留供匯出 .glb，舊路徑（viewer.ts / synthesize / 反投影管線）零改動
- 互動改「拖曳驅動」（取代 hover）：dragScale=2.2 易到上限、damping=0.18 反應快、放開回正
- 著色器位移：offset = uMouse*(0.5-depth)*uIntensity，以 0.5 為中性面、前後景反向
- DepthEstimator 抽象介面 + NoOp 佔位 + provider；無 depth 且未啟用 → 422
- 新端點 /parallax 回 base64 PNG×2（~1.9MB），不動 /synthesize
- **disocclusion（殘影/物件撥離）業界三層**：純位移(治標)／DIBR depth-aided 補色(只填背景、排前景)／LDI+CNN 學習補繪(FB/SOTA，重)。裁示：A+B 輕量先做、C 走未來 mesh/進階路線（與自動估深共用 DepthEstimator 接口）
- A 邊界衰減：用 depth 梯度，邊界處壓住位移；開成 UI 滑桿（uEdgeFalloff 0~20，預設 6）
- B depth-aware 補色：取樣落在「明顯更近」像素(前景滲入)時，沿位移反向退步(≤4)取背景色重採——層級2的著色器輕量近似，零後端依賴
- 本質限制：玻璃/半透明（depth 不可靠）仍有殘留，唯 C 能解

## Changes
- `backend/depth_estimator.py`: 新增 DepthEstimator 抽象 + NoOpDepthEstimator + get/set provider（純介面，無模型/依賴）
- `backend/app.py`: 新增 POST /parallax（可選 depth、共用 loader 正規化、回 {width,height,rgb,depth} base64 PNG）；_png_data_url helper
- `frontend/src/parallax.ts`: 新增 ParallaxViewer（正交相機 + quad + 位移 shader + 拖曳互動 + contain 縮放）
- `frontend/src/api.ts`: 新增 parallax()（depth 選填）
- `frontend/src/main.ts`: 預設視差模式、depth 選填、視差/Mesh 切換、intensity 滑桿綁 uIntensity
- `frontend/index.html` + `style.css`: depth 標選填、模式 radio、自動估深 checkbox 佔位、intensity 滑桿、mesh-only 參數收合
- `tests/integration/test_backend_api.py`: 新增 TestParallax（有depth 200 / depth 灰階正規化 / 無depth NoOp 422 / 注入估算器 200）
- `frontend/src/parallax.ts`: FRAG 加 disocclusion 兩道防線（A 邊界衰減 + B depth-aware 退步重採）；ClampToEdge；新增 setEdgeFalloff()
- `frontend/index.html` + `main.ts`: 新增「邊界穩定」滑桿（uEdgeFalloff）綁 setEdgeFalloff

## Verification
- pytest 67 passed（原 63 + 4）；tsc && vite build 通過（含 A+B 後重 build 仍綠）
- 端到端：1344×768 → /parallax ~1.9MB（vs mesh ~30MB）；depth auto=metric 正確
- 使用者實機：「相當成功，路線正確」✅（驗 #1/#2/#3/#5）；殘影 A+B 修正待實機調 uEdgeFalloff 甜蜜點

## Open Questions / TODO
- 殘影 A+B 已上線，待使用者實機調「邊界穩定」滑桿找甜蜜點（多→調大、太死→調小）；不透明邊界應收斂，玻璃/半透明仍受限（屬本質、留 C）
- **C（disocclusion 學習式補繪）已完成規劃 → 見 Phase 4 段落**（C1 墊底 + 3DGS 換代雙軌）
- mesh 模式目前在同 viewport 疊第二 canvas（最簡並存）；若要切回清視差 canvas 需加互斥
- 自動估深尚未接模型（NoOp）；未來 MiDaS/Depth-Anything 注入點已就位
- 分支 `fix/depth-semantics-coordinate-cliff` 已 commit（5 個語意化 commit）並開 PR #1（→ main）

# Phase Checkpoint
- Project: 3D-Photo-Synthesis-Engine
- Phase: Phase 4 – C：disocclusion 學習式補繪（規劃，尚未動工）
- Status: in-progress（僅規劃完成；使用者要求 compact 後再執行）
- Date: 2026-06-28
- Detail: references/3D-photo-engine-phase4-plan.md

## Goals
- 規劃如何根治殘影（disocclusion）——輕量視差 A+B 已到本質天花板，需「真的把被遮擋區畫出來」
- 不動輕量預設路線（/parallax），C 全走 mesh/進階路線

## Decisions
- 調研三代：①vt-vl-lab/3d-photo-inpainting(CVPR2020) 已過時不維護(Py3.7/torch1.4)、不原樣整合；②SLIDE(2021) 概念參考；③2024–2025 = 基礎模型深度 + warp + 擴散補繪 / **3DGS**
- **關鍵判斷**：「warp+2D 擴散補洞」非最優——逐視角 2D 補丁會 temporal flicker、仍困在 2.5D 單層。純本地+足夠好品質的真正解是 **3D Gaussian Splatting（單圖→完整 3D 生成，跨視角一致無閃爍）**
- **定案雙軌（使用者裁示「C1 墊底再換上 3DGS」）**：
  - 軌道一 C1：`DepthAwareInpainter(AbstractInpainter)` 注入 Orchestrator primary（Telea 轉 fallback），DIBR 原則只取背景排前景；純 CPU、零 GPU 依賴、沿用既有接口與降級鏈 → 墊底保底
  - 軌道二 3DGS：換代級——產物 .glb→.ply/splat、前端 GLTFLoader→3DGS 渲染器、新增 `/splat` 端點與既有兩端點並存、補洞 seam 用不上（生成時建進 3D）、torch+模型權重選用安裝
- 本機**有 GPU**（3DGS 軌道可實跑）；重依賴一律選用安裝 + import 失敗優雅退回

## Changes
- （本回合無程式碼變更）references/3D-photo-engine-phase4-plan.md：完整調研 + 雙軌落地計畫

## Open Questions / TODO
- **下一 session 接手點**：從軌道一 C1 的 `DepthAwareInpainter` 實作開始（最低風險、立即見效）
- 並行：3DGS spike（本機 GPU 跑單圖→splat + 前端試渲染，驗品質/延遲/可行性）→ 通過再規劃正式換代
- 3DGS 前端渲染器候選：@mkkellogg/gaussian-splats-3d 或 Three.js splat 方案
- 玻璃/半透明屬本質限制，即使 3DGS 亦有極限，不過度承諾

# Phase Checkpoint
- Project: 3D-Photo-Synthesis-Engine
- Phase: Phase 4 軌道一 C1 落地 + 前端 viewer/UX 修正
- Status: completed（C1 已 merge 進 main；前端修正在 PR #3 待 merge）
- Date: 2026-06-28

## Goals
- 落地軌道一 C1：DIBR depth-aware 補繪取代 Telea 當 Orchestrator primary
- 修實機回報的前端問題：視差拖曳手感、mesh 模式空白/切換不清、測試範例圖、mesh 攝影機（浮雕/遠看物件/歪）

## Decisions
- **C1 演算法**：`DepthAwareInpainter` = depth-gated 迭代背景擴散（純 NumPy/OpenCV、零 GPU、無狀態）——估背景深度門檻→切背景種子（排前景）→逐圈往洞內擴散 color/depth→殘餘交 Telea 收尾→depth 裁回原值域防尖刺。沿用 AbstractInpainter 契約，注入 /synthesize primary、Telea 留 fallback
- **mesh 攝影機三連修**（與視差模式手感對齊 = FB 3D Photo「鏡頭在場景內」感）：
  - 拖曳驅動（取代 hover）：dragScale=3.5、拖曳中無阻尼跟手、放開 damping=0.18 回正
  - 解「浮雕/遠看 3D 物件」：mesh 是近窄遠寬透視視錐，舊版用整體 bbox 寬高（=遠平面尺寸）定框距把相機推到視錐外。改貼到正面（max.z）、框距用正面內容尺度（bbox 高 ×0.4）→ 後牆填滿溢出視野、box 輪廓落框外
  - 解「攝影機歪」：原相機光軸 = 反投影空間 X=0,Y=0 線（影像中心 cx,cy 映到 X=Y=0）。先前對準 bbox 質心、被遠平面拉偏 → 斜射。改相機站位與 lookAt 都落在 X=0,Y=0、正對 −Z
- **新增 mesh 可選「自由旋轉視角」**（OrbitControls）：預設 FB 視差，勾選才自由轉動看真 3D 結構（會露側面破洞，進階）
- **業界（FB）做法釐清**：FB 網頁版根本不看 mesh，就是「視差模式」那種平面+depth UV 位移（天生正、無 box 邊界）；縱深與空洞靠 **LDI 多層 RGBA+depth（各層不同速位移、前景移開露背景層）+ 學習式 inpainting 補真空洞**（CVPR2020）。即我們的軌道二方向
- **空洞確認**：未加 LDI/3DGS 模型前，mesh 大角度露出「原圖沒拍到的被遮擋區」= 空洞，屬單層 2.5D 本質限制、正常現象；C1 只能讓斷崖接縫不滲前景，補不了大洞

## Changes
- `src/core/inpainting.py`: 新增 `DepthAwareInpainter(AbstractInpainter)`；模組 docstring 註明現行主修補器
- `backend/app.py`: /synthesize primary 由 Telea 改 `DepthAwareInpainter()`，Telea 留 fallback
- `tests/unit/test_inpainting_depth_aware.py`: 新增 16 測（fast path/契約/DIBR 只取背景/退化/與 Telea 對照）
- `frontend/src/parallax.ts`: dragScale 2.2→3.5、拖曳中無阻尼跟手、`setVisible()`
- `frontend/src/viewer.ts`: 拖曳驅動、相機貼正面+光軸對準（X=0,Y=0）、panAmount/tiltOffset 加大、`setVisible()`/`clear()`/`setOrbitMode()`/cameraZ、OrbitControls
- `frontend/src/main.ts`: applyViewerVisibility()/resetViewport()、模式切換清空、範例圖一鍵載入、orbit toggle 綁定
- `frontend/src/style.css`: canvas 改 position:absolute 重疊（解 mesh 空白）、empty-state z-index、.secondary 按鈕
- `frontend/index.html`: 「載入測試範例圖」按鈕、mesh-only「自由旋轉視角」checkbox
- `frontend/public/samples/`: 內建 RGB_TEST.jpg + DEPTH_TEST.png

## Verification
- pytest 83 passed（原 67 + 新 16）；frontend `npm run build` 綠（tsc + Vite）
- 使用者實機：C1 待驗；mesh 拖曳手感一致✅、自由旋轉模式✅切換正確✅；mesh 正視角仍偏「遠看物件」與「歪」→ 本回合續修（光軸對準 + 貼正面），待再驗

## Open Questions / TODO
- **PR 狀態**：PR #1（Phase1-3）✅merged、PR #2（C1）✅merged 進 main；**PR #3（前端 viewer/UX）OPEN 待 merge**（4 commits：UX 修正 / mesh 手感 / 貼正面框距 / 光軸對準）
- mesh 正視角係數（框高 ×0.4）依 near:far≈1:4 估算，實機若仍偏遠調小（0.3）、太貼調大——待使用者定案
- **空洞根治 = 軌道二**（LDI 多層補繪 或 3DGS）；下一步可起 3DGS spike（本機 GPU）
- depth_far 預設 4.0（前端 parallax 滑桿），若縱深不足可調大

# Phase Checkpoint
- Project: 3D Photo Synthesis Engine
- Phase: Phase 4 軌道二 — LDI 分層補洞引擎（階段 A：端到端跑起來）
- Status: completed
- Date: 2026-06-28

## Goals
- 把「補洞」升級為 **LDI（Layered Depth Image）多層補洞**，根治小角度視差的 disocclusion 空洞
- 使用者裁示：目標①可重用引擎+規格 / ②端到端可用 / ③低配工具鏈 **全要，順序 2→1→3**；先跑起來
- 前端 = **新增獨立「LDI 模式」**與視差/mesh 並存（風險隔離、可 A/B 對比）

## Decisions
- **第一性原理**：FB 3D Photo = 小角度視差，剩餘問題只有 disocclusion 空洞 → LDI 是正解（非 3DGS 換代，見前一 spike no-go checkpoint）
- **複用 C1**：背景層的遮擋破洞用既有 DepthAwareInpainter（只取背景、排前景）預填 —— 這是 C1 最對的用法；純 CPU、零新依賴
- **層語意**：layers 由近到遠；最遠背景底層 alpha 全 255（不透明底，任何視差量不露黑洞）；近層位移大、遠層位移小，前景滑開露出預填背景
- **分層門檻**：用 depth **分位數**切帶（自適應深度尺度、前景小也能單獨成層），非等距切
- **Provider 模式**：AbstractLDIBuilder + get/set_ldi_builder() 單例（鏡像 depth_estimator），日後可抽換更強分層器，端點/前端不動
- **接口零破壞**：/synthesize、/parallax 與其 shader 一行不動；新 /ldi 與 _acquire_color_depth helper 為純新增

## Changes
- src/core/contracts.py: 新增 LDILayer / LDIScene 契約
- src/core/ldi.py（新）: AbstractLDIBuilder + LDIBuilder（斷崖分層 + 背景層 C1 預填）+ Provider 單例
- backend/app.py: 新增 POST /ldi（num_layers 2~3）+ 共用 _acquire_color_depth helper
- frontend/src/ldi.ts（新）: LDIViewer 多層取樣 shader（over 合成、各層自身 depth 位移）
- frontend/src/api.ts: ldi() + LDIResult/LDILayer 型別
- frontend/src/main.ts: 模式擴為 parallax|ldi|mesh（延遲建 LDIViewer、合成/可見性/按鈕分支）
- frontend/index.html: LDI radio + LDI 層數滑桿（ldi-only）
- tests: test_ldi 單元 12 + /ldi 整合 5；**全套 100 passed**；npm run build typecheck 綠
- 實機煙霧驗收（samples/RGB_TEST 1344×768）：n=2 背景層 100% 不透明且破洞被合理填補、前景層 alpha 正確切出近景；n=3 三層深度遞增

## Open Questions / TODO
- **肉眼已驗（後端輸出）**：背景層大洞（整張床）填補偏 smeary（C1 對超大洞的擴散平滑）——小角度視差下多被前景遮住，可接受；改善留階段 B/C（Provider 換更強 inpainter）
- **待實機前端驗**：三模式切換無互蓋、LDI 拖曳露出預填背景（後端資料已備齊）
- 分支 feat/ldi-layers（2 commits：core+/ldi、前端 LDI 模式），PR #3 已 merge 進 main，本分支從 main 起
- **下一步**：開 PR；通過後進階段 B（.ldi 開放格式規格 docs/LDI_FORMAT.md + CLI tools/ldi_cli.py + 文件），再階段 C（可選 Depth-Anything 估深 + Docker + 實測表）
