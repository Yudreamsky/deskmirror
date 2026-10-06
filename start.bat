@echo off
chcp 65001 >nul
rem 桌面魔镜：魔镜框里原位显示译文。退出：右键托盘图标 → 退出。看日志：start.bat debug
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo 还没安装运行环境，请先双击 setup.bat。
    pause
    exit /b 1
)
if /I "%~1"=="debug" (
    ".venv\Scripts\python.exe" -B -m deskmirror
    pause
) else (
    start "" ".venv\Scripts\pythonw.exe" -B -m deskmirror
)
