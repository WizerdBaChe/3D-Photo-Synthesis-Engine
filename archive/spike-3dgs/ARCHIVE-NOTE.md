# archive/spike-3dgs/ — 3DGS spike 工具鏈（已封存）

**封存日期**：2026-08-16（專案結案善後）
**來源**：本地分支 `spike/phase4-3dgs`（從未合併、**沒有遠端副本**）
**結論**：3DGS 換代 **no-go**（2026-06-28）。完整判定見
`references/3D-photo-engine-phase-log.md` 的
「Phase 4 軌道二 — 3DGS Spike（單圖→場景級 3DGS）調研結論」段。

## 為什麼這些檔案在這裡

這四個檔案原本住在 `spike/3dgs/`，而 `spike/` 在專案根 `.gitignore` 裡，
所以它們**只**以 blob 的形式活在 `spike/phase4-3dgs` 分支上，而且
**早已從工作目錄消失**。刪掉那條分支就等於銷毀唯一副本，因此在刪分支之前
把它們搬到這裡。搬檔時把原本的 `.gitignore` 改名為 `gitignore.txt`，
否則它會反過來管到 `archive/`。

| 檔案 | 用途 |
|---|---|
| `README.md` | 硬體規格、候選方案評估、實測表、隔離安裝步驟 |
| `check_env.py` | Gate ①：檢查 torch 是否支援 sm_120 (Blackwell) |
| `run_flash3d.py` | Flash3D 單圖 → `.ply` CLI（已對齊 cloned repo 的真實模組路徑） |
| `gitignore.txt` | 原 `spike/3dgs/.gitignore`（權重/輸出/venv 全排除） |

## 這個 spike 從未跑出結果

torch cu128 的背景安裝**卡住**（網路可達但傳輸停滯，exit 255 中止），
Flash3D 的官方與 fork HF Space 當時**全部掛掉**，所以**沒有產生任何 `.ply`**。
no-go 的依據是**安裝可行性與授權**，不是實測品質——重啟時這一點要記得。

關鍵硬體事實（2026-06 本機）：RTX 5070 Laptop、**8 GiB VRAM**、
**sm_120 (Blackwell)**、driver 610.47。sm_120 在 PyTorch 穩定輪不支援，必須 cu128 或 nightly。

## 大體積殘留物

`archive/spike-3dgs-residue/` 放的是同一次 spike 留下的 49 MB：

- `flash3d/`（37 MB）：`https://github.com/eldar/flash3d.git` 的 clone，**可重新 clone**。
- `.venv-3dgs/`（13 MB）：隔離虛擬環境，內含絕對路徑，**已無法使用**。

兩者都**不進版控**（見根 `.gitignore`）。依「不刪檔、搬進 archive/」的慣例保留；
需要磁碟空間時可以直接刪掉整個 `archive/spike-3dgs-residue/`，不會損失任何無法重建的東西。
