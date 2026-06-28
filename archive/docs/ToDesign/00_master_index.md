# 3D Photo Synthesis Engine 文件主索引

文件版本：v1.0（AI 閱讀優化分流版）

來源文件：`3D_Photo_Synthesis_Engine_DesignPaper.md`

重整原則：
- 不增刪原始技術內容。
- 僅做分流、重排、標題層級與閱讀導引優化。
- 目標為提升 AI 與工程人員在多輪任務中的定位、引用與交叉比對效率。

## 文件分流結構

### 1. 核心設計主體
- `01_core_design.md`
- 內容範圍：PIM、PSM、ADR。
- 用途：作為正式設計與架構決策的主要權威文件。

### 2. 驗證與測試主體
- `02_verification_testing.md`
- 內容範圍：Verification & Testing 全部內容。
- 用途：獨立承載驗證策略、測試規範、基準測試與測試藍圖。

### 3. 系統工程交接主體
- `03_system_engineering_handover.md`
- 內容範圍：System Engineering Summary 全部內容。
- 用途：承載協作習慣、避坑指南、核心規則與審查紅線。

### 4. 整合附錄
- `04_appendix_integration_notes.md`
- 內容範圍：原文件中的整合註記、已知問題、補充說明與非主規格性內容。
- 用途：保留脈絡，但避免干擾主規格抽取。

## AI 閱讀建議

### 建議查詢順序
1. 若要理解系統架構與模組責任，先讀 `01_core_design.md`。
2. 若要檢查測試完備性、驗證邊界與 SLA，讀 `02_verification_testing.md`。
3. 若要理解團隊規範、架構紅線與交接意圖，讀 `03_system_engineering_handover.md`。
4. 若要查整合脈絡與保留備註，讀 `04_appendix_integration_notes.md`。

### 建議提示詞引用方式
- 請直接用章節 ID 或檔名定位，例如：
  - `在 01_core_design.md 中，找 PSM Phase 4 與 ADR DD-008 的對應關係。`
  - `在 02_verification_testing.md 中，整理 Tier 2 的容錯測試情境。`
  - `在 03_system_engineering_handover.md 中，列出所有 Mandatory Rules。`

## 分層優化說明

本次重整主要解決以下問題：
- 將正式設計規格與測試規格分離。
- 將架構主體與治理/交接性內容分離。
- 降低單一巨型文件中多種資訊型態混雜造成的檢索噪音。
- 保留原始內容，但提升章節權威性與段落可尋址性。
