# 未來優化方向

基於 MVP v1.0 的實際實作，以下各項均有對應的具體程式位置。
全文分為兩大部分：**功能導向**（使用者感知得到的改善）與**維護性與擴充性**（工程結構的演進）。

---

## 一、功能導向優化

### 1. 遮擋偵測品質提升

**現狀：** `SobelEdgeDetector` 以整張深度圖的第 95 百分位梯度作為單一閾值。對於前景物體輪廓密集的場景（例如多人物、複雜家具），單一閾值容易同時誤判平滑過渡區域與漏判真正的物體邊界，造成網格在視覺上出現不必要的裂縫，或是應裂開的地方反而連成一片。

**建議方向：**

第一步可以在 `policies.py` 中新增 `LocalAdaptiveSobelDetector`，以滑動視窗（例如 32×32 區塊）各自計算百分位數，取代全局單值。這樣前景與背景的深度尺度差異不會互相污染，對 4K 解析度輸入特別有效。

再進一步，可以引入輔助的 RGB 邊緣資訊：在 `RGBDFrame` 中額外計算一張 Canny 邊緣圖，並在 `GeometryProcessor.build_topology()` 中以 AND / OR 邏輯與深度梯度遮罩合并。深度斷崖且 RGB 邊緣也存在的位置，幾乎可以確定是物體輪廓，可以安全裂開；只有其中一者的位置，則保留連接。

---

### 2. LaMa AI 修補器正式整合

**現狀：** `LaMaInpainter.fill()` 目前拋出 `NotImplementedError`，MVP 階段全程使用 Telea。Telea 屬於擴散型演算法，對大面積遮擋（例如移除前景物體後留下的整片背景缺口）會產生明顯模糊與紋理拉伸。

**建議方向：**

最小整合路徑只需補完 `inpainting.py` 中 `LaMaInpainter._load_model()` 與 `_run_inference()` 兩個方法，其餘架構骨架（PERSISTENT/LAZY 雙模式、OOM 降級路徑）都已就緒，不需動其他檔案。

在推論介面上，要注意 LaMa 原生輸入為 `[0,1]` float tensor，需在 `fill()` 內部加入正規化與反正規化的轉換，且輸出要裁切回輸入解析度（LaMa 內部有 padding）。深度圖部分 LaMa 不適用，`_run_inference()` 只處理 color；depth 的遮擋填補仍應保留 Telea 作為後處理，這個雙軌設計正是 DD-007 的設計動機。

---

### 3. 相機視角互動模式擴充

**現狀：** `InputAdapter.on_rotation_slider_changed()` 只支援 Pitch/Yaw/Roll 三個絕對角度的組合，並以 ZYX 順序計算外參矩陣，寫死在一個方法中。使用者無法用滑鼠直接拖曳旋轉視角，也無法平移（Translation）或縮放（Zoom）。

**建議方向：**

在 `adapter.py` 中新增 `on_mouse_drag()` 與 `on_scroll_wheel()` 方法，分別計算旋轉增量矩陣與沿 Z 軸的平移向量，再嵌入 4×4 外參矩陣的對應位置（旋轉部分與平移列）。增量矩陣的優勢在於每次拖曳只計算差值，不需要重算累積旋轉，可避免 Euler 角的萬向節鎖（Gimbal Lock）問題。

`MainWindowView` 只需在中央預覽區域（目前尚無預覽，見第 6 項）連接 `mouseMoveEvent`，再呼叫 Adapter 對應方法即可，View 層不需理解任何矩陣計算。

---

### 4. 暫存檔管理與記憶體壓力

**現狀：** `Orchestrator._save_mesh_to_tempfile()` 每次合成都用 `tempfile.NamedTemporaryFile` 建立新的 `.ply`，並以 `delete=False` 保留。這表示每次按下「開始合成」或重新處理幀，舊的暫存檔不會被自動清除，在長時間使用或批次處理情境下會持續佔用磁碟空間。

**建議方向：**

最簡單的做法是在 `Orchestrator` 中記錄上一次的暫存路徑，在下次寫入前先呼叫 `os.unlink()`。更乾淨的設計是引入一個 `TempFileManager` 類別，以 context manager 模式管理暫存檔的生命週期，並在 `RenderProcessController.load_mesh()` 確認子進程已讀取完畢後（可透過一個 ACK Queue 訊號）再觸發刪除。這樣可以完全避免子進程還在讀取時主進程就刪除的競態條件。

---

### 5. 批次多幀處理

