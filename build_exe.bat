@echo off
echo ==================================================
echo EXANET Ping Monitor - Executable Builder (.exe)
echo ==================================================

:: Check for .venv
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Please run 'install_windows.bat' first.
    pause
    exit /b
)

:: Install PyInstaller in the venv if not present
echo [1/3] Verifying PyInstaller...
.venv\Scripts\pip install pyinstaller

:: Build the executable
echo [2/3] Building Standalone Executable...
:: --onefile: Create a single .exe
:: --add-data: Include index.html (syntax: source;destination for Windows)
:: --name: Name of the output file
:: --clean: Clean PyInstaller cache before building
.venv\Scripts\pyinstaller --onefile --add-data "index.html;." --name "EXANET_Ping_Pro" --clean app.py

echo ==================================================
echo [3/3] Build Complete!
echo You can find the executable at: dist\EXANET_Ping_Pro.exe
echo ==================================================
pause
