@echo off
echo ==================================================
echo EXANET Ping Monitor - Environment Setup
echo ==================================================

:: Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Please install Python from https://www.python.org/
    pause
    exit /b
)

:: Create Virtual Environment
echo [1/3] Creating Virtual Environment (.venv)...
python -m venv .venv

:: Upgrade pip
echo [2/3] Upgrading pip...
.venv\Scripts\python.exe -m pip install --upgrade pip

:: Install dependencies
echo [3/3] Installing dependencies from requirements.txt...
:: --no-cache-dir helps prevent corrupted cached wheels from being reused
.venv\Scripts\pip install --no-cache-dir -r requirements.txt

:: Specific fix for Pydantic core issue if common
echo [EXTRA] Verifying Pydantic installation...
.venv\Scripts\pip install --no-cache-dir --force-reinstall pydantic pydantic-core

echo ==================================================
echo Setup Complete!
echo You can now run the program using 'run_windows.bat'.
echo ==================================================
pause
