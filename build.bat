@echo off
chcp 65001 >nul
rem Сборка MtsJoiner.exe (нужен Python 3.12+ с PyInstaller: py -m pip install pyinstaller)
cd /d "%~dp0"
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name MtsJoiner MtsJoiner.pyw
if errorlevel 1 exit /b 1
echo.
echo Готово: dist\MtsJoiner.exe
