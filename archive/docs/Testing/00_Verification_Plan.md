# 驗證規劃總覽 (Master Verification Plan)
**文件路徑**：`docs/Testing/00_Verification_Plan.md`
**文件版本**：v1.0 (2026-05-27)

## 1. 驗證目標 (Verification Objectives)
本專案為高吞吐量之本機端 3D 圖形應用，基於 V-Model 系統工程法，本計畫旨在驗證「無狀態分層模組架構」與「獨立渲染管線」在 Python (PyTorch/Open3D) 環境下的正確性與穩定性。目標確保系統在 Intel 10 代與獨立顯卡環境下，不發生 OOM (Out of Memory) 崩潰，且畫面更新率達標。

## 2. 測試環境與工具 (Testing Environment & Tools)
| 領域 | 測試框架/工具 | 用途 |
| :--- | :--- | :--- |
| **自動化測試框架** | `pytest` | 執行所有單元與整合測試，驗證資料契約 (Data Contracts)。 |
| **資料模擬 (Mocking)** | `unittest.mock`, `numpy.testing` | 攔截 PyTorch 錯誤、模擬高梯度深度圖矩陣。 |
| **記憶體監控** | `memory_profiler`, `torch.cuda` | 追蹤 Python 主進程 RAM 與 GPU VRAM 的洩漏狀況。 |
| **效能分析** | `cProfile`, `time` | 定位 AI 推論與幾何三角化的 CPU/GPU 耗時瓶頸。 |

## 3. 驗證策略階層 (Verification Tiers)
本計畫採由下而上 (Bottom-Up) 的三層驗證策略：
* **階層一 (Unit Test)**：驗證無狀態純函數的數學正確性（確保 Git 協作時底層邏輯不被破壞）。
* **階層二 (Integration Test)**：驗證跨執行緒/進程的 IPC 佇列與 OOM 容錯降級機制。
* **階層三 (Benchmark)**：驗證端到端 (End-to-End) 系統在真實硬體上的延遲與幀率 (FPS)。