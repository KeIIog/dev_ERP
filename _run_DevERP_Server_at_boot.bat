@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "APP_DIR=%~dp0"
set "EXE=%APP_DIR%DevERP_Server.exe"
set "LOG_DIR=%APP_DIR%logs"
set "LOG_FILE=%LOG_DIR%\server_autostart.log"
set "OUT_LOG=%LOG_DIR%\server_stdout.log"
set "ERR_LOG=%LOG_DIR%\server_stderr.log"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%" >nul 2>&1

echo ============================================================ >> "%LOG_FILE%"
echo [%DATE% %TIME%] Boot task invoked. >> "%LOG_FILE%"
echo APP_DIR=%APP_DIR% >> "%LOG_FILE%"

if not exist "%EXE%" (
    echo [%DATE% %TIME%] ERROR: DevERP_Server.exe not found. >> "%LOG_FILE%"
    exit /b 1
)

tasklist /FI "IMAGENAME eq DevERP_Server.exe" 2>nul | find /I "DevERP_Server.exe" >nul
if "%errorlevel%"=="0" (
    echo [%DATE% %TIME%] DevERP_Server.exe is already running. Exit. >> "%LOG_FILE%"
    exit /b 0
)

echo [%DATE% %TIME%] Starting DevERP_Server.exe... >> "%LOG_FILE%"
"%EXE%" >> "%OUT_LOG%" 2>> "%ERR_LOG%"

echo [%DATE% %TIME%] DevERP_Server.exe exited with code %ERRORLEVEL%. >> "%LOG_FILE%"
exit /b %ERRORLEVEL%
