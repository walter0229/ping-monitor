@echo off
echo ==================================================
echo EXANET Ping Monitor - Starting...
echo ==================================================

:: Check if .venv exists
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found.
    echo Please run 'install_windows.bat' first.
    pause
    exit /b
)

:: Show Local IP Address for convenience
echo [INFO] Your Local IP Address(es):
for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /c:"IPv4"') do (
    echo    - %%a
)
echo.

:: Start the server in a new window (keeps window open on error with /k)
echo [PROGRESS] Starting FastAPI server...
start "EXANET Ping Monitor Server" cmd /k ".venv\Scripts\python.exe app.py"

:: Wait for a few seconds for the server to start
timeout /t 3 /nobreak >nul

:: Open the browser
echo [PROGRESS] Opening Web Browser...
start http://localhost:8000

echo ==================================================
echo Server is running at http://localhost:8000
echo Do not close the other command window while using.
echo ==================================================
