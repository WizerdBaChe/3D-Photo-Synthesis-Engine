# 設計決策日誌 (Design Decision Log)
**檔案版本**：v1.6 (2026-05-27)  
**狀態**：Active  
**最後更新**：2026-05-27 by System Architect

## 索引 (Index)
| ID | 標題 | 狀態 | 決策日期 |
|----|------|------|----------|
| DD-011 | 採用嵌入式免安裝環境 (Portable Embedded Environment) 部署 | Accepted | 2026-05-27 |
| DD-010 | 採用 PySide6 (Qt) 作為前端展示層框架 | Accepted | 2026-05-27 |
| DD-009 | GUI 與核心引擎的徹底解耦 | Accepted | 2026-05-27 |
| DD-010 | 採用 PySide6 (Qt) 作為前端展示層框架 | Accepted | 2026-05-27 |
| DD-009 | GUI 與核心引擎的徹底解耦 (嚴格 MVVM/Adapter 模式) | Accepted | 2026-05-27 |
| DD-008 | 支援雙模式顯存管理與 OOM 自動降級 (VRAM Management & Fallback) | Accepted | 2026-05-27 |
| DD-007 | 採用 RGB 與 Depth 雙重遮擋修補 | Accepted | 2026-05-27 |
| DD-006 | 採用基於分位數 (Percentile) 的動態邊緣斷離閾值 | Accepted | 2026-05-27 |
| DD-005 | 採用策略模式實作邊緣判定介面 (Edge Detection Policy) | Accepted | 2026-05-27 |
| DD-004 | 採用嚴格型別與形狀註解的資料契約 | Accepted | 2026-05-27 |
| DD-003 | 基於佇列 (Queue) 的非同步事件通訊協定 | Accepted | 2026-05-27 |
| DD-002 | 採用 NumPy 向量化進行網格生成與斷離 | Accepted | 2026-05-27 |
| DD-001 | 確立無狀態分層模組 (Stateless Layered) 架構 | Accepted | 2026-05-27 |

---

## 決策紀錄 (最新在前)

**決策ID**：DD-011  
**標題**：採用嵌入式免安裝環境 (Portable Embedded Environment) 部署  
**狀態**：Accepted  
**日期**：2026-05-27  

* **情境**：專案目標受眾包含不熟悉 Python 環境配置的一般使用者。若要求使用者自行安裝 CUDA Toolkit、配置虛擬環境，將大幅提高使用門檻並引發不可控的相依性衝突。
* **決策**：參考 ComfyUI_portable 架構，系統發布時採用「Windows Embedded Python」進行封裝。所有依賴庫（PyTorch, Open3D, PySide6）與 LaMa 模型權重皆內建於釋出的壓縮檔中，透過相對路徑 `.bat` 腳本啟動。
* **後果**：使用者體驗極大化（開箱即用）。代價是發布檔的體積龐大（預估 4GB ~ 6GB），需建立 CI/CD 管線來自動化這個「肥包 (Fat client)」的打包流程。

---

**決策ID**：DD-010  
**標題**：採用 PySide6 (Qt) 作為前端展示層框架  
**狀態**：Accepted  
**日期**：2026-05-27  

* **情境**：需要為 Python 引擎加上圖形操作介面，且必須支援跨執行緒的非同步通訊（避免 UI 卡死）。
* **決策**：棄用 Tkinter，選擇 PySide6 (官方 Qt for Python)。
* **後果**：PySide6 具備強大的 Signal/Slot 機制，完美契合我們的「事件驅動通訊」架構。其 QThread 能夠安全地把我們厚重的 3D 渲染與 AI 修補引擎隔離在背景運行。

**決策ID**：DD-009  
**標題**：GUI 與核心引擎的徹底解耦 (嚴格 MVVM/Adapter 模式)  
**狀態**：Accepted  
**日期**：2026-05-27  

