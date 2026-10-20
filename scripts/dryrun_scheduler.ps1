# Dry-run：只显示会安装哪些任务，不实际写注册表
. "$PSScriptRoot\install_scheduler.ps1" -ProjectDir "F:\MiniMAX工作区\体育彩票预测项目" -DryRun 2>&1 | Out-Null
# 上面会失败因为脚本本身有 Uninstall 分支不能 source
# 改用 dot-sourcing 不带参数
EOF

# 实际上手动 dot-source 看函数定义
. "F:\MiniMAX工作区\体育彩票预测项目\scripts\install_scheduler.ps1"

Write-Host "===== Loaded OK ====="
Write-Host "Tasks defined:"
foreach ($task in $tasks) {
    $cronStr = $task.Cron -join ' '
    Write-Host "  - $($task.Name) [$cronStr] -> main.py $($task.Command) $($task.Args)"
}
Write-Host ""
Write-Host "Note: Run with -Install flag to actually create Windows tasks"
