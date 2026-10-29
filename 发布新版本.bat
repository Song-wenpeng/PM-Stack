@echo off
chcp 65001 >nul 2>&1
setlocal
cd /d "%~dp0"
if not exist ".venv-review\Scripts\python.exe" (
    echo 请先按 README 准备 .venv-review 开发环境。
    pause
    exit /b 1
)
set "PM_RELEASE_HANDOFF=%~1"
if not defined PM_RELEASE_HANDOFF set /p "PM_RELEASE_HANDOFF=请输入本次发布的交接记录路径（handoffs/任务名.md）："
if not defined PM_RELEASE_HANDOFF exit /b 1
".venv-review\Scripts\python.exe" publish.py --handoff "%PM_RELEASE_HANDOFF%"
set "PM_RELEASE_EXIT=%errorlevel%"
pause
exit /b %PM_RELEASE_EXIT%
