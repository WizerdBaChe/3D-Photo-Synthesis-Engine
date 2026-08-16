# 環境清理報告 — 2026-08-16

**模式**：env-cleanup Mode B（專案工作目錄）
**對象**：`D:\AIWork\3D_Photo_Synthesis_Engine`（已結案專案，結案後整理）
**執行**：主 session（Opus 5，L1）
**與慣例的差異**：本 skill 的預設是「封存不刪除」。**本輪使用者明確裁定改為刪除**
（原話：「殘留那 49MB 直接刪掉 還有其他類似的狀況也處理，保持到整個項目乾淨」），
故所有項目皆為**可重建**類別，並在下方逐項附還原方式。

**結果**：工作目錄 **348 MB → 3.0 MB**（`archive/` 從 50 MB 降到 325 KB）。
分兩批：第一批刪殘留與快取（348 → 294 MB），第二批依使用者第二次裁定
（「現在就刪」）移除建置環境（294 → 3.0 MB）。

---

## 一、已刪除

| 路徑 | 大小 | 分類理由 | 怎麼還原 |
|---|---|---|---|
| `archive/spike-3dgs-residue/flash3d/` | 37 MB | 第三方 repo 的 clone，從未進版控 | `git clone https://github.com/eldar/flash3d.git` |
| `archive/spike-3dgs-residue/.venv-3dgs/` | 13 MB | 隔離虛擬環境，內含絕對路徑，**已無法使用** | 依 `archive/spike-3dgs/README.md`〈安裝（隔離 venv）〉重建 |
| `frontend/.vite/` | 3.7 MB | Vite 相依快取（gitignored，可重生） | 下次 `npm run dev` / `npm run build` 自動重建 |
| `frontend/dist/` | 928 KB | 前端建置輸出（gitignored，可重生） | `cd frontend && npm run build` |
| `.pytest_cache/` | 20 KB | pytest 快取（gitignored，可重生） | 下次 `pytest` 自動重建 |
| `__pycache__/` ×7 | 少量 | Python bytecode 快取（gitignored，可重生） | 下次 import 自動重建 |
| `.claude/`（空目錄） | 0 B | 搬檔後留下的空殼，內容物為零 | Claude Code 需要時會自行建立 |

> 七個 `__pycache__` 位於 `backend/`、`src/`、`src/app/`、`src/core/`、`tests/`、
> `tests/unit/`、`tests/integration/`。其餘 51 個原本在被刪掉的 `.venv-3dgs` 裡。

## 二、跟著刪除一併修掉的懸空引用

刪掉 `archive/spike-3dgs-residue/` 會讓三處指向它的敘述變成假話，一併更正：

| 檔案 | 原本寫的 | 改成 |
|---|---|---|
| `.gitignore` | 註解 + `archive/spike-3dgs-residue/` 忽略規則 | 註解改為「已刪除（可重建）」，移除該忽略規則 |
| `archive/README.md` | 表格列出 `spike-3dgs-residue/` 為封存項目 | 改列本清理批次目錄；說明殘留物是**刪除**不是封存 |
| `archive/spike-3dgs/ARCHIVE-NOTE.md` | 「殘留物放在 `archive/spike-3dgs-residue/`」 | 改為刪除紀錄 + 兩條還原指令 |

## 三、掃描結果：沒有其他候選

依 Mode B 啟發式（`references/project-heuristics.md` §2）逐項掃過，**全部為零**：

| 訊號 | 結果 |
|---|---|
| 未追蹤又未被 ignore 的散落檔（>14 天） | 0（`git status --porcelain -uall` 為空） |
| 編輯器／OS 垃圾（`*.tmp`/`*.swp`/`*.bak`/`.DS_Store`/`Thumbs.db`/`*.orig`） | 0 |
| 重複命名殘骸（`* (1).*`/`*_old.*`/`*副本*`） | 0 |
| 根目錄一次性產物（`*.png`/`*.log`/`*-report.md`，>14 天） | 0 |
| gitignore 有規則但實際存在的產物（`*.glb`/`*.zip`/`benchmark_report.json`/`debug_out/`） | 0 |

這個 repo 本來就不髒——唯一的髒點是那 49 MB，而它之所以存在，是因為它躲在一條
gitignored 的路徑（`spike/`）底下，`git status` 永遠看不到它。

## 四、第二批：建置環境（使用者裁定「現在就刪」）

`engine.bat clean` 是互動式的（`set /p OK=`），故直接執行它的三個目標：

| 路徑 | 大小 | 怎麼還原 |
|---|---|---|
| `.venv/` | 213 MB | `engine.bat install` |
| `frontend/node_modules/` | 79 MB | `engine.bat install`（或 `cd frontend && npm install`）|
| `frontend/dist/` | — | 第一批已刪 |

**這次刪除的已知代價（明說，不埋起來）**：`parallax.ts` 的 `onShaderError` 改動
**仍有一份未執行的人眼驗收清單**（Document 1 文末，8 步，含第 8 步的負向控制），
而執行它需要這兩個目錄。刪除後要驗收，得先跑一次 `engine.bat install`（要網路、數分鐘）。
使用者在知道這個代價的前提下裁定刪除，本行是紀錄，不是異議。

## 五、保留（未動）

| 路徑 | 大小 | 為什麼保留 |
|---|---|---|
| `.idea/` | 19 KB | 使用者的 IDE 設定，gitignored，非本 skill 的處置對象 |
| `archive/docs/`、`archive/spike-3dgs/`、`archive/3D_Photo_Synthesis_Engine_DesignPaper.md` | 325 KB | 刻意封存的歷史文件，進版控 |
| `samples/`、`frontend/public/samples/` | 324 KB | 測試範例圖，程式碼與 UI 皆引用（`載入測試範例圖` 按鈕）|
| `.git/` | 1.5 MB | 版本庫本身。清完之後它是工作目錄裡最大的東西 |

**體積離群值（>50 MB）：清理後為零。**

## 六、還原總指令

把這個 repo 從 3.0 MB 變回可執行狀態，只要一行：

```powershell
cd D:\AIWork\3D_Photo_Synthesis_Engine
.\engine.bat install
```

它會重建 `.venv`、裝後端依賴、跑 `npm install`。之後 `.\engine.bat run` 就能起前後端。
快取（`.vite` / `dist` / `.pytest_cache` / `__pycache__`）不必手動處理，執行時自動重生。

若哪天真要回頭做 3DGS：

```powershell
git clone https://github.com/eldar/flash3d.git
```

隔離 venv 的重建步驟見 `archive/spike-3dgs/README.md`。
**注意**：那份 README 的相容性敘述停在 2026-06（sm_120 當時不在 PyTorch 穩定輪），
重跑前要重新確認現況。

隔離 venv 的重建步驟見 `archive/spike-3dgs/README.md`。
**注意**：那份 README 的相容性敘述停在 2026-06（sm_120 當時不在 PyTorch 穩定輪），
重跑前要重新確認現況。
