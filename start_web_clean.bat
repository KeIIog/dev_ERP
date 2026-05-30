@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set PYTHONUTF8=1

echo ========================================
echo DevERP WEB SOURCE START
echo ========================================
echo Base: %CD%
echo.

echo [0] Stop old ngrok.exe...
taskkill /F /T /IM ngrok.exe >nul 2>nul

echo [1] Free ports 8000 and 8001 if needed...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do taskkill /F /PID %%a >nul 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":8001 .*LISTENING"') do taskkill /F /PID %%a >nul 2>nul

echo [2] Python check...
where py.exe >nul 2>nul
if not errorlevel 1 (
    py -3 --version
    echo.
    echo [3] Start server from source...
    py -3 server\main_server.py
    echo.
    echo [SERVER EXITED] code=%ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

where python.exe >nul 2>nul
if not errorlevel 1 (
    python --version
    echo.
    echo [3] Start server from source...
    python server\main_server.py
    echo.
    echo [SERVER EXITED] code=%ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

echo [ERROR] Python was not found. Install Python 3.10+ or add it to PATH.
pause
exit /b 1
