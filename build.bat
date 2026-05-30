@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "BUILD_VERSION=v2.2.5"
set "BUILD_DATE="
for /f %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Date -Format yyyyMMdd" 2^>nul') do set "BUILD_DATE=%%I"
if not defined BUILD_DATE set "BUILD_DATE=unknown_date"
set "FINAL_DIST_NAME=DEVERP_server_%BUILD_VERSION%_%BUILD_DATE%"
set "FINAL_DIST_DIR=dist\%FINAL_DIST_NAME%"

echo ========================================
echo DevERP WEB Server Build Start - v2.2.5 SAFE ASCII
echo ========================================
echo Base: %CD%
echo Output folder: %FINAL_DIST_DIR%
echo.

REM Important: keep this BAT ASCII-only. Korean text in BAT can break on some Windows codepages.

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

echo [0] Stop old processes...
taskkill /F /T /IM DevERP_Server.exe >nul 2>nul
taskkill /F /T /IM ngrok.exe >nul 2>nul

echo [1] Python check...
%PY_CMD% --version
if errorlevel 1 (
    echo [ERROR] Python command failed: %PY_CMD%
    pause
    exit /b 1
)

echo.
echo [2] Required file check...
if not exist "server\main_server.py" (
    echo [ERROR] server\main_server.py not found.
    echo Run build.bat from the DevERP source root folder.
    pause
    exit /b 1
)
if not exist "server\web\index.html" (
    echo [ERROR] server\web\index.html not found.
    pause
    exit /b 1
)
if not exist "shared" (
    echo [ERROR] shared folder not found.
    pause
    exit /b 1
)
if not exist "database" (
    echo [WARN] database folder not found. Creating empty folder.
    mkdir database >nul 2>nul
)



echo.
echo [2-1] Clean Python bytecode cache...
for /d /r %%D in (__pycache__) do (
    if exist "%%D" rmdir /s /q "%%D" >nul 2>nul
)
for /r %%F in (*.pyc *.pyo) do (
    if exist "%%F" del /f /q "%%F" >nul 2>nul
)
echo [OK] Python bytecode cache cleaned.

echo.
echo [2-2] Clean obsolete source artifacts...
for %%F in (test.pdf inspection_template.xlsx check_legacy_ngrok_qr_domain.bat force_start_legacy_ngrok_8001.bat check_purchase_orders_detail_hotfix.bat list_request_numbers.bat list_request_numbers.py delete_request_no.bat delete_request_no.py DevERP_Client.spec start_client.bat) do (
    if exist "%%F" del /f /q "%%F" >nul 2>nul
)
if exist "database\vendor_master__.xlsx" del /f /q "database\vendor_master__.xlsx" >nul 2>nul
if exist "qr_codes\TEST_QR_SAMPLE.png" del /f /q "qr_codes\TEST_QR_SAMPLE.png" >nul 2>nul
if exist "client\ui" rmdir /s /q "client\ui" >nul 2>nul
for %%F in (client\main.py client\api_client.py client\user_settings.py) do (
    if exist "%%F" del /f /q "%%F" >nul 2>nul
)
echo [OK] Obsolete source artifacts cleaned.

echo.
echo [3] PyInstaller check...
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
%PY_CMD% -m PyInstaller --version

echo.
echo [3-1] Legacy XLS parser dependency check...
%PY_CMD% -c "import xlrd" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing xlrd for legacy .xls estimate parsing...
    %PY_CMD% -m pip install "xlrd>=2.0.1"
    if errorlevel 1 (
        echo [ERROR] xlrd install failed. Legacy .xls estimate parsing requires xlrd when Excel COM/LibreOffice is unavailable.
        pause
        exit /b 1
    )
)

%PY_CMD% -c "import pdfplumber" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing pdfplumber for PDF estimate text/table extraction...
    %PY_CMD% -m pip install "pdfplumber>=0.11.0"
    if errorlevel 1 (
        echo [ERROR] pdfplumber install failed.
        pause
        exit /b 1
    )
)

%PY_CMD% -c "import docx" >nul 2>nul
if errorlevel 1 (
    echo [INFO] Installing python-docx for DOCX estimate text/table extraction...
    %PY_CMD% -m pip install "python-docx>=1.1.0"
    if errorlevel 1 (
        echo [ERROR] python-docx install failed.
        pause
        exit /b 1
    )
)

echo.
echo [4] Clean old build folders...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
if exist "build_client_agent" rmdir /s /q "build_client_agent"
if exist "bundled_client_agent" rmdir /s /q "bundled_client_agent"
if exist "build" (
    echo [ERROR] Failed to remove build folder. Close Explorer/CMD/Server using it and retry.
    pause
    exit /b 1
)
if exist "dist" (
    echo [ERROR] Failed to remove dist folder. Close Explorer/CMD/Server using it and retry.
    pause
    exit /b 1
)

echo.
echo [5] Build Client Agent EXE for client PCs without Python...
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
    echo [ERROR] Client Agent EXE was not created.
    pause
    exit /b 1
)
echo [OK] Client Agent EXE ready.

