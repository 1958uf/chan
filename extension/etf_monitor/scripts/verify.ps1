param(
    # 功能：执行独立系统离线验收；输入：是否启用有限在线测试；输出：退出码与测试结果。
    [switch]$Live
)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Python = Join-Path $Root ".venv/Scripts/python.exe"
if (-not (Test-Path $Python)) { throw "缺少专属Python环境" }
Push-Location $Root
try {
    & $Python -m pytest -m "not live" --cov=etf_monitor --cov-report=term-missing --cov-fail-under=85
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    Push-Location "frontend"
    try {
        & npm.cmd run typecheck
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        & npm.cmd run test -- --run
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    } finally { Pop-Location }
    if ($Live) {
        $env:ETF_MONITOR_LIVE_TESTS = "1"
        & $Python -m pytest -m live
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
} finally { Pop-Location }
