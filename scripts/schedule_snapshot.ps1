"""
竞彩快照定时任务
==================
Windows 计划任务脚本 —— 每天定时抓一次竞彩赔率存档.

安装 (管理员 PowerShell):
  powershell -ExecutionPolicy Bypass -File scripts\schedule_snapshot.ps1 -Install

查看状态:
  powershell -ExecutionPolicy Bypass -File scripts\schedule_snapshot.ps1 -Status

卸载:
  powershell -ExecutionPolicy Bypass -File scripts\schedule_snapshot.ps1 -Uninstall

默认: 每天 09:00 + 21:00 各抓一次
      (09:00 抓当天开盘赔率, 21:00 抓临场赔率 —— 临场变化最有信息量)
"""
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Status,
    [string]$Times = '09:00,21:00',
    [string]$TaskName = 'LotteryOddsSnapshot'
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) {
    Write-Host '[错误] 找不到 python, 请先安装 Python 3.10+' -ForegroundColor Red
    exit 1
}

$SnapshotPy = Join-Path $PSScriptRoot 'snapshot.py'

if ($Uninstall) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "已卸载计划任务: $TaskName" -ForegroundColor Green
    exit 0
}

if ($Status) {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($t) {
        Write-Host "计划任务存在: $TaskName" -ForegroundColor Green
        $t | Format-List TaskName, State
        Get-ScheduledTaskInfo -TaskName $TaskName | Format-List LastRunTime, NextRunTime
    } else {
        Write-Host "计划任务不存在: $TaskName" -ForegroundColor Yellow
    }
    exit 0
}

if ($Install) {
    $times = $Times -split ',' | ForEach-Object { $_.Trim() }
    foreach ($t in $times) {
        $h, $m = $t -split ':'
        $hh = [int]$h; $mm = [int]$m
        $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"& '$Python' '$SnapshotPy'`""
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg
        $trigger = New-ScheduledTaskTrigger -Daily -At "HH:mm".Replace('HH:mm', ('{0:D2}:{1:D2}' -f $hh, $mm))
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
            -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 10)
        Register-ScheduledTask -TaskName $TaskName -Action $action `
            -Trigger $trigger -Principal $principal -Settings $settings `
            -Description '竞彩赔率每日快照存档 (积累自有历史数据)' `
            -Force | Out-Null
        Write-Host "已注册: $TaskName  每天 $t" -ForegroundColor Green
    }
    Write-Host ''
    Write-Host '首次立即跑一次:' -ForegroundColor Cyan
    Write-Host "  & '$Python' '$SnapshotPy'" -ForegroundColor DarkGray
    exit 0
}

Write-Host '用法:'
Write-Host '  -Install    注册计划任务'
Write-Host '  -Status     查看状态'
Write-Host '  -Uninstall  卸载计划任务'
