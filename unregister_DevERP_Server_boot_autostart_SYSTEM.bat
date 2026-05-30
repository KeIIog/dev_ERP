@echo off
setlocal EnableExtensions
set "TASK_NAME=DevERP_Server_Autostart"

echo.
echo ============================================================
echo DevERP Server boot autostart unregistration
echo ============================================================
echo.

net session >nul 2>&1
if not "%errorlevel%"=="0" (
    echo [INFO] Administrator rights are required. Re-opening as administrator...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

echo [INFO] Stopping scheduled task if running...
schtasks /End /TN "%TASK_NAME%" >nul 2>&1

echo [INFO] Deleting scheduled task...
schtasks /Delete /TN "%TASK_NAME%" /F
if errorlevel 1 (
    echo [WARN] Task was not found or could not be deleted.
) else (
    echo [OK] Task deleted.
)

echo.
echo Note: If DevERP_Server.exe is still running, stop it manually from Task Manager.
echo.
pause
exit /b 0