* **情境**：若 GUI 直接呼叫 `LaMaInpainter` 或 `GeometryProcessor`，會導致前端與後端高度耦合，未來若要將引擎抽換為雲端 API，前端將面臨重構災難。
* **決策**：GUI 層 (View) 只負責發出 PyQt Signals（例如：`slider_moved(value)`）。建立一個獨立的 `InputAdapter` 類別，負責攔截這些 Signals，將其轉換為數學矩陣或系統設定檔（DTO），再透過 `Queue.put()` 丟給背景的協調層 (Orchestrator)。
* **後果**：實現了最純粹的「前端只做映射」原則。核心引擎完全不知道 PyQt 的存在，維持了最高級別的可測試性。

---

**決策ID**：DD-008  
**標題**：支援雙模式顯存管理與 OOM 自動降級 (VRAM Management & Fallback)  
**狀態**：Accepted  
**日期**：2026-05-27  

* **情境**：導入 LaMa AI 模型後，高解析度影像 (1080p) 會消耗高達 7~8 GB 的 VRAM。不同使用者有不同的多工需求，且設備可能隨時面臨 CUDA Out Of Memory (OOM) 崩潰風險。
* **決策**：
  1. 在 GUI 暴露 `VramStrategy` (PERSISTENT / LAZY) 供使用者選擇。在 LAZY 模式下，推論結束必須強制觸發 Python 垃圾回收與 `torch.cuda.empty_cache()`。
  2. 協調層 (Orchestrator) 必須捕捉 PyTorch 的 `RuntimeError`。若偵測到記憶體不足，系統需自動釋放資源，並無縫切換至 CPU 運算的 `TeleaInpainter` 完成該次管線，確保軟體不閃退。
* **後果**：提升了桌面應用的穩定性與使用者好感度。代價是程式碼需增加狀態檢查與資源鎖 (Resource Lock) 的複雜度。

---

**決策ID**：DD-007  
**標題**：採用 RGB 與 Depth 雙重遮擋修補 (Joint RGB-D Inpainting)  
**狀態**：Accepted  
**日期**：2026-05-27  

* **情境**：Phase 3 需要填補深度斷崖產生的物理破洞。若僅修補 RGB 色彩，破洞處的深度值將為 0 或維持背景的極端值，導致 3D 網格在破洞區塊呈現不自然的平面化或尖刺狀。
* **決策**：基於目標硬體（Intel 10th Gen+ 及獨立顯卡）具備充裕算力的前提，規定所有的修補策略（Inpainters）必須「同時修補 Color 矩陣與 Depth 矩陣」。Depth 修補必須維持 float32 的精度。
* **後果**：運算量與記憶體開銷將翻倍（需執行兩次推論或處理），但能確保補全的背景在 3D 空間中具備合理且平滑的幾何深度，極大化提升新視角渲染的視覺品質。

---

**決策ID**：DD-006  
**標題**：採用基於分位數 (Percentile) 的動態邊緣斷離閾值  
**狀態**：Accepted  
**日期**：2026-05-27  

* **情境**：深度圖的數值分佈會隨場景（近景/遠景）劇烈變化，使用靜態的梯度常數作為邊緣斷離閾值，會導致網格過度碎裂或斷裂不足。若使用 Otsu 演算法，又因為梯度圖屬於長尾分佈而容易產生誤判。
* **決策**：在 `SobelEdgeDetector` 中棄用靜態閾值，改為傳入 `percentile` (預設為 95.0)。實作時利用 NumPy 計算整張梯度矩陣的第 95 百分位數 (95th Percentile) 作為當次運算的動態閾值。大於此數值的像素點才被判定為斷崖。
* **後果**：系統能夠自適應任何圖片的深度尺度，確保每次生成的 3D 網格都只在場景中「深度落差最劇烈的前 5%」發生斷離，維持拓樸的穩定性與自動化能力。

---

**決策ID**：DD-005  
**標題**：採用策略模式實作邊緣判定介面 (Edge Detection Policy)  
**狀態**：Accepted  
**日期**：2026-05-27  

