@echo off
setlocal EnableExtensions

REM ============================================================
REM  Project Setup + Validate + Repair
REM  Purpose:
REM    - Validate project structure
REM    - Create missing folders
REM    - Create missing empty files
REM    - Prepare embedded Python folder skeleton
REM  Notes:
REM    - ASCII only, to avoid encoding issues in cmd.exe
REM    - File contents are NOT written here
REM ============================================================

set "ERROR_COUNT=0"
set "FIX_COUNT=0"
set "WARN_COUNT=0"

echo ============================================================
echo  Project Setup + Validate + Repair
echo ============================================================
echo.

REM ------------------------------------------------------------
REM Helper section
REM ------------------------------------------------------------

goto :MAIN

:ENSURE_DIR
if exist "%~1\" (
    echo   [OK] DIR  exists: %~1
) else (
    mkdir "%~1" >nul 2>&1
    if exist "%~1\" (
        echo   [FIX] DIR  created: %~1
        set /a FIX_COUNT+=1
    ) else (
        echo   [ERR] DIR  failed : %~1
        set /a ERROR_COUNT+=1
    )
)
exit /b

:ENSURE_FILE
if exist "%~1" (
    echo   [OK] FILE exists: %~1
) else (
    type nul > "%~1" 2>nul
    if exist "%~1" (
        echo   [FIX] FILE created: %~1
        set /a FIX_COUNT+=1
    ) else (
        echo   [ERR] FILE failed : %~1
        set /a ERROR_COUNT+=1
    )
)
exit /b

:WARN_IF_MISSING
if exist "%~1" (
    echo   [OK] OPT  exists: %~1
) else (
    echo   [WARN] OPT  missing: %~1
    set /a WARN_COUNT+=1
)
exit /b

:MAIN

REM ------------------------------------------------------------
REM 1. Core project directories
REM ------------------------------------------------------------
echo [SECTION] Required directories
call :ENSURE_DIR "src"
call :ENSURE_DIR "src\core"
call :ENSURE_DIR "src\app"
call :ENSURE_DIR "gui"
call :ENSURE_DIR "tests"
call :ENSURE_DIR "tests\unit"
call :ENSURE_DIR "tests\integration"
call :ENSURE_DIR "tests\benchmark"

echo.

REM ------------------------------------------------------------
REM 2. Python package marker files
REM ------------------------------------------------------------
echo [SECTION] Package marker files
call :ENSURE_FILE "src\__init__.py"
call :ENSURE_FILE "src\core\__init__.py"
call :ENSURE_FILE "src\app\__init__.py"
call :ENSURE_FILE "gui\__init__.py"
call :ENSURE_FILE "tests\__init__.py"
call :ENSURE_FILE "tests\unit\__init__.py"
call :ENSURE_FILE "tests\integration\__init__.py"
call :ENSURE_FILE "tests\benchmark\__init__.py"

echo.

REM ------------------------------------------------------------
REM 3. Core placeholder files
REM ------------------------------------------------------------
echo [SECTION] Placeholder source files
call :ENSURE_FILE "src\core\contracts.py"
call :ENSURE_FILE "src\core\policies.py"
call :ENSURE_FILE "src\core\geometry.py"
call :ENSURE_FILE "src\core\inpainting.py"

call :ENSURE_FILE "src\app\commands.py"
call :ENSURE_FILE "src\app\orchestrator.py"
call :ENSURE_FILE "src\app\render_ipc.py"
call :ENSURE_FILE "src\app\adapter.py"

call :ENSURE_FILE "gui\main_window.py"
call :ENSURE_FILE "gui\worker.py"

call :ENSURE_FILE "tests\conftest.py"
call :ENSURE_FILE "tests\unit\test_geometry.py"
call :ENSURE_FILE "tests\unit\test_inpainting_telea.py"
call :ENSURE_FILE "tests\integration\test_orchestrator_fallback.py"
call :ENSURE_FILE "tests\integration\test_render_ipc.py"
call :ENSURE_FILE "tests\benchmark\run_benchmarks.py"

call :ENSURE_FILE "main.py"
call :ENSURE_FILE "requirements.txt"

echo.

REM ------------------------------------------------------------
REM 4. Embedded Python skeleton
REM ------------------------------------------------------------
echo [SECTION] Embedded Python skeleton
call :ENSURE_DIR  "python_embedded"
call :ENSURE_DIR  "python_embedded\Scripts"
call :ENSURE_DIR  "python_embedded\Lib"
call :ENSURE_DIR  "python_embedded\Lib\site-packages"

REM Placeholder files only. Real binaries/content should be added later.
call :ENSURE_FILE "python_embedded\README.txt"
call :ENSURE_FILE "python_embedded\python_env.bat"
call :ENSURE_FILE "python_embedded\get-pip.py"

REM Optional markers for later repair tools
call :WARN_IF_MISSING "python_embedded\python.exe"
call :WARN_IF_MISSING "python_embedded\pythonw.exe"

echo.

REM ------------------------------------------------------------
REM 5. Command availability check
REM ------------------------------------------------------------
echo [SECTION] Command availability

where py >nul 2>&1
if not errorlevel 1 (
    echo   [OK] CMD  found : py
) else (
    echo   [WARN] CMD  missing: py
    set /a WARN_COUNT+=1
)

where python >nul 2>&1
if not errorlevel 1 (
    echo   [OK] CMD  found : python
) else (
    echo   [WARN] CMD  missing: python
    set /a WARN_COUNT+=1
)

where pip >nul 2>&1
if not errorlevel 1 (
    echo   [OK] CMD  found : pip
) else (
    echo   [WARN] CMD  missing: pip
    set /a WARN_COUNT+=1
)

echo.

REM ------------------------------------------------------------
REM 6. Optional future tool files
REM ------------------------------------------------------------
echo [SECTION] Future repair-tool hooks
call :WARN_IF_MISSING "tools"
call :WARN_IF_MISSING "tools\repair"
call :WARN_IF_MISSING "tools\repair\README.txt"

echo.

REM ------------------------------------------------------------
REM 7. Final report
REM ------------------------------------------------------------
echo ============================================================
echo  Repair report
echo ============================================================
echo   Fixed items : %FIX_COUNT%
echo   Warnings    : %WARN_COUNT%
echo   Errors      : %ERROR_COUNT%
echo ============================================================

if %ERROR_COUNT% EQU 0 (
    echo [OK] Structure check completed.
    if %FIX_COUNT% GTR 0 (
        echo [OK] Missing items were repaired where possible.
    ) else (
        echo [OK] No repair was needed.
    )
) else (
    echo [ERR] Some items could not be repaired automatically.
)

echo.
echo Notes:
echo   - This script creates folders and empty placeholder files only.
echo   - It does not write source code into files.
echo   - It does not download embedded Python automatically yet.
echo   - A later repair library can fill file contents and fetch real runtime assets.
echo.
pause
exit /b %ERROR_COUNT%