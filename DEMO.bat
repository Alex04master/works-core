@echo off
chcp 65001 >nul
rem WORKS-CORE — запуск с демо-данными и без пароля. Порт: DEMO.bat 8090
cd /d "%~dp0"
set "PY=python"
where %PY% >nul 2>nul || set "PY=py -3"
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8080"
echo ============================================================
echo    WORKS-CORE  —  проверка работоспособности
echo    Студенты:  http://localhost:%PORT%/
echo    Панель:      http://localhost:%PORT%/staff
echo    Симулятор:  http://localhost:5173/ (velxio)
echo    Модули:    http://localhost:%PORT%/_modules
echo    Остановка: Ctrl+C
echo ============================================================
%PY% -X utf8 server.py --port %PORT% --demo --no-pass --sim
if errorlevel 1 (
  echo.
  echo  ** Ошибка. Нужен Python 3.10+ ; порт занят?  DEMO.bat 8090
)
pause
