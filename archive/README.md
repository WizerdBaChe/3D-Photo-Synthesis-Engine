# archive/

已封存的文件與資料，保留供歷史參照，不再是日常工作的參考來源。

| 路徑 | 封存原因 |
|------|---------|
| `3D_Photo_Synthesis_Engine_DesignPaper.md` | 原始整合設計文件（桌面版 v1.0），Web v2.0 架構已由 `DEV_README.md` + `CLAUDE.md` 取代 |
| `docs/PIM/` | PIM 規格，已融入設計文件；Web 版實作以 `src/core/` + `backend/` 為準 |
| `docs/PSM/` | PSM 分章規格（桌面版），Web 版架構已有重大分歧，以 `DEV_README.md` 為準 |
| `docs/Testing/` | 桌面版測試規格，已由 `tests/` 實際測試套件取代 |
| `docs/ToDesign/` | 設計文件的 AI 閱讀優化分流版，來源文件已封存，不再維護 |
| `docs/claude-instructions-LDI.md` | LDI 工作的 Claude 指令草稿，內容已正式合入 `CLAUDE.md` |
| `docs/重製注意事項.md` | 桌面→Web 遷移的修正清單，所有項目已完成（2026-06-23）|
| `docs/前端UX檢視報告.md` | 一次性 UX 審查報告（2026-06-23），已供參考使用完畢 |
| `docs/專案架構設計與系統工程總結轉交文件.md` | 桌面版架構總結交接文件，Web 版後已失效 |
| `spike-3dgs/` | 3DGS spike 的工具鏈（README / check_env.py / run_flash3d.py）。結論 no-go；**原本只存在於未合併且無遠端副本的 `spike/phase4-3dgs` 分支上**，2026-08-16 刪分支前搬來。**進版控**，說明見 `spike-3dgs/ARCHIVE-NOTE.md` |
| `spike-3dgs-residue/` | 同一次 spike 的 49 MB 殘留：`flash3d/`（可重新 clone）與 `.venv-3dgs/`（含絕對路徑，已失效）。**不進版控**（根 `.gitignore`）；需要空間時可整個刪除，不損失無法重建的東西 |

`spike/` 目錄已於 2026-08-16 清空並移入本資料夾；根 `.gitignore` 仍保留該規則。
