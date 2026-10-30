param(
    # 功能：启动独立ETF系统；输入：模式、端口、数据目录、调度；输出：本地服务前台日志。
    [ValidateSet("live", "demo")][string]$Mode = "demo",
    [ValidateRange(1024, 65535)][int]$Port = 8765,
    [string]$DataDir = "",
    [switch]$Schedule
)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $Root ".venv/Scripts/python.exe"
if (-not (Test-Path $Python)) {
    throw "独立虚拟环境尚未建立，请先按README完成安装。启动脚本不会自动安装或改动现有环境。"
}
$env:ETF_MONITOR_MODE = $Mode
$env:ETF_MONITOR_SCHEDULER = "0"
if ($Schedule) { $env:ETF_MONITOR_SCHEDULER = "1" }
if ($DataDir) {
    $env:ETF_MONITOR_HOME = [System.IO.Path]::GetFullPath($DataDir)
} else {
    $env:ETF_MONITOR_HOME = Join-Path $Root "runtime"
}
$env:PYTHONIOENCODING = "utf-8"
# 仅监听回环地址，不结束占用端口的已有进程；Ctrl+C停止本次服务。
& $Python -m uvicorn etf_monitor.main:app --host 127.0.0.1 --port $Port
exit $LASTEXITCODE