* **情境**：在將 3D 點雲連成網格時，需要決定哪些相鄰像素因為深度落差過大而不該相連。由於未來可能需要切換不同的判定演算法（如 Sobel 梯度、Laplacian 或直接深度百分比），將演算法寫死在幾何處理器中會破壞開閉原則 (OCP)。
* **決策**：定義抽象基底類別 `EdgeDetectionPolicy`。`GeometryProcessor` 在初始化時接收此策略的實例。該策略的唯一職責是接收深度矩陣，並回傳一個標記了斷邊位置的布林遮罩 (Boolean Mask)。
* **後果**：實現了演算法的完全解耦。未來新增 AI 輔助的邊緣偵測時，不需修改任何一行網格生成的底層邏輯。

---

**決策ID**：DD-004  
**標題**：採用嚴格型別與形狀註解的資料契約 (Strictly Typed Data Contracts)  
**狀態**：Accepted  
**日期**：2026-05-27  
**決策者**：System Architect  

* **情境**：Python 屬於動態型別語言。在跨模組傳遞百萬像素的影像與 3D 幾何資料時，若僅傳遞 `numpy.ndarray`，實作工程師極易因為矩陣維度 (Shape) 或資料型態 (dtype) 錯位而引發難以除錯的 Runtime Error。
* **決策**：在 PSM 設計階段，強制規定所有的資料轉移物件 (DTO) 必須使用 `@dataclass`，並且所有 `ndarray` 參數必須在註解中明確標示預期的 `Shape` 與 `dtype`（如 `(H, W, 3), uint8`）。模組邊界必須先驗證這些資料契約。
* **後果**：降低了整合階段的錯誤率。實作時可搭配 `pydantic` 或 `nptyping` 等套件進行靜態/動態型別檢查。

---

**決策ID**：DD-003  
**標題**：基於佇列 (Queue) 的非同步事件通訊協定  
**狀態**：Accepted  
**日期**：2026-05-27  

* **情境**：本機端 Python 引擎需接收外部指令（滑鼠拖曳、旋轉等），但圖形渲染視窗的生命週期與 AI 運算容易發生執行緒阻塞。
* **決策**：採用標準相機外參矩陣 ($4 \times 4$ Extrinsic Matrix) 作為統一通訊 Payload。外部控制器與渲染引擎之間，透過 Thread-safe 的非同步事件佇列 (`queue.Queue`) 傳遞狀態更新。
* **後果**：解耦了外部事件攔截與核心圖形渲染，符合單一職責原則。未來若需支援跨網域控制（如 Web UI），只需在介面適配層額外實作 WebSocket。

---

**決策ID**：DD-002  
**標題**：採用 NumPy 向量化進行網格生成與斷離  
**狀態**：Accepted  
**日期**：2026-05-27  

* **情境**：從 RGB-D 矩陣生成 3D 網格時，若依賴 Python 雙層迴圈處理百萬級像素會導致嚴重超時。此外，需支援自定義的深度邊緣斷離 (Tearing) 邏輯。
* **決策**：棄用傳統迴圈與 Open3D 內建的體積積分重建。採用 NumPy 向量化運算生成頂點與索引，並透過布林遮罩 (Boolean Mask) 直接過濾掉跨越斷崖邊緣的三角形面 (Faces)。
* **後果**：網格生成時間大幅縮短至毫秒級。但矩陣廣播 (Broadcasting) 邏輯較為抽象，需在程式碼中加入詳細註解以利後護。

---

**決策ID**：DD-001  
**標題**：確立無狀態分層模組 (Stateless Layered) 架構  
**狀態**：Accepted  
**日期**：2026-05-27  

* **情境**：影像處理與 3D 渲染系統極易因為狀態過度耦合（例如把相機座標寫死在修補演算法中）而變成難以維護的「拼裝車」。
* **決策**：強制所有幾何引擎與修補模組實作為純函數 (Pure Functions) 或無狀態物件。模組僅接收資料 (如 `RGBDFrame`) 並回傳結果 (如 `SpatialMesh`)，內部不存留相機、視窗或硬體狀態。
* **後果**：極大化程式碼的可測試性與 Git 協作友善度，實現零副作用的資料處理管線。