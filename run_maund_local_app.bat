@echo off
set ROOT_DIR=%~dp0
cd /d "%ROOT_DIR%"

set PYRUNNER=
where py >nul 2>&1
if %ERRORLEVEL%==0 set PYRUNNER=py -3
if not defined PYRUNNER (
  where python >nul 2>&1
  if %ERRORLEVEL%==0 set PYRUNNER=python
)

if not defined PYRUNNER (
  echo Python 3가 필요합니다. Python 3를 설치한 뒤 다시 실행하세요.
  exit /b 1
)

set MAUND_OPEN_BROWSER=1
%PYRUNNER% maund_local_webapp_launcher.py
