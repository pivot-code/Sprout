@echo off
title Sprout - Install
echo.
echo   ========================================
echo       Sprout v1.0 - Installation
echo   ========================================
echo.

:: Step 1: Check Python
echo [1/4] Checking Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python not found. Please install Python 3.10+
    echo Download: https://www.python.org/downloads/
    pause
    exit /b 1
)
python --version
echo.

:: Step 2: Create venv
echo [2/4] Creating virtual environment...
if not exist ".venv" (
    python -m venv .venv
    echo       .venv created
) else (
    echo       .venv already exists, skipping
)
echo.

:: Step 3: Install dependencies
echo [3/4] Installing dependencies (this may take a few minutes)...
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt -q
echo       Dependencies installed
echo.

:: Step 4: Copy config templates
echo [4/4] Setting up config files...
if not exist ".env" (
    copy .env.example .env >nul
    echo       .env created from template
    echo       *** Please edit .env and add your API key! ***
    echo       Get one at: https://platform.deepseek.com/api_keys
    echo.
) else (
    echo       .env already exists
    echo.
)

if not exist "providers.json" (
    copy providers.json.example providers.json >nul
    echo       providers.json created from template
    echo.
)

echo   ========================================
echo       Installation complete!
echo   ========================================
echo.
echo   Next steps:
echo     1. Edit .env and add your DeepSeek API Key
echo     2. Double-click start.bat to launch
echo     3. Open http://127.0.0.1:8000 in browser
echo.
pause