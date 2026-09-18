@echo off
rem ============================================================
rem  One-click launcher for download_embedding_model.py
rem
rem  Keep this file ASCII-only. cmd.exe reads .bat files using the
rem  console code page, so non-ASCII characters would be garbled.
rem  Rename this file to a Chinese name if you like -- the name does
rem  not affect how it runs.
rem ============================================================

cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo [ERROR] .venv\Scripts\python.exe not found.
    echo.
    echo Please create the virtual environment and install dependencies
    echo first. See README.md, section "Prepare environment".
    echo.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" download_embedding_model.py %*

echo.
pause
