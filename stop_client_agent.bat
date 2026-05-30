@echo off
chcp 65001 >nul
setlocal EnableExtensions
set "AGENT_PORT=8765"
echo Stop DevERP Client Agent on port %AGENT_PORT%...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":%AGENT_PORT% .*LISTENING"') do (
    echo   Kill PID %%P
    taskkill /F /PID %%P
)
echo Done.
pause
