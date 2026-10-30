@echo off
setlocal
chcp 65001 >nul
title ETF份额观察站

rem 功能：一键启动独立ETF份额观察站并打开浏览器。
rem 输入：无；默认真实数据模式、端口8765，后台日更默认关闭。
rem 输出：本地Web服务及运行日志；Ctrl+C停止服务。
set "APP_DIR=%~dp0etf_monitor"
set "PYTHON=%APP_DIR%\.venv\Scripts\python.exe"
set "URL=http://127.0.0.1:8765"

if not exist "%PYTHON%" (
    echo [错误] 未找到独立Python虚拟环境：
    echo %PYTHON%
    echo 请先按照 etf_monitor\README.md 安装环境。
    echo 本脚本不会自动安装依赖或修改其他Python环境。
    goto :error
)
if not exist "%APP_DIR%\backend\etf_monitor\main.py" (
    echo [错误] 未找到监控系统后端文件，请检查目录是否完整。
    goto :error
)
if not exist "%APP_DIR%\frontend\dist\index.html" (
    echo [错误] 前端尚未构建。
    echo 请在 etf_monitor\frontend 目录执行 npm.cmd ci 和 npm.cmd run build。
    goto :error
)

rem 只检查端口，不终止任何已有进程。
"%PYTHON%" -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',8765)); s.close()" >nul 2>&1
if errorlevel 1 (
    echo [错误] 端口8765已被占用或无法使用。
    echo %URL%
    echo 本脚本不会结束占用端口的程序。
    goto :error
)

pushd "%APP_DIR%"
if errorlevel 1 goto :error
set "PYTHONPATH=%APP_DIR%\backend"
set "PYTHONIOENCODING=utf-8"
set "ETF_MONITOR_HOME=%APP_DIR%\runtime"
set "ETF_MONITOR_MODE=live"
set "ETF_MONITOR_SCHEDULER=0"

echo ================================================
echo ETF份额观察站正在启动
echo 模式：真实数据；日更默认关闭，可在界面启用
echo 地址：%URL%
echo 首次使用请同步目录、核对分类，再更新日份额。
echo 份额按日披露，不代表实时国家队买卖。
echo 保持本窗口打开，按Ctrl+C停止服务。
echo ================================================

rem 等待服务就绪再打开浏览器，最多等待30秒；不访问外部服务。
start "" /b "%PYTHON%" -c "import time,urllib.request,webbrowser; url='%URL%'; deadline=time.monotonic()+30; exec('while time.monotonic() < deadline:\n try:\n  urllib.request.urlopen(url+\"/api/health\", timeout=1).close()\n  webbrowser.open(url)\n  break\n except Exception:\n  time.sleep(0.5)')" >nul 2>&1

"%PYTHON%" -m uvicorn etf_monitor.main:app --host 127.0.0.1 --port 8765
set "EXIT_CODE=%ERRORLEVEL%"
popd
if not "%EXIT_CODE%"=="0" (
    echo.
    echo [错误] 服务退出，退出码：%EXIT_CODE%。请查看上方日志。
    pause
)
exit /b %EXIT_CODE%

:error
echo.
pause
exit /b 1
