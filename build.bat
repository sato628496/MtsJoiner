@echo off
chcp 65001 >nul
rem Сборка MtsJoiner.exe (нужен Python 3.12+ с PyInstaller: py -m pip install pyinstaller)
rem Иконка: assets\icon.ico (пересоздать: py -m pip install pillow ^&^& py tools\make_icon.py)
cd /d "%~dp0"
py -3 -m PyInstaller --noconfirm --clean --onefile --windowed --name MtsJoiner ^
  --icon assets\icon.ico --add-data "assets\icon.ico;assets" MtsJoiner.pyw
if errorlevel 1 exit /b 1
echo.
echo Готово: dist\MtsJoiner.exe
