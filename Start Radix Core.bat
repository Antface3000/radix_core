@echo off
REM Start Radix Core. This is the file to double-click.
REM It ensures the .venv exists, starts the local services (AllTalk / ComfyUI /
REM Piper), then opens the app. There is nothing to set up or activate by hand.
cd /d "%~dp0"

REM 1) Make sure the virtual environment exists (build it on first run).
if exist ".venv\Scripts\python.exe" goto :run

set "PYCMD="
call :try_py "py -3"
call :try_py "python"
call :try_py "python3"
if not defined PYCMD (
    echo Python 3.10 or newer was not found.
    echo Install it from https://www.python.org/downloads/
    echo ^(tick "Add python.exe to PATH"^), then double-click this file again.
    pause
    exit /b 1
)
%PYCMD% run.py --bootstrap-only

if not exist ".venv\Scripts\python.exe" (
    echo Setup did not finish - the virtual environment is missing.
    pause
    exit /b 1
)

:run
REM 2) Pre-launch services (start AllTalk, probe ComfyUI, ready Piper).
set "RADIX_SERVICES_PRELAUNCHED=1"
".venv\Scripts\python.exe" scripts\start_services.py

REM 3) Open the app.
".venv\Scripts\python.exe" run.py %*
exit /b %errorlevel%

:try_py
if defined PYCMD goto :eof
%~1 -c "import sys;sys.exit(0 if sys.version_info[:2]>=(3,10) else 1)" >nul 2>&1
if "%errorlevel%"=="0" set "PYCMD=%~1"
goto :eof
