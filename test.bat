@echo off
"%SystemRoot%\System32\chcp.com" 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo 请先双击 run.bat 或 build.bat 准备好环境
    pause
    exit /b 1
)
".venv\Scripts\python.exe" -m unittest tests.test_core tests.test_gui_logic tests.test_gomoku tests.test_duck tests.test_spy tests.test_stream -v
pause
