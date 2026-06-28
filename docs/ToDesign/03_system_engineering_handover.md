# 3D Photo Synthesis Engine 系統工程交接主體

文件角色：System Engineering Handover & Governance

內容來源：原主文件第五部分。

AI 閱讀指引：
- 若問題涉及團隊協作模式、設計推進習慣、避坑指南、Mandatory Rules、Code Review 紅線，請優先讀本文件。
- 本文件不是核心設計規格本體，而是治理規範、交接背景與工程實務導向說明。

# 第五部分：系統工程總結轉交文件 (System Engineering Summary)

## 一、對話模式與協作習慣分析

回顧整個架構設計過程，推進模式呈現出以下高度規律的特徵，也是本專案能維持高質量的關鍵：

**Top-Down 抽象到具象 (PIM to PSM)：**

始終堅持「先定義邏輯與資料流 (PIM)，再決定技術棧與介面 (PSM)」。這有效避免了被特定硬體或函式庫綁架。

**文件化與版本控制推動：**

強制要求導入 ADR（設計決策日誌）並嚴格標記文件版本。這讓每一次架構轉向（如導入 LaMa、改用並行處理）都有跡可循，避免了「為何當初這樣寫」的技術債。

**批判性思考與邊界碰撞：**

具備極強的防禦性設計思維（例如質疑 API 路由、日誌、管線規劃）。這種「刻意找碴」的過程，促使釐清了「本機圖形運算」與「Web 雲端微服務」的本質差異，成功收斂出最適合本專案的架構。

**步步為營 (No Jumping Ahead)：**

多次踩煞車（「莫忘你是在設計 PSM，不要跟實作混一起」、「先完整規劃 PSM 才做驗證」），確保每一層的合約（Contract）都簽署完畢後，才進入下一層。

## 二、避坑指南與決策覆盤 (Lessons Learned)

### 避坑 1：過早陷入演算法實作細節

* 情境：在處理深度斷層時，很容易直接去寫迴圈判斷像素。
* 解法：透過定義 EdgeDetectionPolicy 介面，將邊緣判定抽象化為策略模式。這讓我們順利過渡到使用 NumPy 向量化與百分位數 (Percentile) 動態計算，解決了效能瓶頸與場景適應性問題。

### 避坑 2：錯把 Web 架構套用於本機圖形運算 (Over-engineering)

* 情境：系統擴充性考量下，一度考慮引入 API 層與路由排程。
* 解法：及時踩煞車。認清了處理高解析度 NumPy 矩陣時，序列化 (Serialization) 與網路通訊會帶來災難性延遲。最終拍板採用零拷貝的記憶體指標與 multiprocessing.Queue 進行 IPC 通訊。

### 避坑 3：忽略 GUI 與 3D 渲染的底層互斥性

* 情境：PySide6 (GUI) 與 Open3D (渲染) 都強制要求佔用 Main Thread。
* 解法：在 PSM 最終章果斷切分進程邊界。GUI 與 AI 留在主進程（區分主/副執行緒），Open3D 則完全隔離至獨立的子進程 (Sub-Process)。

### 避坑 4：AI 顯存的樂觀偏見 (OOM 危機)

* 情境：高畫質 LaMa 修補會輕易吃光 8GB VRAM 導致軟體閃退。
* 解法：設計了「常駐 (Persistent) / 用完即丟 (Lazy)」雙模式，並強制在 Orchestrator 實作 try...except RuntimeError 的 Telea 降級備案 (Fallback)。

## 三、系統工程核心規則 (Mandatory Rules)

未來的實作工程師（Developers）必須無條件遵守以下架構規則：

### 規則一：純粹的無狀態分層模組 (Stateless Layered Modules)

所有的幾何處理（GeometryProcessor）與 AI 修補（AbstractInpainter）必須是純函數或無狀態物件。只允許吃 DTO，吐 DTO。模組內部絕對禁止存留 GUI 狀態、相機座標或全域變數。

### 規則二：嚴格的資料契約 (Strict Data Contracts)

* 跨模組通訊只能使用 @dataclass 封裝的物件（如 RGBDFrame, CameraPoseUpdate）。
* 對於 numpy.ndarray 與 torch.Tensor，必須在程式碼中明確註解其 Shape 與 dtype（例：(H, W, 3), np.uint8）。

### 規則三：UI 只做映射 (View is Dumb)

PySide6 畫面元件不允許包含任何業務邏輯。滑桿與按鈕只能觸發 Signal，交由 InputAdapter 翻譯成數學矩陣或指令後，丟進通訊佇列。

### 規則四：攜帶式環境優先 (Portable First)

系統必須能在類似 ComfyUI_portable 的免安裝嵌入式 Python 環境中運行。所有路徑引用必須使用相對路徑，禁止寫死絕對路徑或依賴系統全域環境變數。

## 四、絕對紅線 (Absolute Red Lines — Code Review Veto)

**⚠️ 紅線 1：阻塞主執行緒**

任何會在 GUI 主執行緒中執行超過 16ms 的運算，都屬於不可接受的架構違規。

**⚠️ 紅線 2：跨模組直接傳裸 ndarray / Tensor 且無契約說明**

任何未經 DTO 封裝、未標註 Shape / dtype 的大型資料流，視為高風險整合缺陷。

**⚠️ 紅線 3：GUI 直接呼叫 AI / Geometry 核心**

前端不得跳過 Adapter / Queue 邊界直接操控核心模組。

**⚠️ 紅線 4：透過 Queue 直接傳遞大型 3D Mesh 物件**

這將造成序列化與 IPC 瓶頸，屬於需被否決的實作方式。
