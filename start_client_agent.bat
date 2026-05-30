@echo off
chcp 65001 >nul
setlocal EnableExtensions
pushd "%~dp0" || exit /b 1

set "AGENT_PORT=8765"
set "HEALTH_URL=http://127.0.0.1:%AGENT_PORT%/health"
if not exist "%~dp0logs" mkdir "%~dp0logs" >nul 2>nul

echo ========================================
echo DevERP Client Agent v30 start/register
echo ========================================
echo Base: %~dp0
echo Health: %HEALTH_URL%
echo.

if not exist "%~dp0client_web_agent.py" (
    echo [ERROR] client_web_agent.py not found.
    pause
    exit /b 2
)
if not exist "%~dp0run_client_agent_hidden.ps1" (
    echo [ERROR] run_client_agent_hidden.ps1 not found.
    pause
    exit /b 3
)

echo [1/5] Stop existing listener on port %AGENT_PORT%
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%AGENT_PORT% .*LISTENING"') do (
    echo   Kill PID %%P
    taskkill /F /PID %%P >nul 2>nul
)

echo [2/5] Register auto-start methods: HKCU Run + Startup folder + Task Scheduler
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_client_agent_startup.ps1"
if errorlevel 1 (
    echo [WARN] Some auto-start registration methods failed. Continuing with immediate start.
)

echo [3/5] Start hidden now
wscript.exe //B "%~dp0run_client_agent_hidden.vbs"

echo [4/5] Health check
call :wait_health 25
if errorlevel 1 (
    echo [WARN] Hidden start did not respond. Trying direct PowerShell launcher once...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0run_client_agent_hidden.ps1"
    call :wait_health 20
)

if errorlevel 1 (
    echo.
    echo [FAIL] Client agent did not respond: %HEALTH_URL%
    echo Try visible mode to see the exact error:
    echo   "%~dp0run_client_agent_console.bat"
    echo.
    echo Diagnostics:
    echo   "%~dp0check_client_agent.bat"
    echo Logs:
    echo   "%~dp0logs"
    if exist "%~dp0logs\client_agent_launcher.log" type "%~dp0logs\client_agent_launcher.log"
    pause
    exit /b 10
)

echo.
echo OK: DevERP Client Agent is running.
echo Auto-start registration was attempted through HKCU Run, Startup folder, and Task Scheduler.
echo Open: %HEALTH_URL%
timeout /t 3 /nobreak >nul
exit /b 0

:wait_health
set "MAX=%~1"
if "%MAX%"=="" set "MAX=10"
for /l %%I in (1,1,%MAX%) do (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "try{ $r=Invoke-WebRequest -UseBasicParsing -Uri '%HEALTH_URL%' -TimeoutSec 1; if($r.StatusCode -ge 200 -and $r.StatusCode -lt 300){ $r.Content; exit 0 }else{ exit 1 } }catch{ exit 1 }" >nul 2>nul && exit /b 0
    echo   waiting %%I/%MAX% ...
    timeout /t 1 /nobreak >nul
)
exit /b 1
