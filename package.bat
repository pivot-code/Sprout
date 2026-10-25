@echo off
title Sprout - Package

:: Try venv Python first
if exist ".venv\Scripts\python.exe" goto use_venv

:: Try system Python
python --version >nul 2>&1
if %errorlevel% equ 0 goto use_system

:: Not found
echo [ERROR] Python not found. Run install.bat first.
echo Download: https://www.python.org/downloads/
pause
exit /b 1

:use_venv
.venv\Scripts\python.exe package.py
pause
exit /b 0

:use_system
python package.py
pause
exit /b 0