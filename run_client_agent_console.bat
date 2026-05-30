@echo off
chcp 65001 >nul
setlocal EnableExtensions
pushd "%~dp0" || exit /b 1
if not exist "%~dp0logs" mkdir "%~dp0logs" >nul 2>nul

echo ========================================
echo DevERP Client Agent v32 VISIBLE MODE
echo ========================================
echo Base: %~dp0
echo Health: http://127.0.0.1:8765/health
echo This window must stay open while testing.
echo Press Ctrl+C to stop.
echo.

if exist "%~dp0dist\DevERP_Client_Agent\DevERP_Client_Agent.exe" (
    echo Standalone EXE found. Python is NOT required.
    echo Starting EXE...
    "%~dp0dist\DevERP_Client_Agent\DevERP_Client_Agent.exe"
    echo.
    echo [EXITED] code=%ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)
if exist "%~dp0DevERP_Client_Agent.exe" (
    echo Standalone EXE found. Python is NOT required.
    echo Starting EXE...
    "%~dp0DevERP_Client_Agent.exe"
    echo.
    echo [EXITED] code=%ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

echo Python locations:
where py.exe 2>nul
where python.exe 2>nul
echo.

where py.exe >nul 2>nul
if not errorlevel 1 (
    py -3 --version
    echo Checking dependencies...
    py -3 -c "import selenium, webdriver_manager, bs4" 2>nul || py -3 -m pip install -r "%~dp0requirements_client_agent.txt"
    echo Starting agent...
    py -3 -u "%~dp0client_web_agent.py"
    echo.
    echo [EXITED] code=%ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

where python.exe >nul 2>nul
if not errorlevel 1 (
    python --version
    echo Checking dependencies...
    python -c "import selenium, webdriver_manager, bs4" 2>nul || python -m pip install -r "%~dp0requirements_client_agent.txt"
    echo Starting agent...
    python -u "%~dp0client_web_agent.py"
    echo.
    echo [EXITED] code=%ERRORLEVEL%
    pause
    exit /b %ERRORLEVEL%
)

echo [ERROR] Standalone EXE and Python were both not found. Rebuild the server with v32 patch, then download/install the agent again.
pause
exit /b 1
