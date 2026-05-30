@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo ===============================================
echo  DevERP 로그인 비밀번호 긴급 초기화
echo ===============================================
echo.
echo 예) 고성훈 입력 후 비밀번호 1 입력
echo 예) admin 입력 후 비밀번호 roqkfxla 입력
echo.
set /p USER_ID=초기화할 아이디 입력 [기본: 고성훈, 전체직원: all]: 
if "%USER_ID%"=="" set USER_ID=고성훈
if /I "%USER_ID%"=="all" set USER_ID=--all-employees
set /p NEW_PW=새 비밀번호 입력 [기본: 1 / admin은 roqkfxla 권장]: 
if "%NEW_PW%"=="" set NEW_PW=1
if /I "%USER_ID%"=="admin" if "%NEW_PW%"=="1" set NEW_PW=roqkfxla

echo.
echo 서버 실행 중이면 잠시 종료한 뒤 진행하는 것을 권장합니다.
echo.
python "%~dp0reset_login_password.py" "%USER_ID%" "%NEW_PW%"
if errorlevel 1 (
  echo.
  echo [실패] Python이 없거나 DB 파일을 찾지 못했을 수 있습니다.
  echo DevERP_Server.exe가 있는 폴더에서 실행했는지 확인하세요.
)
echo.
pause
