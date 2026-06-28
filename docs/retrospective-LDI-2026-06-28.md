# LDI 分層補洞引擎 — 經驗守則

**整理日期**：2026-06-28
**專案期間**：Phase 4 軌道二（3DGS spike → LDI 階段 A）→ 暫停
**核心目標**：根治 FB 3D Photo 小角度視差下的 disocclusion 空洞，並標準化成低配硬體可用的引擎

---

## TL;DR（最重要的三件事）

> 如果只能記住三件事：
> 1. **視覺/渲染功能,後端資料對 ≠ 畫面對**。三輪都是「測試全綠、curl 回正確 JSON」但實機畫面是壞的（空白→紙板→脫影）。視覺功能一定要有「人在迴圈裡的肉眼 Gate」,別拿後端煙霧測試當通過。
> 2. **東西「看起來不對」時,先查業界正解再逐項比對,不要憑感覺迭代**。剛性分層平移 = 紙板抽離感,是查了 FB 3D Photo / Alan Zucconi 才確認的觀念性錯誤；早一步查就省兩輪。
> 3. **把懷疑最弱的零件做成可抽換（Provider）**。最後結論是「瓶頸 = 背景補繪品質,非 shader/管線」,而 LDIBuilder 的 inpainter 已經是注入式 → 重啟只需換零件（LaMa）不必重寫。

---

## 技術決策紀錄

### Decision: 縱深補洞用 LDI 連續位移 + 預填背景,而非剛性分層或 3DGS
- **Chosen**：與視差模式相同的**連續逐像素 depth UV 位移**（`offset = uMouse*(0.5-depth)*強度*邊界衰減`）,只在 disocclusion 處改取後端**預先 inpaint 的背景層**。
- **Reason**：FB 3D Photo / Zucconi 的業界正解就是連續位移（depth 平滑→位移漸變→無硬邊）；分層只負責「破洞填真內容」。
- **Rejected**：
  - **剛性分層平移**（把離散層當剛體整塊搬）→ 經典 cardboard cutout 紙板抽離感。
  - **3DGS 換代** → 8GB Blackwell sm_120 + 授權 + 生態,前一 spike 已 no-go。
- **Context**：小角度視差、單張 RGB(+depth)、純 CPU、零重依賴的前提下。

### Decision: 管線接口 Provider 化
- **Chosen**：`AbstractLDIBuilder` + `get_/set_ldi_builder()` 單例,鏡像既有 `backend/depth_estimator.py`。
- **Reason**：分層器/補繪器日後要換更強的（LaMa/diffusion/更多層）,只改 provider,端點與前端不動。
- **Context**：任何「我懷疑這塊品質不夠但先用 baseline」的元件,都該這樣做。

---

## 踩雷紀錄

### Pitfall: 多層 GLSL shader 用 sampler 陣列 + 動態迴圈 → 整片空白
- **Symptom**：LDI 模式合成後檢視視窗全空白,且看起來像「切換模式沒刷新」。
- **Root cause**：WebGL/GLSL ES 對「sampler2D 陣列以變數索引」「動態迴圈上限」相容性差 → shader 編譯失敗 → three.js **靜默渲染空白**（不報錯）。
- **Fix/workaround**：改成**完全展開的具名 uniform**（`uColor0/1/2`…）+ 直線合成；掛 `renderer.debug.onShaderError` 印 infoLog。
- **Prevention**：three.js ShaderMaterial 一律避開 sampler 陣列變數索引與動態迴圈；多層就展開。一律掛 onShaderError,否則編譯失敗會靜默變空白、誤導成別的 bug。

### Pitfall: 剛性分層平移 = 紙板抽離 + 反向錯覺
- **Symptom**：前景被整塊「拔出」、與背景脫離；拖曳方向/手感不對。
- **Root cause**：(a) 離散層當剛體整塊平移本身就會在層邊界出現硬切口;(b) 用「層深度中點」當平移量,導致背景層平移幅度比前景大 → 反向錯覺。
- **Fix/workaround**：放棄剛性平移,改連續位移（見技術決策）。
- **Prevention**：縱深視差**永遠用連續 depth 位移**,不要把 LDI 的「分層」理解成「前端把層當積木搬」。

