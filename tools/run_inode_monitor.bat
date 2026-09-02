@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "CONFIG_PATH=%~1"
if "%CONFIG_PATH%"=="" set "CONFIG_PATH=%SCRIPT_DIR%inode_monitor.ini"

set "SERVICE_MODE=%~2"
if "%SERVICE_MODE%"=="" set "SERVICE_MODE="

echo ============================================================
 echo Starting iNode monitor...
 echo Script directory: %SCRIPT_DIR%
 echo Config file: %CONFIG_PATH%
 echo ============================================================

if "%SERVICE_MODE%"=="--service" (
    echo Running in service mode...
    python "%SCRIPT_DIR%run_inode_monitor.py" --service "%CONFIG_PATH%"
) else (
    echo Running in normal mode...
    python "%SCRIPT_DIR%run_inode_monitor.py" "%CONFIG_PATH%"
)

if errorlevel 1 (
    echo.
    echo iNode monitor exited with an error.
    echo Error code: %errorlevel%
    echo.
    echo Press any key to exit...
    pause >nul
    exit /b %errorlevel%
)

echo.
 echo iNode monitor exited normally.
 echo Press any key to exit...
 pause >nul
 exit /b 0
