@echo off
REM ============================================================
REM  Radix Core - Windows installer
REM  - Finds a suitable Python (3.10+); installs one via winget if missing
REM  - Creates a .venv virtual environment
REM  - Installs dependencies from requirements.txt
REM
REM  Usage:
REM    install.bat            (use the newest Python 3 found)
REM    install.bat 3.11       (force a specific version, e.g. to test on 3.11)
REM ============================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

REM Minimum supported minor version (3.x). numpy 2.2 requires >= 3.10.
set "MIN_MINOR=10"
set "REQVER=%~1"
set "PYCMD="

echo ============================================================
echo  Radix Core - Windows installer
echo ============================================================
echo.

call :find_python
if not defined PYCMD (
    call :install_python
    call :find_python
)
if not defined PYCMD (
    echo.
    echo [ERROR] Could not find or install Python 3.%MIN_MINOR% or newer.
    echo         Install it from https://www.python.org/downloads/
    echo         ^(tick "Add python.exe to PATH"^) and run this installer again.
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%V in ('!PYCMD! -c "import sys;print('.'.join(map(str,sys.version_info[:3])))"') do set "PYVER=%%V"
echo [OK] Using Python !PYVER!   ^(command: !PYCMD!^)
echo.

REM ---- virtual environment ----
if exist ".venv\Scripts\python.exe" (
    echo [OK] Virtual environment .venv already exists.
) else (
    echo [..] Creating virtual environment in .venv ...
    !PYCMD! -m venv .venv
    if errorlevel 1 (
        echo [ERROR] Failed to create the virtual environment.
        pause
        exit /b 1
    )
)
set "VENV_PY=.venv\Scripts\python.exe"

REM ---- dependencies ----
echo [..] Upgrading pip ...
"%VENV_PY%" -m pip install --upgrade pip
echo.
echo [..] Installing dependencies from requirements.txt ...
"%VENV_PY%" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [WARN] One or more dependencies failed to install.
    echo        This is usually llama-cpp-python needing a prebuilt wheel.
    echo        See INSTALL.txt, section "GPU acceleration", for the CUDA/CPU wheel.
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo  Setup complete.
echo.
echo  Optional next steps:
echo    * GPU speed-up : install a CUDA wheel (see INSTALL.txt)
echo    * Models       : run  "%VENV_PY%" scripts\download_models.py
echo                     or drop .gguf files into  models\
echo.
echo  Launch the app:   double-click "Start Radix Core.bat"
echo  (Until models are added, agents reply in MOCK mode.)
echo ============================================================
echo.
set "LAUNCH="
set /p "LAUNCH=Launch Radix Core now? [y/N] "
if /i "!LAUNCH!"=="y" (
    "%VENV_PY%" run.py
)
exit /b 0

REM ------------------------------------------------------------
:find_python
if not "%REQVER%"=="" (
    call :try_py "py -%REQVER%"
    goto :eof
)
call :try_py "py -3"
call :try_py "python"
call :try_py "python3"
goto :eof

:try_py
if defined PYCMD goto :eof
%~1 -c "import sys;sys.exit(0 if sys.version_info[:2]>=(3,%MIN_MINOR%) else 1)" >nul 2>&1
if !errorlevel! equ 0 set "PYCMD=%~1"
goto :eof

:install_python
echo [..] No suitable Python found. Trying to install one via winget ...
where winget >nul 2>&1
if errorlevel 1 (
    echo [WARN] winget is not available on this system.
    goto :eof
)
winget install -e --id Python.Python.3.13 --accept-package-agreements --accept-source-agreements
echo.
echo [..] Python may have just been installed. If the next step fails,
echo      close this window and run install.bat again so PATH refreshes.
goto :eof
