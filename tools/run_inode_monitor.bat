@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "CONFIG_PATH=%~1"
if "%CONFIG_PATH%"=="" set "CONFIG_PATH=%SCRIPT_DIR%inode_monitor.ini"

python "%SCRIPT_DIR%run_inode_monitor.py" "%CONFIG_PATH%"

if errorlevel 1 (
    echo.
    echo iNode monitor exited with an error.
    exit /b %errorlevel%
)

exit /b 0
