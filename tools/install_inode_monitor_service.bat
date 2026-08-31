@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "PYTHON_EXE=%~1"
set "CONFIG_PATH=%~2"

if "%PYTHON_EXE%"=="" set "PYTHON_EXE=python"
if "%CONFIG_PATH%"=="" set "CONFIG_PATH=%SCRIPT_DIR%inode_monitor.ini"

where nssm >nul 2>nul
if errorlevel 1 (
    echo nssm not found in PATH. Please install NSSM first or add it to PATH.
    exit /b 1
)

set "SERVICE_NAME=INodeMonitor"
set "DISPLAY_NAME=iNode Monitor"

nssm install "%SERVICE_NAME%" "%PYTHON_EXE%" "%SCRIPT_DIR%run_inode_monitor.py" "%CONFIG_PATH%"
nssm set "%SERVICE_NAME%" AppDirectory "%SCRIPT_DIR%"
nssm set "%SERVICE_NAME%" DisplayName "%DISPLAY_NAME%"
nssm set "%SERVICE_NAME%" Start SERVICE_AUTO_START

echo.
echo Service installed successfully.
echo To start it:
 echo nssm start %SERVICE_NAME%
echo To stop it:
 echo nssm stop %SERVICE_NAME%
echo To remove it:
 echo nssm remove %SERVICE_NAME% confirm
