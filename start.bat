@echo off
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Virtual environment not found. Run install.bat first.
    pause
    exit /b 1
)

if not exist ".env" (
    echo [ERROR] .env not found.
    echo Copy .env.example to .env and add your API key.
    pause
    exit /b 1
)

for /f "tokens=2 delims==" %%a in ('findstr "API_PORT" .env') do set PORT=%%a
if "%PORT%"=="" set PORT=8000

echo.
echo   ========================================
echo       Sprout v1.0 - Starting...
echo   ========================================
echo.
echo   Port: %PORT%
echo.

.venv\Scripts\python.exe -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',%PORT%)); s.close()" 2>nul
if errorlevel 1 (
    echo   Port %PORT% in use, freeing...
    for /f "tokens=5" %%p in ('netstat -ano ^| findstr "127.0.0.1:%PORT%" ^| findstr "LISTENING"') do taskkill /PID %%p 2>nul
    timeout /t 2 /nobreak >nul
)

echo   Starting AI Agent...
start "SproutServer" .venv\Scripts\python.exe web_api.py

echo   Waiting for agent to initialize...
timeout /t 8 /nobreak >nul

start http://127.0.0.1:%PORT%

echo.
echo   ========================================
echo       Sprout running at http://127.0.0.1:%PORT%
echo       Close this window to exit.
echo   ========================================
echo.
pause