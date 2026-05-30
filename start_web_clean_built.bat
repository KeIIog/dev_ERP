@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

echo ========================================
echo DevERP WEB BUILT START
echo ========================================
echo Base: %CD%
echo.

echo [0] Stop old ngrok.exe...
taskkill /F /T /IM ngrok.exe >nul 2>nul

echo [1] Free ports 8000 and 8001 if needed...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":8000 .*LISTENING"') do taskkill /F /PID %%a >nul 2>nul
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R /C:":8001 .*LISTENING"') do taskkill /F /PID %%a >nul 2>nul

echo [2] Start built server...
DevERP_Server.exe

echo.
echo [SERVER EXITED] code=%ERRORLEVEL%
pause
exit /b %ERRORLEVEL%
