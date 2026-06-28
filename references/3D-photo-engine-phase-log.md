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
- **C（未來進階路線）**：LDI + 學習式補繪（vt-vl-lab/3d-photo-inpainting 同類），與「單張 RGB→自動估深」一起做，共用 backend/depth_estimator.py 注入接口
- mesh 模式目前在同 viewport 疊第二 canvas（最簡並存）；若要切回清視差 canvas 需加互斥
- 自動估深尚未接模型（NoOp）；未來 MiDaS/Depth-Anything 注入點已就位
- 分支 `fix/depth-semantics-coordinate-cliff` 現含 Step 1+2+3，仍未 commit / PR
