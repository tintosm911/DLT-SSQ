# ================================================================
# 竞彩快照定时任务 (兼容入口)
# ---------------------------------------------------------------
# 本脚本现在委托给 scripts\schedule_jobs.ps1 (统一管理多个计划任务)。
# 保留这个文件是为了不打断已有的调用方式。
#
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_snapshot.ps1 -Install
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_snapshot.ps1 -Status
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_snapshot.ps1 -Uninstall
#
# 要管全部任务 (含开奖数据更新) 请用 schedule_jobs.ps1。
#
# ★ 本文件必须存为 UTF-8 with BOM, 且 param() 必须是第一个语句。
#   检查: python scripts\check_script_encoding.py
# ================================================================
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Status,
    [string]$Times = '09:00,21:00'
)

$ErrorActionPreference = 'Stop'
$Jobs = Join-Path $PSScriptRoot 'schedule_jobs.ps1'

if (-not (Test-Path $Jobs)) {
    Write-Host "[错误] 找不到 $Jobs" -ForegroundColor Red
    exit 1
}

$flags = @()
if ($Install)   { $flags += '-Install' }
if ($Uninstall) { $flags += '-Uninstall' }
if ($Status)    { $flags += '-Status' }

$argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $Jobs) + $flags + @('-Job', 'odds')
& powershell.exe @argList
exit $LASTEXITCODE
