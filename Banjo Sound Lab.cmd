@echo off
setlocal
cd /d "%~dp0"

rem Banjo Sound Lab needs Python with numpy and pygame.
py -c "import numpy, pygame" >nul 2>&1
if errorlevel 1 (
  echo Installing the two packages Banjo Sound Lab needs...
  py -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Could not install them automatically. Run this by hand:
    echo     py -m pip install numpy pygame
    echo.
    pause
    exit /b 1
  )
)

start "" pythonw player.pyw
