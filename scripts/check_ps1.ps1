$content = Get-Content 'scripts/install_scheduler.ps1' -Raw
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($content, [ref]$tokens, [ref]$errors)

if ($errors.Count -eq 0) {
    Write-Host 'OK - PowerShell script syntax valid'
    Write-Host "Functions defined:"
    $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] }, $true) |
        ForEach-Object { Write-Host "  - $($_.Name)" }
} else {
    Write-Host 'FAIL:'
    $errors | ForEach-Object { Write-Host "  $($_.Extent.StartLineNumber): $($_.Message)" }
}
