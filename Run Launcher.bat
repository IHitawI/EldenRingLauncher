@echo off
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
    py -3 -B splash.py
    if errorlevel 1 (
        echo.
        echo Не удалось запустить через Python. Установите зависимости:
        echo py -m pip install -r requirements.txt
        pause
    )
) else if exist "EldenRingLauncher.exe" (
    start "" "EldenRingLauncher.exe"
) else (
    echo.
    echo Не найден ни Python, ни EldenRingLauncher.exe.
    echo Установите Python 3.11+ с https://www.python.org/downloads/
    echo или соберите exe: py build_release.py
    pause
)
