@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "CONFIG_PATH=%~1"
if "%CONFIG_PATH%"=="" set "CONFIG_PATH=%SCRIPT_DIR%inode_monitor.ini"

echo ============================================================
echo Starting iNode monitor service...
echo Script directory: %SCRIPT_DIR%
echo Config file: %CONFIG_PATH%
echo ============================================================

python "%SCRIPT_DIR%run_inode_monitor.py" --service "%CONFIG_PATH%"

if errorlevel 1 (
    echo.
    echo iNode monitor service process exited with an error.
    echo Error code: %errorlevel%
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b %errorlevel%
)

echo.
echo iNode monitor service exited normally.
echo Press any key to exit...
pause >nul
exit /b 0
