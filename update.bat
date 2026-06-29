@echo off
REM Update Radix Core (git pull or release zip overlay).
REM Preserves data/, models/, .venv/, and assets/piper/.
cd /d "%~dp0"

if exist ".git\" (
    echo Fetching and pulling latest from origin/main...
    git fetch origin main
    if errorlevel 1 goto :fail
    git pull origin main
    if errorlevel 1 goto :fail
    if exist ".venv\Scripts\python.exe" (
        echo Installing any new dependencies...
        ".venv\Scripts\python.exe" -m pip install -r requirements.txt
        if errorlevel 1 goto :fail
    )
    echo.
    echo Update complete. Close Radix Core if open, then double-click Start Radix Core.bat.
    pause
    exit /b 0
)

echo No git repository detected — trying release zip overlay...
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" scripts\update.py --zip
) else (
    python scripts\update.py --zip
)
if errorlevel 1 goto :fail
pause
exit /b 0

:fail
echo.
echo Update failed. See the message above.
pause
exit /b 1
