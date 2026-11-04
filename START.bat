@echo off
rem WORKS-CORE — запуск двойным кликом. Порт можно задать: START.bat 8090
cd /d "%~dp0"
set "PY=python"
where %PY% >nul 2>nul || set "PY=py -3"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8080"
echo ============================================================
echo    WORKS-CORE
echo    Студенты:  http://localhost:%PORT%/
echo    Панель:    http://localhost:%PORT%/staff
echo    Остановка: Ctrl+C
echo ============================================================
%PY% -X utf8 server.py --port %PORT%
if errorlevel 1 (
  echo.
  echo  ** Ошибка. Нужен Python 3.10+ ; порт занят?  START.bat 8090
)
pause
