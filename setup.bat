@echo off
chcp 65001 >nul
rem 桌面魔镜：第一次使用前运行一次，创建 .venv 并安装依赖（需要联网）。
setlocal
cd /d "%~dp0"
set "PY="
py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul && set "PY=python"
if not defined PY (
    echo 没找到 Python 3.12。请先从 https://www.python.org/downloads/ 安装，安装时勾选 "Add python.exe to PATH"。
    goto :error
)
if not exist ".venv\Scripts\python.exe" (
    echo [1/2] 创建虚拟环境 .venv ...
    %PY% -m venv .venv || goto :error
)
echo [2/2] 安装依赖 ...
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
echo.
echo 完成。双击 start.bat 启动。
pause
exit /b 0

:error
echo.
echo 安装没有完成，请看上面的提示。
pause
exit /b 1
