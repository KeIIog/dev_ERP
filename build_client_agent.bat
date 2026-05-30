@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo DevERP Client Agent Build Start
echo ========================================
echo Base: %CD%
echo.

set "PY_CMD="
where py.exe >nul 2>nul
if not errorlevel 1 set "PY_CMD=py -3"
if not defined PY_CMD (
    where python.exe >nul 2>nul
    if not errorlevel 1 set "PY_CMD=python"
)

if not defined PY_CMD (
    echo [ERROR] Python was not found on this server PC.
    echo Install Python 3.10+ or add it to PATH.
    pause
    exit /b 1
)

echo [1] Python check...
%PY_CMD% --version
if errorlevel 1 (
    echo [ERROR] Python command failed: %PY_CMD%
    pause
    exit /b 1
)

echo [2] PyInstaller check...
%PY_CMD% -m PyInstaller --version >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing PyInstaller...
    %PY_CMD% -m pip install --upgrade pyinstaller
    if errorlevel 1 (
        echo [ERROR] PyInstaller install failed.
        pause
        exit /b 1
    )
)

echo [3] Build client agent EXE...
if exist "build_client_agent" rmdir /s /q "build_client_agent"
if exist "bundled_client_agent" rmdir /s /q "bundled_client_agent"

if exist "DevERP_Client_Agent.spec" (
    %PY_CMD% -m PyInstaller "DevERP_Client_Agent.spec" --noconfirm --clean --distpath bundled_client_agent --workpath build_client_agent --log-level INFO
) else (
    %PY_CMD% -m PyInstaller "client_web_agent.py" --noconfirm --clean --onedir --name DevERP_Client_Agent --distpath bundled_client_agent --workpath build_client_agent --collect-submodules selenium --collect-submodules webdriver_manager --collect-submodules bs4 --collect-submodules fastapi --collect-submodules starlette --collect-submodules uvicorn --hidden-import selenium.webdriver.chrome.options --hidden-import selenium.webdriver.chrome.service --hidden-import selenium.webdriver.common.by --hidden-import selenium.webdriver.support.ui --hidden-import selenium.webdriver.support.expected_conditions --hidden-import selenium.webdriver.common.keys --hidden-import webdriver_manager.chrome --add-data "server;server" --add-data "shared;shared"
)

if errorlevel 1 (
    echo.
    echo [ERROR] Client Agent EXE build failed.
    pause
    exit /b 1
)

if not exist "bundled_client_agent\DevERP_Client_Agent\DevERP_Client_Agent.exe" (
    echo [ERROR] EXE was not created.
    pause
    exit /b 1
)

echo.
echo [OK] Client Agent EXE ready:
echo bundled_client_agent\DevERP_Client_Agent\DevERP_Client_Agent.exe
echo.
pause
exit /b 0
