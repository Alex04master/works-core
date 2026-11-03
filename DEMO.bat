@echo off
rem WORKS-CORE — запуск с демо-данными и без пароля
cd /d "%~dp0"
set "PY=python"
where %PY% >nul 2>nul || set "PY=py -3"
echo ============================================================
echo    WORKS-CORE  —  проверка работоспособности
echo    Студенты:  http://localhost:8080/
echo    Панель:    http://localhost:8080/staff
echo    Модули:    http://localhost:8080/_modules
echo    Остановка: Ctrl+C
echo ============================================================
%PY% -X utf8 server.py --port 8080 --demo --no-pass
if errorlevel 1 (
  echo.
  echo  ** Ошибка. Нужен Python 3.10+ ; порт занят?  DEMO.bat 8090
)
pause