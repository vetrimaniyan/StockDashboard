<#
.SYNOPSIS
  Register (or remove) the Windows Scheduled Task that keeps the Alpha-500 API
  running, so the nightly pipeline fires without anyone being logged into a
  terminal.

.DESCRIPTION
  The EOD pipeline is scheduled inside the API process (SRS 2.1, D-6). A task
  that ran `alpha500 pipeline` directly would instead collide with the serving
  API over DuckDB's single-writer lock, and duplicate the run. So this task
  starts the SERVER; the 18:45 IST fire then happens in-process as designed.

  Runs at logon rather than at boot: at boot it would need SYSTEM or stored
  credentials, and SYSTEM writes files as a different principal than the one
  that owns this repo. Logon keeps ownership consistent, and the scheduler's
  six-hour misfire grace covers a machine that wakes late.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\register_api_task.ps1
  powershell -ExecutionPolicy Bypass -File scripts\register_api_task.ps1 -Remove
#>

[CmdletBinding()]
param(
    [string]$TaskName = 'Alpha500 API',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$repoRoot = Split-Path -Parent $here
$launcher = Join-Path $repoRoot 'scripts\start_api.ps1'

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'."
        Write-Host "The API will no longer start at logon, so the 18:45 IST"
        Write-Host "pipeline runs only while you start the server yourself."
    } else {
        Write-Host "No scheduled task named '$TaskName'."
    }
    return
}

if (-not (Test-Path $launcher)) { throw "launcher not found at $launcher" }

$action = New-ScheduledTaskAction `
    -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`"" `
    -WorkingDirectory $repoRoot

# At logon, plus a retry a few minutes later. The first attempt can lose a race
# with a network stack that is not up yet, and the calendar seed wants the net.
$triggers = @(
    New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Principal $principal `
    -Description 'Starts the Alpha-500 API, which carries the in-process EOD scheduler (18:45 IST).' `
    -Force | Out-Null

Write-Host "Registered '$TaskName' - starts the API at logon."
Write-Host ""
Write-Host "  Verify : Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Run now: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  Remove : scripts\register_api_task.ps1 -Remove"
Write-Host ""
Write-Host "This makes the pipeline survive a reboot, not the machine being off."
Write-Host "If the PC is asleep at 18:45 IST the run happens when it wakes,"
Write-Host "once, within the scheduler's six-hour misfire grace."
