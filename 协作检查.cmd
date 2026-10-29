@echo off
setlocal
chcp 65001 >nul 2>&1
set "PM_HANDOFF_HOME=%~dp0"
cd /d "%PM_HANDOFF_HOME%"
if "%~1"=="" goto interactive
call :run %*
exit /b %errorlevel%
:interactive
call :run status
pause
exit /b
:run
if exist "%PM_HANDOFF_HOME%.venv-review\Scripts\python.exe" goto review_python
if exist "%PM_HANDOFF_HOME%.venv\Scripts\python.exe" goto local_python
py -3 "%PM_HANDOFF_HOME%tools\handoff.py" %*
exit /b %errorlevel%
:review_python
"%PM_HANDOFF_HOME%.venv-review\Scripts\python.exe" "%PM_HANDOFF_HOME%tools\handoff.py" %*
exit /b %errorlevel%
:local_python
"%PM_HANDOFF_HOME%.venv\Scripts\python.exe" "%PM_HANDOFF_HOME%tools\handoff.py" %*
exit /b %errorlevel%