**現狀：** 整個管線設計為單幀輸入：`SynthesisWorker.set_files()` 接收一對 RGB/Depth 路徑，`Orchestrator.process_and_render()` 執行後直接通知渲染器。使用者若要處理一系列連續幀（例如從影片截取的序列），目前只能手動逐幀操作。

**建議方向：**

`Orchestrator` 本身已是無狀態的，天然支援在迴圈中重複呼叫。擴充的主要工作在 `SynthesisWorker.run()` 中：接收一個路徑列表而非單一路徑，在迴圈中依序呼叫 `_load_rgbd()` 與 `orchestrator.process_and_render()`，並透過 `progress_updated` Signal 回報整體進度（例如 `第 3 幀 / 共 10 幀`）。

`commands.py` 中可新增 `BatchSynthesisCommand` DTO，讓 GUI 的「批次模式」按鈕統一打包多筆路徑後透過 `command_queue` 傳入，維持 View is Dumb 原則。

---

### 6. 主視窗預覽區域

**現狀：** `MainWindowView` 目前只有控制面板（滑桿、按鈕、進度條），合成結果完全在獨立的 Open3D 子進程視窗顯示，兩個視窗之間沒有視覺關聯。使用者看不到原始 RGB 圖片與深度圖的縮圖預覽，體驗上有斷層感。

**建議方向：**

在 `gui/main_window.py` 中加入一個 `QLabel` 預覽區，使用 `QPixmap` 顯示載入後的 RGB 縮圖。這完全在 GUI 層完成，不需要修改任何核心模組。

進一步可以在 `SynthesisWorker` 完成邊緣偵測後，透過新增一個 `Signal(np.ndarray)` 將斷邊遮罩的疊加圖傳回主視窗顯示，讓使用者在 3D 合成結果出現前就能確認斷邊偵測是否合理，降低「按下去等很久才發現參數不對」的挫折感。

---

## 二、維護性與擴充性優化

### 7. 消除 `Orchestrator._inpaint_with_fallback` 中的字串比對耦合

**現狀：** OOM 降級的觸發條件是 `"out of memory" in str(e).lower()`，這是一個對 PyTorch 錯誤訊息格式的隱性假設。若 PyTorch 未來修改訊息格式（例如改為 `"insufficient memory"` 或增加前綴），降級機制會靜默失效，且沒有任何測試能在第一時間發現。

**建議方向：**

在 `inpainting.py` 中定義一個專屬的例外類別：

```python
class VRAMExhaustedError(RuntimeError):
    """顯存耗盡，需要觸發降級備案。"""
    pass
```

`LaMaInpainter.fill()` 在捕捉到 PyTorch OOM 後，重新包裝並拋出 `VRAMExhaustedError`。`Orchestrator._inpaint_with_fallback()` 改為捕捉 `VRAMExhaustedError`，不再依賴字串內容。這樣錯誤分類的責任在最了解 PyTorch 行為的修補模組內部，Orchestrator 只需關心業務語意。

---

### 8. `RenderProcessController.update_camera()` 的競態條件

**現狀：** `update_camera()` 的 Latest-Wins 實作是一個「清空 → 重新放回非位姿指令 → 放入新位姿」的序列，整個過程沒有鎖。在主進程同時有多個執行緒存取 `command_queue` 的情境下（例如未來 Orchestrator 也透過同一個 Queue 傳遞指令），可能在「清空到放入新指令」的空窗期遺失其他執行緒剛剛塞入的指令。

**建議方向：**

最直接的修正是為 `RenderProcessController` 加入一個 `threading.Lock`，在 `update_camera()` 的清空-重填-放入整個序列上加鎖。這不影響任何公開介面，只是在 `__init__` 中加入 `self._queue_lock = threading.Lock()` 並在 `update_camera()` 中以 `with self._queue_lock:` 包裹關鍵區段。

更長遠的方向是把 Latest-Wins 邏輯移進子進程側：`Open3DRenderWorker` 的事件迴圈在每次 `poll_events()` 前把 Queue 排空，只取最後一個 `CameraPoseCommand` 執行，主進程側的 `update_camera()` 就退化為單純的 `put()`，徹底消除競態條件。

---

### 9. `SynthesisWorker` 中的相機內參硬編碼

**現狀：** `SynthesisWorker._estimate_intrinsics()` 以固定 FOV 60° 估算內參，用一個靜態方法藏在 Worker 中。這使得「相機內參來源」的業務邏輯散落在 GUI 層（Worker 屬於 Layer 0），而不是在核心層或設定層中統一管理。

**建議方向：**

