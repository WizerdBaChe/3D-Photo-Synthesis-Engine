@echo off
setlocal EnableDelayedExpansion
chcp 65001 > nul

REM ============================================================
REM  3D Photo Synthesis Engine — 前後端總控腳本
REM ------------------------------------------------------------
REM    engine.bat            顯示選單
REM    engine.bat install    建立 .venv + 裝後端依賴 + 前端 npm install
REM    engine.bat repair     檢查/修復環境（缺什麼補什麼，可重複執行）
REM    engine.bat run        開發模式：分別開啟「後端」「前端」兩個 console
REM    engine.bat backend    只啟動後端 (FastAPI, :8000)
REM    engine.bat frontend   只啟動前端 (Vite, :5173)
REM    engine.bat test       後端 pytest + 前端 build typecheck
REM    engine.bat clean      刪除 .venv / node_modules / dist
REM ============================================================

set "ROOT=%~dp0"+
set "VENV=%ROOT%.venv"
set "VPY=%VENV%\Scripts\python.exe"
set "FRONTEND=%ROOT%frontend"
set "PYTHONPATH=%ROOT%"

REM --- 偵測系統 Python（建立 venv 用，優先 py -3）---
set "SYSPY="
where py >nul 2>&1 && set "SYSPY=py -3"
if not defined SYSPY ( where python >nul 2>&1 && set "SYSPY=python" )

if "%~1"==""        goto :MENU
if /i "%~1"=="install"  goto :INSTALL
if /i "%~1"=="repair"   goto :REPAIR
if /i "%~1"=="run"      goto :RUN
if /i "%~1"=="backend"  goto :BACKEND
if /i "%~1"=="frontend" goto :FRONTEND
if /i "%~1"=="test"     goto :TEST
if /i "%~1"=="clean"    goto :CLEAN
echo [ERROR] 未知參數：%~1
echo         可用：install / repair / run / backend / frontend / test / clean
exit /b 1


:MENU
echo.
echo  ╔════════════════════════════════════════════════╗
echo  ║   3D Photo Synthesis Engine  (Web v2.0)        ║
echo  ╠════════════════════════════════════════════════╣
echo  ║  1. install   首次安裝（.venv + 兩端依賴）      ║
echo  ║  2. repair    檢查/修復環境                     ║
echo  ║  3. run       開發模式（前後端各一視窗）         ║
echo  ║  4. backend   只啟動後端 (:8000)               ║
echo  ║  5. frontend  只啟動前端 (:5173)               ║
echo  ║  6. test      跑測試                            ║
echo  ║  7. clean     清除環境                          ║
echo  ║  0. 離開                                        ║
echo  ╚════════════════════════════════════════════════╝
set /p CHOICE= 請輸入選項 [0-7]：
if "%CHOICE%"=="1" goto :INSTALL
if "%CHOICE%"=="2" goto :REPAIR
if "%CHOICE%"=="3" goto :RUN
if "%CHOICE%"=="4" goto :BACKEND
if "%CHOICE%"=="5" goto :FRONTEND
if "%CHOICE%"=="6" goto :TEST
if "%CHOICE%"=="7" goto :CLEAN
if "%CHOICE%"=="0" exit /b 0
echo [WARN] 無效選項。
exit /b 1


:INSTALL
echo.
echo [INSTALL] ── 建立後端虛擬環境 .venv ───────────────────
if not defined SYSPY (
    echo [FAIL] 找不到系統 Python，請先安裝 Python 3.10+（含 py launcher）。
    pause & exit /b 1
)
if not exist "%VPY%" (
    echo   建立 .venv ...
    %SYSPY% -m venv "%VENV%"
    if !errorlevel! neq 0 ( echo [FAIL] venv 建立失敗。& pause & exit /b 1 )
) else (
    echo   .venv 已存在，略過建立。
)
echo   升級 pip 並安裝後端依賴 ...
"%VPY%" -m pip install --upgrade pip
"%VPY%" -m pip install -r "%ROOT%requirements.txt"
if !errorlevel! neq 0 ( echo [FAIL] 後端依賴安裝失敗。& pause & exit /b 1 )

echo.
echo [INSTALL] ── 安裝前端依賴 (npm install) ──────────────
where npm >nul 2>&1
if !errorlevel! neq 0 (
    echo [WARN] 找不到 npm，跳過前端安裝。請安裝 Node.js 18+ 後再執行 engine.bat frontend。
) else (
    pushd "%FRONTEND%"
    call npm install
    popd
    if !errorlevel! neq 0 ( echo [FAIL] 前端依賴安裝失敗。& pause & exit /b 1 )
)
echo.
echo [INSTALL] 完成！可執行 engine.bat run 啟動開發環境。
if "%~1"=="" pause
exit /b 0


