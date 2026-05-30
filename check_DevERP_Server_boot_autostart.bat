@echo off
setlocal EnableExtensions
set "TASK_NAME=DevERP_Server_Autostart"

echo.
echo ============================================================
echo DevERP Server boot autostart check
echo ============================================================
echo.

echo [1] Scheduled task:
schtasks /Query /TN "%TASK_NAME%" /V /FO LIST
echo.

echo [2] DevERP_Server.exe process:
tasklist /FI "IMAGENAME eq DevERP_Server.exe"
echo.

echo [3] Local web server check:
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 'http://127.0.0.1:8000/'; Write-Host ('HTTP OK: ' + $r.StatusCode) } catch { Write-Host ('HTTP CHECK FAILED: ' + $_.Exception.Message) }"
echo.

pause
exit /b 0
