@echo off
"%SystemRoot%\System32\chcp.com" 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\pythonw.exe" goto run

echo 首次运行：正在准备运行环境，需要联网，大约 1 到 3 分钟……
py -3 -m venv .venv >nul 2>nul
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if not exist ".venv\Scripts\python.exe" goto nopython
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto pipfail

:run
start "" ".venv\Scripts\pythonw.exe" main.py %*
exit /b 0

:nopython
echo 没有找到 Python。请先安装 Python 3.10 或更新版本：https://www.python.org/downloads/
echo 安装时记得勾选 Add python.exe to PATH
pause
exit /b 1

:pipfail
echo 依赖安装失败，请检查网络后重新双击 run.bat
rmdir /s /q .venv
pause
exit /b 1
