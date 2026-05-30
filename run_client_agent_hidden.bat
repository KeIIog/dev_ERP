@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0" || exit /b 1
if not exist "%~dp0logs" mkdir "%~dp0logs" >nul 2>nul
echo [%DATE% %TIME%] DevERP Client Agent hidden BAT launcher start >> "%~dp0logs\client_agent_hidden.log"
powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0run_client_agent_hidden.ps1" >> "%~dp0logs\client_agent_hidden.log" 2>>&1
exit /b %ERRORLEVEL%
