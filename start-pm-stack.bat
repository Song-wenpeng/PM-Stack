@echo off
cd /d "%~dp0"
if not exist ".venv-review\Scripts\python.exe" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "tools\setup_review_env.ps1"
    if errorlevel 1 (
        pause
        exit /b 1
    )
)
".venv-review\Scripts\python.exe" main.py
if errorlevel 1 pause
