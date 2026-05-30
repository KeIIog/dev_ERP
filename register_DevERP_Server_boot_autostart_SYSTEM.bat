@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "TASK_NAME=DevERP_Server_Autostart"
set "EXE=%~dp0DevERP_Server.exe"
set "RUNBAT=%~dp0_run_DevERP_Server_at_boot.bat"

echo.
echo ============================================================
echo DevERP Server boot autostart registration
echo ============================================================
echo Folder : %~dp0
echo EXE    : %EXE%
echo Task   : %TASK_NAME%
echo.

if not exist "%EXE%" (
    echo [ERROR] DevERP_Server.exe was not found in this folder.
    echo Put this BAT file in the same folder as DevERP_Server.exe and run again.
    pause
    exit /b 1
)

if not exist "%RUNBAT%" (
    echo [ERROR] _run_DevERP_Server_at_boot.bat was not found in this folder.
    echo Copy all files from the ZIP into the DevERP_Server.exe folder.
    pause
    exit /b 1
)

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo [INFO] Administrator rights are required. Re-opening as administrator...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo [INFO] Removing old task if it exists...
schtasks /End /TN "%TASK_NAME%" >nul 2>&1
schtasks /Delete /TN "%TASK_NAME%" /F >nul 2>&1

echo [INFO] Creating ONSTART task as SYSTEM...
schtasks /Create /TN "%TASK_NAME%" /SC ONSTART /RU SYSTEM /RL HIGHEST /TR "\"%RUNBAT%\"" /F
if errorlevel 1 (
    echo [ERROR] Failed to create scheduled task.
    pause
    exit /b 1
)

echo [INFO] Starting task now...
schtasks /Run /TN "%TASK_NAME%"
if errorlevel 1 (
    echo [WARN] Task was registered, but could not be started immediately.
    echo It should still run after next Windows reboot.
) else (
    echo [OK] Task started.
)

echo.
echo [OK] DevERP_Server.exe is registered to run at Windows boot, before user login.
echo.
echo Check:
echo   schtasks /Query /TN "%TASK_NAME%" /V /FO LIST
echo.
pause
exit /b 0