### Pitfall: 把「後端煙霧測試過」當成「視覺 Gate 過」
- **Symptom**：宣稱階段 A 視覺驗收通過,實機三輪都壞。
- **Root cause**：後端 curl/單元測試只驗資料結構正確,沒驗瀏覽器實際渲染。
- **Prevention**：視覺功能的「通過」定義 = 使用者在瀏覽器看過。後端測試只能宣稱「資料路徑正確」,不能宣稱「畫面正確」。

### Pitfall: 多個 uvicorn --reload 殘留 + 8000 stale TCP listener
- **Symptom**：重啟後端時 `[Errno 10048]` port 已佔用;砍掉 PID 後 `Get-NetTCPConnection` 仍顯示該 PID listening。
- **Root cause**：先前數次背景啟動留下孤兒 reload 程序;程序終止後 socket 仍短暫停在 TIME_WAIT。
- **Fix/workaround**：用 `Get-NetTCPConnection -LocalPort 8000` 找 OwningProcess 後 `taskkill /T /F`;殘留條目會自行釋放。改動後端後務必重啟（或靠 --reload）才會 serve 新 payload。
- **Prevention**：開發伺服器用單一實例;改後端後先確認 serving 的是新程式碼（curl 驗新欄位）再請人測。

---

## 有效工作模式

### Workflow: 「看起來不對」→ 先查業界 → 逐項比對 → 再改
- **Approach**：使用者說畫面不對時,先 WebSearch/WebFetch 業界標準作法（這次是 FB 3D Photo / Alan Zucconi shader）,做一張「業界 vs 現況」逐項比對表,定位觀念錯誤,再動手。
- **When to use**：任何「產出看起來不對但說不清為什麼」的視覺/演算法問題。
- **Why it works**：避免在錯誤模型上反覆微調（這次紙板問題若早查就省兩輪迭代）。
- **Caveats**：純工程實作細節（非觀念錯）不需每次都查,有合理預設就做。

### Workflow: 分階段 + 逐 Gate,先交付可用成果
- **Approach**：A（端到端跑起來）→ B（標準化）→ C（工具鏈）,每階段一個可獨立 merge 的 PR,Gate 沒過就停下檢討。
- **Why it works**：階段 A 視覺 Gate 沒過時,B/C 還沒投入,損失最小,且檢討報告清楚。

---

## 專案約束與術語

### Constraint: 重依賴一律選用安裝 + import 失敗優雅退回
- **Limit**：torch / LaMa / 任何重模型只在啟用時裝;import 失敗 → NoOp → 端點回 422。**絕不污染 `requirements.txt` 基礎依賴。**
- **Impact**：所有 AI 元件（depth estimator、未來的 inpainter）都走 lazy import + provider。

### Constraint: 既有路徑零破壞
- **Limit**：`/synthesize`、`/parallax` 與 `frontend/src/{parallax,viewer}.ts` 一行不動;既有測試全程須續綠（本回合 83→100）。

### Constraint: 架構天花板
- **Limit**：單張 depth map 位移 + 補洞（FB 3D Photo / 單圖 LDI）**本質只能做小幅變形**,被遮擋內容無法真正還原。
- **Impact**：要真正拉開與視差的差距,得換零件（生成式 inpainter 或真 3D 表示）,不是調 shader。

