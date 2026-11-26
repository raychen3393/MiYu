@echo off
"%SystemRoot%\System32\chcp.com" 65001 >nul
cd /d "%~dp0"
echo 正在打包成单个 exe，需要联网，大约 3 到 8 分钟……
rem 打包工具对 Python 3.15 以上的支持还不完善,之前用新版建的虚拟环境要换掉
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import sys; sys.exit(0 if sys.version_info < (3, 15) else 1)"
  if errorlevel 1 (
    echo 检测到 Python 3.15 以上,打包工具还不完全支持,改用 3.13 或 3.12 重建环境……
    py -3.13 -c "pass" >nul 2>nul && (rmdir /s /q .venv & py -3.13 -m venv .venv) || (
      py -3.12 -c "pass" >nul 2>nul && (rmdir /s /q .venv & py -3.12 -m venv .venv) || echo 没找到 3.13 / 3.12,继续用现在的版本
    )
  )
)
if exist ".venv\Scripts\python.exe" goto deps
py -3.13 -m venv .venv >nul 2>nul
if not exist ".venv\Scripts\python.exe" py -3.12 -m venv .venv >nul 2>nul
if not exist ".venv\Scripts\python.exe" py -3 -m venv .venv >nul 2>nul
if not exist ".venv\Scripts\python.exe" python -m venv .venv
if not exist ".venv\Scripts\python.exe" goto nopython

:deps
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto pipfail
rem 准备发布签名(局域网自动更新用):公钥打包进 exe,私钥留在你的用户目录
".venv\Scripts\python.exe" tools\release.py prepare
rem 编译超轻量 Uninstall.exe 并放进 assets（自动内置进 MiYu.exe，局域网更新后也会自动释放）
if exist "%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" (
  "%SystemRoot%\Microsoft.NET\Framework64\v4.0.30319\csc.exe" /nologo /utf8output /optimize+ /target:winexe /win32icon:assets\icon.ico /win32manifest:tools\uninstall.manifest /r:System.Windows.Forms.dll /r:System.Drawing.dll /out:assets\Uninstall.exe tools\uninstall.cs
)
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean MiYu.spec
if errorlevel 1 goto buildfail
rem 给 exe 加上发布签名,并确认签完还能正常启动;不行就保留没签名的版本(只是不参与自动更新)
copy /y "dist\MiYu.exe" "dist\MiYu.signed.exe" >nul
".venv\Scripts\python.exe" tools\release.py sign "dist\MiYu.signed.exe"
if errorlevel 1 goto nosign
start /wait "" "dist\MiYu.signed.exe" --selftest
if errorlevel 1 goto nosign
move /y "dist\MiYu.signed.exe" "dist\MiYu.exe" >nul
if exist "assets\Uninstall.exe" copy /y "assets\Uninstall.exe" "dist\Uninstall.exe" >nul
if exist "build" rmdir /s /q "build"
echo 已签名，支持局域网自动更新，并已内置 Uninstall.exe 与清理 build 临时目录。
goto done
:nosign
del "dist\MiYu.signed.exe" >nul 2>nul
echo 注意：签名或启动自检没通过。这份 exe 大概率还能用，但不参与局域网自动更新。请把上面的信息截图发给我；也可以双击 exe 打开后在 设置 → 诊断信息 里点复制。
:done
echo.
echo 打包完成：dist\MiYu.exe
echo 把这个 exe 发给同一局域网的人，双击就能用，对方电脑不需要装 Python。
start "" "dist"
pause
exit /b 0

:nopython
echo 没有找到 Python。请先安装 Python 3.13（推荐）：https://www.python.org/downloads/
echo 安装时记得勾选 Add python.exe to PATH
pause
exit /b 1

:pipfail
echo 依赖安装失败，请检查网络后重试
pause
exit /b 1

:buildfail
echo 打包失败，请把上面的报错截图发给我
pause
exit /b 1
