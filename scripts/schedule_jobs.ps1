# ================================================================
# 彩票实验室 — 计划任务统一管理
# ---------------------------------------------------------------
# 管理两个后台任务:
#   1) LotteryOddsSnapshot  竞彩赔率快照存档 (每天 09:00 + 21:00)
#   2) LotteryDrawUpdate    开奖数据增量更新 (每天 21:30)
#
# 用法:
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs.ps1 -Install
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs.ps1 -Status
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs.ps1 -Uninstall
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs.ps1 -Install -Job odds
#   powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs.ps1 -Status -Job draw
#
# ★ 两个必须记住的 PowerShell 坑 (都真实踩过):
#   1. 本文件必须存为 **UTF-8 with BOM**。PowerShell 5.1 读无 BOM 的 .ps1
#      会按系统 ANSI 代码页 (中文=GBK) 解码 → 中文乱码破坏引号 → 语法错误。
#      检查: python scripts\check_script_encoding.py
#   2. `param()` 块必须是脚本的**第一个语句**, 前面不能有任何表达式。
#      ★ 所以文档不能用 """...""" (那是 here-string 表达式, 不是注释),
#        必须用 # 注释, 或者把 param() 放到文件第一行。
# ================================================================
param(
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Status,
    [ValidateSet('all', 'odds', 'draw')]
    [string]$Job = 'all'
)

$ErrorActionPreference = 'Stop'
$Python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $Python) {
    $py = (Get-Command py -ErrorAction SilentlyContinue).Source
    if ($py) { $Python = "$py -3" }
}
if (-not $Python) {
    Write-Host '[错误] 找不到 python, 请先安装 Python 3.10+' -ForegroundColor Red
    exit 1
}

# ---- 任务定义 ----
# name / times / script / 说明
$JOBS = @(
    @{
        Name    = 'LotteryOddsSnapshot'
        Times   = @('09:00', '21:00')
        Script  = 'snapshot.py'
        Desc    = '竞彩赔率每日快照存档 (积累自有历史数据)'
        Note    = '09:00 抓开盘赔率, 21:00 抓临场赔率'
    },
    @{
        Name    = 'LotteryDrawUpdate'
        Times   = @('21:30')
        Script  = 'update_draws.py'
        Desc    = '开奖数据每日增量更新 (官方 API → SQLite)'
        Note    = '21:30 抓当晚开奖 (20:30-21:00 开奖)'
    }
)

function Get-JobList {
    if ($Job -eq 'all') { return $JOBS }
    return @($JOBS | Where-Object {
        ($_.Name -like '*Odds*' -and $Job -eq 'odds') -or
        ($_.Name -like '*Draw*'  -and $Job -eq 'draw')
    })
}

if ($Uninstall) {
    foreach ($j in Get-JobList) {
        Unregister-ScheduledTask -TaskName $j.Name -Confirm:$false -ErrorAction SilentlyContinue
        Write-Host "已卸载: $($j.Name)" -ForegroundColor Green
    }
    exit 0
}

if ($Status) {
    $allFound = $true
    foreach ($j in Get-JobList) {
        $t = Get-ScheduledTask -TaskName $j.Name -ErrorAction SilentlyContinue
        if ($t) {
            Write-Host "✅ $($j.Name)  [$($t.State)]" -ForegroundColor Green
            $trig = $t.Triggers | ForEach-Object {
                ($_.StartBoundary -split '\.')[0]
            }
            Write-Host "     触发: $($trig -join ' / ')"
            $info = Get-ScheduledTaskInfo -TaskName $j.Name -ErrorAction SilentlyContinue
            if ($info) {
                Write-Host "     上次: $($info.LastRunTime)  结果: $($info.LastTaskResult)  下次: $($info.NextRunTime)"
            }
        } else {
            $allFound = $false
            Write-Host "❌ $($j.Name) 不存在" -ForegroundColor Yellow
        }
    }
    if (-not $allFound) {
        Write-Host ''
        Write-Host '  安装: powershell -ExecutionPolicy Bypass -File scripts\schedule_jobs.ps1 -Install' -ForegroundColor DarkGray
    }
    exit 0
}

if ($Install) {
    foreach ($j in Get-JobList) {
        $scriptPath = Join-Path $PSScriptRoot $j.Script
        if (-not (Test-Path $scriptPath)) {
            Write-Host "[跳过] $($j.Name): 找不到 $($j.Script)" -ForegroundColor Yellow
            continue
        }
        $triggers = @()
        foreach ($t in $j.Times) {
            $parts = $t -split ':'
            $at = '{0:D2}:{1:D2}' -f [int]$parts[0], [int]$parts[1]
            $triggers += New-ScheduledTaskTrigger -Daily -At $at
        }
        # ★ 1 个任务 + N 个 trigger (早期版本对每个时间用同一 TaskName 注册,
        #   后面的 -Force 覆盖前面的 → 只剩 1 个触发时间)
        $arg = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -Command `"& '$Python' '$scriptPath'`""
        $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arg
        $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME `
            -LogonType Interactive -RunLevel Limited
        $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
            -DontStopIfGoingOnBatteries -StartWhenAvailable `
            -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
            -MultipleInstances IgnoreNew

        Register-ScheduledTask -TaskName $j.Name -Action $action `
            -Trigger $triggers -Principal $principal -Settings $settings `
            -Description $j.Desc -Force | Out-Null
        Write-Host "已注册: $($j.Name)  每天 $($j.Times -join ' / ')  ($($j.Note))" -ForegroundColor Green
    }
    exit 0
}

Write-Host '用法:'
Write-Host '  -Install     注册计划任务'
Write-Host '  -Status      查看状态'
Write-Host '  -Uninstall   卸载计划任务'
Write-Host '  -Job         all (默认) / odds / draw'