### Term Definitions
| 術語 | 在本專案的意義 | 備註 |
|------|----------------|------|
| 視差模式 | 單層平面 + depth UV 位移(連續),預設輕量路徑 | 已驗收乾淨,LDI 沿用其位移數學 |
| LDI | 沿 depth 斷崖分層 + 背景層預填,**渲染仍是連續位移**,分層只供破洞填真內容 | 不是「前端把層當積木搬」 |
| disocclusion | 前景滑開露出的、原圖沒有的破洞 | 唯一剩餘問題;小角度下只佔邊緣細條 |
| C1 / DepthAwareInpainter | DIBR「只取背景、排前景」的純 CPU 古典擴散補繪 | 對超大洞會糊成放射狀條紋(脫影來源) |

---

## 使用者偏好紀錄

### Preference: 視覺功能必須實機驗證
- **Preference**：視覺/渲染改動,要在瀏覽器實際看過才算數。
- **Anti-pattern**：拿「測試綠 / 後端 curl 回正確 JSON」就宣稱視覺功能可用。
- **Scope**：所有前端渲染相關。

### Preference: 看起來不對 → 查證 + 逐項比對 → 再改
- **Preference**：遇到觀念可能錯的問題,先查業界正解、逐項比對差異,寫清楚再修。
- **Anti-pattern**：在沒查證的模型上憑感覺反覆微調。

### Preference: 誠實收尾
- **Preference**：暫停時要寫誠實的根因 + 檢討報告,標清楚哪些對、哪些是天花板。
- **Anti-pattern**：含糊的「已修好」或假裝都解決了。

### Preference: git 流程
- **Preference**：feature branch + PR + Conventional Commits;merge 由使用者拍板（本回合明示要 merge 才做）。

---

## 可複用守則（帶進下個專案）

### Principle: 視覺功能要有人在迴圈裡的肉眼 Gate
- **Rule**：渲染/視覺類功能,「通過」的定義是使用者在真實環境看過;自動化測試只能宣稱資料路徑正確。
- **Applies when**：任何輸出是「給人看的畫面」的功能。
- **Exceptions**：純資料/邏輯功能,單元測試即足。

### Principle: 產出「看起來不對」時,先對照權威/業界參考
- **Rule**：在錯誤模型上微調是浪費;先查 canonical 作法、逐項比對,再動手。
- **Applies when**：視覺、演算法、或任何有公認最佳實踐的領域。

### Principle: WebGL/GLSL ES 避開 sampler 陣列變數索引與動態迴圈
- **Rule**：多 texture 一律展開成具名 uniform;掛 onShaderError,別讓編譯失敗靜默變空白。
- **Applies when**：three.js ShaderMaterial / 任何 WebGL1 GLSL ES 1.00 shader。

### Principle: 把懷疑最弱的零件做成可抽換
- **Rule**：用 baseline 先跑通,但把它放在 Provider/注入點後面,日後換更強實作不必重寫管線。
- **Applies when**：明知某元件品質不夠但要先有可用成果時。

---

## 未解決的問題

> 這次沒解決、下次還要面對的：

- [ ] 超大洞（整張床/花瓶）的補繪品質：C1 古典擴散會糊成放射狀條紋（脫影）。
- [ ] LDI 在小角度下與視差模式差異不夠大（disocclusion 只佔邊緣細條）—— 需更高品質的破洞填補才划算。
- [ ] 標準化階段 B（.ldi 開放格式 + CLI + docs）與階段 C（Depth-Anything 估深 + Docker + 實測表）尚未開始。

---

## 下次想嘗試的做法

- **路 B（首選、最高投報率）**：把 LDIBuilder 注入的 inpainter 由 C1 換成**預訓練 LaMa / 輕量 diffusion inpainting**（選用安裝、import 失敗退 C1）。大洞填可信後,LDI 才會明顯勝過視差。
- **路 A'**：純 CPU 的 PatchMatch 風格 / 邊緣導向合成,減輕超大洞 smear（天花板仍受古典法限制）。
- **路 C**：待 8GB 友善、單圖、可商用的 feed-forward 3DGS 方案成熟再回試。
- **評估判準**：評估任何補繪/補洞方案時,直接看它對「整張床」這種**超大洞**的輸出,別只看小破洞 demo。
