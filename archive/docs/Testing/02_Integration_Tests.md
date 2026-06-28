# 階層二：整合與容錯測試規範 (Tier 2: Integration & Fallback)
**文件路徑**：`docs/Testing/02_Integration_Tests.md`
**文件版本**：v1.0 (2026-05-27)

## 1. 驗證範圍
驗證 `Orchestrator` (協調層) 的管線流轉、AI 模型降級機制，以及 `RenderProcessController` 的跨進程通訊防呆機制。

## 2. 容錯與狀態斷言規範 (State & Error Assertions)
| 測試情境 (Scenario) | 執行動作與 Mock 設置 | 預期斷言 (Expected Assertions) |
| :--- | :--- | :--- |
| **AI 記憶體爆滿降級** | 攔截 `LaMaInpainter.fill()`，強制拋出 `RuntimeError("CUDA out of memory")`。 | 斷言 `Orchestrator` 捕捉異常、`TeleaInpainter` 被自動呼叫，並成功回傳無破洞的 `RGBDFrame`。 |
| **LAZY 模式記憶體釋放** | 實例化 `LaMaInpainter(strategy=LAZY)` 並執行一次修補。 | 斷言執行前後的 `torch.cuda.memory_allocated()` 數值完全一致 (確認無洩漏)。 |
| **IPC 佇列擠壓防護** | 向 `RenderProcessController.command_queue` 連續寫入 10,000 個相機位姿指令。 | 啟動子進程後，斷言佇列能在 0.5 秒內被清空或只讀取最新值，不發生阻塞死鎖。 |
| **子進程安全關閉** | 呼叫 `RenderProcessController.terminate()`。 | 斷言 `render_process.is_alive()` 在 2 秒內變為 `False`，無殭屍進程 (Zombie Process) 殘留。 |

## 3. 測試設計原則
* 本階層允許載入輕量級神經網路權重進行測試，但仍以 `unittest.mock` 控制例外狀況為主。
* 針對跨進程測試，需加入超時機制 (`pytest.mark.timeout`) 避免死鎖導致測試卡死。