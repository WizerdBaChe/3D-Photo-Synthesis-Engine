# 階層一：單元測試規範 (Tier 1: Unit Testing)
**文件路徑**：`docs/Testing/01_Unit_Tests.md`
**文件版本**：v1.0 (2026-05-27)

## 1. 驗證範圍
本階層專注於「無狀態模組 (Stateless Modules)」，包含 `GeometryProcessor`、`SobelEdgeDetector` 與 `TeleaInpainter`。測試過程**禁止**啟動 GUI 視窗或佔用真實的 GPU 資源。

## 2. 資料契約斷言規範 (Data Contract Assertions)
| 測試目標 | 輸入模擬 (Mock Data) | 預期斷言 (Expected Assertions) |
| :--- | :--- | :--- |
| **RGBDFrame 建構** | 傳入 $100 \times 100$ 的 color 矩陣與 $50 \times 50$ 的 depth 矩陣。 | 斷言拋出 `ValueError` (驗證維度一致性合約)。 |
| **邊緣判定 (Sobel)** | 傳入 $10 \times 10$ 深度矩陣，左半部為 1.0，右半部為 10.0。 | 斷言輸出的 Mask 矩陣形狀為 $10 \times 10$，且布林值 `True` 僅出現於第 5 行邊界。 |
| **反投影 (Unprojection)** | 傳入 $10 \times 10$ 深度矩陣（全為 1.0），與預設內參。 | 斷言輸出的 `points` 陣列形狀為 $(100, 3)$，且 $Z$ 軸數值全為 1.0。 |
| **網格剔除 (Topology)** | 傳入上述 `points` 與全為 `False` 的 Mask。 | 斷言產出的 `TriangleMesh` 包含精準的 $162$ 個面 ($9 \times 9 \times 2$)。 |
| **網格破洞 (Tearing)** | 傳入一組 Mask，其中包含 4 個相連的 `True` 像素。 | 斷言產出的 `TriangleMesh` 面數小於 $162$，確認破洞物理生成成功。 |

## 3. 測試設計原則
* 利用 `numpy.testing.assert_array_equal` 進行矩陣比對。
* 所有測試函數必須能在 1 秒內於純 CPU 環境執行完畢，確保 CI/CD 管線的極速回饋。