@echo off
REM One-click downloader for the AI models (about 15 GB).
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setup is not finished yet.
    echo Please double-click "Start Radix Core.bat" once ^(or install.bat^) to
    echo set things up, then run this again.
    pause
    exit /b 1
)

echo ============================================================
echo  Downloading the Radix Core AI models (about 15 GB).
echo  This can take a while depending on your internet speed.
echo  You can keep using your computer while it runs.
echo ============================================================
echo.

".venv\Scripts\python.exe" scripts\download_models.py
echo.
echo Done. You can now start the app with "Start Radix Core.bat".
pause
