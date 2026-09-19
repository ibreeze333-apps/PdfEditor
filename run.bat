@echo off
set FLAGS_use_mkldnn=0
set FLAGS_enable_pir_api=0
set PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT=0

rem 프로젝트 가상환경이 있으면 그걸 쓴다. 없으면 시스템 파이썬 3.11 로 대체
set "VENVPY=%~dp0.venv\Scripts\python.exe"
if exist "%VENVPY%" goto runvenv

where py >nul 2>&1
if errorlevel 1 goto nopy
py -3.11 "%~dp0main.py"
if errorlevel 1 goto apperr
exit /b 0

:runvenv
"%VENVPY%" "%~dp0main.py"
if errorlevel 1 goto apperr
exit /b 0

:nopy
echo [오류] Python 런처 py 를 찾을 수 없습니다.
echo        python.org 에서 Python 3.11 을 설치하세요.
pause
exit /b 1

:apperr
echo.
echo [오류] 앱이 오류로 종료됐습니다. 위 메시지를 확인하세요.
echo        패키지가 없으면 setup_py311.bat 을 먼저 실행하세요.
pause
exit /b 1