定義一個 `IntrinsicsProvider` 策略介面（類比 `EdgeDetectionPolicy`），包含 `get_intrinsics(frame: RGBDFrame) -> CameraIntrinsics` 方法。提供兩個實作：`FovEstimator`（現有邏輯）與 `ExifReader`（從圖片 EXIF 讀取焦距）。`SynthesisWorker` 在初始化時注入 `IntrinsicsProvider`，移除靜態方法，讓整體設計對稱於 `EdgeDetectionPolicy` 的模式，降低認知成本。

---

### 10. `EngineCommand.payload` 的型別安全問題

**現狀：** `commands.py` 中 `EngineCommand.payload` 的型別標注為 `Dict[str, Any]`，鍵名（如 `"rgb"`、`"depth"`）和值的型別在傳送端與接收端沒有任何靜態約束。若傳送端拼錯鍵名，錯誤只會在 `SynthesisWorker.run()` 內部嘗試存取時以 `KeyError` 爆出，且沒有任何 IDE 提示。

**建議方向：**

為每個 `EngineCommandType` 定義對應的具名 payload DTO：

```python
@dataclass(frozen=True)
class LoadImagePayload:
    rgb_path:   str
    depth_path: str
```

`EngineCommand` 改為泛型 `EngineCommand[T]`，或直接廢棄 `payload: Dict` 改用 `Union[LoadImagePayload, ...]`。這項改動不影響 Queue 通訊機制，只影響 `commands.py`、`adapter.py` 中的打包端，以及 `worker.py` 中的解包端，範圍明確且不跨層。

---

### 11. `.ply` 暫存檔與子進程的生命週期耦合

**現狀：** `_save_mesh_to_tempfile()` 的暫存路徑被放入 Queue 後，主進程就失去對該路徑的追蹤。子進程 `Open3DRenderWorker._load_mesh_from_file()` 在讀取完畢後也不會通知主進程，主進程無從得知何時可以安全刪除該檔案。兩端對暫存檔的生命週期認知完全不對稱。

**建議方向：**

在 `render_ipc.py` 中增加一個反向的 `ack_queue: mp.Queue`，子進程在成功讀取 `.ply` 後，發送一個 `MeshLoadedAck(filepath=...)` 訊號回主進程。`RenderProcessController` 在收到 ACK 後呼叫 `os.unlink(filepath)`，完成暫存檔的清理。這個改動把目前「假設子進程已讀完」的隱性假設，變成一個有明確訊號確認的協議，也讓未來的除錯（例如磁碟空間異常增長）有跡可循。

---

### 12. 測試覆蓋率的三個缺口

**現狀：** 目前測試對以下三條路徑尚無覆蓋，未來重構時容易在沒有測試保護的情況下破壞行為：

第一，`InputAdapter.on_rotation_slider_changed()` 的旋轉矩陣計算沒有數值驗證測試。可以用已知的純 Pitch/Yaw/Roll 旋轉（例如 Pitch=90° 對應 Y↔Z 軸互換）驗算輸出矩陣的前三列，確保 ZYX 旋轉順序沒有在重構中被意外改變。

第二，`Open3DRenderWorker._update_camera_pose()` 沒有整合測試，因為它依賴真實的 Open3D `Visualizer` 物件。可以透過引入一個 `VisualizerProtocol` 介面（只定義 `get_view_control()` 等方法），讓 `Open3DRenderWorker` 依賴介面而非具體類別，使測試時可以注入 Mock Visualizer，完全不需要顯示器。

第三，`SynthesisWorker._load_rgbd()` 的解析度對齊邏輯（RGB 與 Depth 尺寸不同時自動 resize）沒有測試。當前的 `conftest.py` Fixture 只提供尺寸一致的合成資料，需補充一個尺寸不一致的 Fixture 來覆蓋這條路徑。

---

### 13. 日誌結構化與可觀測性

**現狀：** 各模組的 `logger.info()` 輸出為純字串（例如 `"斷邊偵測完成，斷崖像素數: 1234"`），在開發時容易閱讀，但在生產環境中若要用 log 聚合工具（Elasticsearch、Loki）做統計或設定 alert，純字串格式難以解析。

**建議方向：**

在不改變任何模組邏輯的前提下，於 `main.py` 的 `logging.basicConfig()` 替換為結構化 JSON handler（例如使用 `python-json-logger`），讓每一條 log 輸出包含 `module`、`event`、`elapsed_ms` 等固定欄位。各模組的 `logger.info()` 調用保持不動，只需在進入點切換 formatter，改動範圍極小。
