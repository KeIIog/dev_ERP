@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "HEALTH_URL=http://127.0.0.1:8765/health"
echo ========================================
echo DevERP Client Agent diagnostics v33 Documents AutoRun
echo ========================================
echo Base: %~dp0
echo Expected install base: %%USERPROFILE%%\Documents\DevERP_Client_Agent
echo.
echo [1] Health: %HEALTH_URL%
powershell -NoProfile -ExecutionPolicy Bypass -Command "try{ $r=Invoke-WebRequest -UseBasicParsing -Uri '%HEALTH_URL%' -TimeoutSec 2; Write-Host $r.Content; exit 0 }catch{ Write-Host '[FAIL]' $_.Exception.Message; exit 1 }"
echo.
echo [2] Listening process on 8765
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8765 .*LISTENING"') do (
  echo PID: %%P
  tasklist /FI "PID eq %%P"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "try{ Get-CimInstance Win32_Process -Filter 'ProcessId=%%P' | Select-Object ProcessId,Name,ExecutablePath,CommandLine | Format-List | Out-String -Width 4096 }catch{}"
)
netstat -ano | findstr ":8765"
echo.
echo [3] Scheduled tasks
schtasks /Query /TN "DevERP_Client_Agent" /FO LIST /V 2>nul
schtasks /Query /TN "DevERP Client Agent" /FO LIST /V 2>nul
echo.
echo [4] HKCU Run
reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "DevERP_Client_Agent" 2>nul
echo.
echo [5] Startup folder
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
dir "%STARTUP%\DevERP_Client_Agent.vbs" 2>nul
echo.
echo [6] Standalone EXE / Python
if exist "%~dp0dist\DevERP_Client_Agent\DevERP_Client_Agent.exe" echo EXE: %~dp0dist\DevERP_Client_Agent\DevERP_Client_Agent.exe
if exist "%~dp0DevERP_Client_Agent.exe" echo EXE: %~dp0DevERP_Client_Agent.exe
where py.exe 2^>nul
where python.exe 2^>nul
echo.
echo [7] Logs
if exist "%~dp0logs\client_agent_startup_register.log" (
  echo --- client_agent_startup_register.log ---
  type "%~dp0logs\client_agent_startup_register.log"
)
if exist "%~dp0logs\client_agent_launcher.log" (
  echo --- client_agent_launcher.log ---
  type "%~dp0logs\client_agent_launcher.log"
)
if exist "%~dp0logs\client_agent_error.log" (
  echo --- client_agent_error.log ---
  type "%~dp0logs\client_agent_error.log"
)
if exist "%~dp0logs\client_agent_stderr.log" (
  echo --- client_agent_stderr.log ---
  type "%~dp0logs\client_agent_stderr.log"
)
echo.
pause