:REPAIR
echo.
echo [REPAIR] ── 環境檢查 ────────────────────────────────
set "NEED_FIX="

echo  [1/4] 系統 Python ...
if defined SYSPY ( %SYSPY% --version ) else ( echo    [MISS] 系統 Python 未安裝 & set "NEED_FIX=1" )

echo  [2/4] 後端 .venv ...
if exist "%VPY%" (
    "%VPY%" --version
    "%VPY%" -c "import fastapi, uvicorn, numpy, cv2; print('    後端依賴 OK')" 2>nul || ( echo    [MISS] 後端依賴不全 & set "NEED_FIX=1" )
) else ( echo    [MISS] .venv 不存在 & set "NEED_FIX=1" )

echo  [3/4] 核心模組可 import ...
if exist "%VPY%" (
    "%VPY%" -c "from src.core.geometry import GeometryProcessor; from backend.app import app; print('    backend.app OK')" 2>nul || ( echo    [MISS] 核心/後端 import 失敗 & set "NEED_FIX=1" )
)

echo  [4/4] 前端 node_modules ...
if exist "%FRONTEND%\node_modules" ( echo    node_modules OK ) else ( echo    [MISS] 前端未安裝 & set "NEED_FIX=1" )

echo.
if defined NEED_FIX (
    echo [REPAIR] 偵測到缺失，執行 install 進行修復 ...
    goto :INSTALL
) else (
    echo [REPAIR] 環境完整，無需修復。
)
if "%~1"=="" pause
exit /b 0


:RUN
if not exist "%VPY%" ( echo [ERROR] 尚未安裝，請先執行 engine.bat install。& pause & exit /b 1 )
echo.
echo [RUN] 開發模式：開啟兩個獨立 console（各自顯示錯誤狀態）
echo   後端 → http://127.0.0.1:8000   (API 文件 /docs)
echo   前端 → http://127.0.0.1:5173
echo.
start "PSE Backend (FastAPI :8000)" cmd /k ""%VPY%" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload"
start "PSE Frontend (Vite :5173)" cmd /k "cd /d "%FRONTEND%" && npm run dev"
echo [RUN] 已啟動。關閉各自視窗即可停止對應服務。
exit /b 0


:BACKEND
if not exist "%VPY%" ( echo [ERROR] 尚未安裝，請先執行 engine.bat install。& pause & exit /b 1 )
echo [BACKEND] FastAPI → http://127.0.0.1:8000  (Ctrl+C 停止)
"%VPY%" -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --reload
exit /b %errorlevel%


:FRONTEND
echo [FRONTEND] Vite → http://127.0.0.1:5173  (Ctrl+C 停止)
pushd "%FRONTEND%"
call npm run dev
popd
exit /b %errorlevel%


:TEST
if not exist "%VPY%" ( echo [ERROR] 尚未安裝，請先執行 engine.bat install。& pause & exit /b 1 )
echo.
echo [TEST] ── 後端 pytest ───────────────────────────────
"%VPY%" -m pytest tests/unit tests/integration -v --timeout=60
set "BACK_RC=!errorlevel!"
echo.
echo [TEST] ── 前端 build typecheck ───────────────────────
where npm >nul 2>&1
if !errorlevel! == 0 (
    pushd "%FRONTEND%"
    call npm run build
    set "FRONT_RC=!errorlevel!"
    popd
) else ( echo [WARN] 無 npm，略過前端檢查。& set "FRONT_RC=0" )
echo.
if "!BACK_RC!"=="0" if "!FRONT_RC!"=="0" ( echo [TEST] 全部通過。) else ( echo [TEST] 有失敗，請查看上方輸出。)
if "%~1"=="" pause
exit /b 0


:CLEAN
echo.
echo [CLEAN] 將刪除 .venv / frontend\node_modules / frontend\dist
set /p OK= 確定？ [y/N]：
if /i not "%OK%"=="y" ( echo 已取消。& exit /b 0 )
if exist "%VENV%" rmdir /s /q "%VENV%"
if exist "%FRONTEND%\node_modules" rmdir /s /q "%FRONTEND%\node_modules"
if exist "%FRONTEND%\dist" rmdir /s /q "%FRONTEND%\dist"
echo [CLEAN] 完成。
if "%~1"=="" pause
exit /b 0
