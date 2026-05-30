@echo off
chcp 65001 >nul
setlocal EnableExtensions
echo Remove DevERP Client Agent startup entries...
reg delete "HKCU\Software\Microsoft\Windows\CurrentVersion\Run" /v "DevERP_Client_Agent" /f >nul 2>nul
if exist "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\DevERP_Client_Agent.vbs" del /f /q "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\DevERP_Client_Agent.vbs" >nul 2>nul
schtasks /Delete /TN "DevERP_Client_Agent" /F >nul 2>nul
schtasks /Delete /TN "DevERP Client Agent" /F >nul 2>nul
echo Stop listener on port 8765...
for /f "tokens=5" %%P in ('netstat -ano ^| findstr /R /C:":8765 .*LISTENING"') do taskkill /F /PID %%P >nul 2>nul
echo Done.
pause