echo.
echo [6] Build Server EXE...
if exist "DevERP_Server.spec" (
    %PY_CMD% -m PyInstaller "DevERP_Server.spec" --noconfirm --clean --log-level INFO
) else (
    %PY_CMD% -m PyInstaller "server\main_server.py" --noconfirm --clean --onedir --name DevERP_Server --noupx --log-level INFO --add-data "server;server" --add-data "shared;shared" --add-data "database;database"
)
if errorlevel 1 (
    echo.
    echo [ERROR] Server EXE build failed.
    pause
    exit /b 1
)
if not exist "dist\DevERP_Server\DevERP_Server.exe" (
    echo [ERROR] Server build finished but dist\DevERP_Server\DevERP_Server.exe was not found.
    pause
    exit /b 1
)

echo.
echo [7] Copy runtime folders...
if exist "generated" xcopy /e /y /i "generated" "dist\DevERP_Server\generated\" >nul
if exist "qr_codes" xcopy /e /y /i "qr_codes" "dist\DevERP_Server\qr_codes\" >nul
if exist "receipt_photos" xcopy /e /y /i "receipt_photos" "dist\DevERP_Server\receipt_photos\" >nul
if exist "uploaded_estimates" xcopy /e /y /i "uploaded_estimates" "dist\DevERP_Server\uploaded_estimates\" >nul
if exist ".runtime" xcopy /e /y /i ".runtime" "dist\DevERP_Server\.runtime\" >nul
if exist "bundled_client_agent" xcopy /e /y /i "bundled_client_agent" "dist\DevERP_Server\_internal\bundled_client_agent\" >nul
if exist "client\settings.json" (
    if not exist "dist\DevERP_Server\client" mkdir "dist\DevERP_Server\client" >nul 2>nul
    copy /y "client\settings.json" "dist\DevERP_Server\client\settings.json" >nul
)

echo.
echo [7-1] Clean obsolete files from build output...
for %%F in (test.pdf inspection_template.xlsx check_legacy_ngrok_qr_domain.bat force_start_legacy_ngrok_8001.bat check_purchase_orders_detail_hotfix.bat list_request_numbers.bat list_request_numbers.py delete_request_no.bat delete_request_no.py DevERP_Client.spec start_client.bat) do (
    if exist "dist\DevERP_Server\%%F" del /f /q "dist\DevERP_Server\%%F" >nul 2>nul
)
if exist "dist\DevERP_Server\database\vendor_master__.xlsx" del /f /q "dist\DevERP_Server\database\vendor_master__.xlsx" >nul 2>nul
if exist "dist\DevERP_Server\qr_codes\TEST_QR_SAMPLE.png" del /f /q "dist\DevERP_Server\qr_codes\TEST_QR_SAMPLE.png" >nul 2>nul
for /r "dist\DevERP_Server" %%F in (README.txt readme.txt *.pyc *.pyo) do del /f /q "%%F" >nul 2>nul
for /d /r "dist\DevERP_Server" %%D in (__pycache__) do rmdir /s /q "%%D" >nul 2>nul
echo [OK] Build output cleaned.

echo.
echo [8] Copy built start BAT...
if exist "start_web_clean_built.bat" (
    copy /y "start_web_clean_built.bat" "dist\DevERP_Server\start_web_clean.bat" >nul
) else (
    echo [WARN] start_web_clean_built.bat not found. Creating minimal start BAT.
    > "dist\DevERP_Server\start_web_clean.bat" echo @echo off
    >> "dist\DevERP_Server\start_web_clean.bat" echo cd /d "%%~dp0"
    >> "dist\DevERP_Server\start_web_clean.bat" echo DevERP_Server.exe
    >> "dist\DevERP_Server\start_web_clean.bat" echo pause
)


echo.
echo [9] Copy server boot autostart BAT files...
for %%F in (register_DevERP_Server_boot_autostart_SYSTEM.bat _run_DevERP_Server_at_boot.bat unregister_DevERP_Server_boot_autostart_SYSTEM.bat check_DevERP_Server_boot_autostart.bat) do (
    if exist "%%F" (
        copy /y "%%F" "dist\DevERP_Server\%%F" >nul
        echo [OK] Copied %%F
    ) else (
        echo [WARN] %%F not found in source root. Skipped.
    )
)

echo.
echo [10] Rename final dist folder...
if exist "%FINAL_DIST_DIR%" rmdir /s /q "%FINAL_DIST_DIR%"
ren "dist\DevERP_Server" "%FINAL_DIST_NAME%"
if errorlevel 1 (
    echo [ERROR] Failed to rename dist\DevERP_Server to %FINAL_DIST_NAME%.
    pause
    exit /b 1
)
if not exist "%FINAL_DIST_DIR%\DevERP_Server.exe" (
    echo [ERROR] Final server executable was not found: %FINAL_DIST_DIR%\DevERP_Server.exe
    pause
    exit /b 1
)

echo.
echo ========================================
echo Build Complete
echo ========================================
echo Server executable:
echo   %FINAL_DIST_DIR%\DevERP_Server.exe
echo Start batch:
echo   %FINAL_DIST_DIR%\start_web_clean.bat
echo.
echo Copy the whole %FINAL_DIST_DIR% folder to the server PC and run it.
echo Keep your old dev_erp.db if you need existing data.
echo ========================================
pause
exit /b 0
