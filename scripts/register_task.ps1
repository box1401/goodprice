# Register run_daily.bat as a Windows scheduled task running daily at 08:00.
# Run from PowerShell:
#   powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1

$taskName = "GoodpriceCoupangDaily"
$batPath  = "D:\Goodprice\scripts\run_daily.bat"
$workDir  = "D:\Goodprice"

if (-not (Test-Path $batPath)) {
    Write-Error "Missing $batPath"
    exit 1
}

$action    = New-ScheduledTaskAction -Execute $batPath -WorkingDirectory $workDir
$trigger   = New-ScheduledTaskTrigger -Daily -At 8:00am
$settings  = New-ScheduledTaskSettingsSet `
                -StartWhenAvailable `
                -DontStopOnIdleEnd `
                -RestartCount 2 `
                -RestartInterval (New-TimeSpan -Minutes 10) `
                -ExecutionTimeLimit (New-TimeSpan -Hours 2)

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $taskName `
    -Description "Coupang Taiwan daily deal scraper" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -User $env:USERNAME `
    -RunLevel Limited

Write-Host "Registered scheduled task: $taskName (daily 08:00)"
Write-Host "Run now : Start-ScheduledTask -TaskName $taskName"
Write-Host "Status  : Get-ScheduledTaskInfo -TaskName $taskName"
