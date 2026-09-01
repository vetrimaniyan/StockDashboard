<#
.SYNOPSIS
  Start the Alpha-500 API with its in-process scheduler, unless it is already up.

.DESCRIPTION
  The nightly pipeline is scheduled INSIDE the API process (SRS 2.1, D-6),
  because DuckDB allows one writer or many readers and never both. So the
  thing that has to survive a reboot is not the pipeline - it is this server.
  If it is not running at 18:45 IST, there is no run at all, and nothing
  anywhere records that there wasn't.

  Registered as a Windows Scheduled Task at logon by register_api_task.ps1.

  The guard below matters. A second instance would fail on the port, and worse,
  would try to open the store read-write while the first holds it - so a
  double-start is not a harmless duplicate but a broken second process.
#>

[CmdletBinding()]
param(
    [string]$RepoRoot,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

# $PSScriptRoot is not populated on every invocation path, and a param default
# that resolves to empty fails far from the cause. Resolve it in the body with
# a fallback instead.
if (-not $RepoRoot) {
    $here = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
    $RepoRoot = Split-Path -Parent $here
}
# Deliberately NOT api.log: the running server holds that open for stdout and
# Windows keeps an exclusive handle on it, so writing here would fail exactly
# when the guard below is doing its job. Forward slashes throughout - they work
# on Windows and survive being edited by tools that treat backslash as escape.
$log = Join-Path $RepoRoot 'data/start_api.log'
$python = Join-Path $RepoRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path $python)) {
    $python = Join-Path $RepoRoot '.venv\Scripts\python.exe'
}

function Write-Line([string]$text) {
    # Best effort. Losing a log line must never stop the server starting -
    # the whole point of this script is that the 18:45 run happens.
    try {
        "$([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))  $text" |
            Out-File -FilePath $log -Append -Encoding utf8 -ErrorAction Stop
    } catch { }
}

# Already serving? Leave it alone. Starting a second one is worse than a no-op.
$listening = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -eq $Port }
if ($listening) {
    Write-Line "start_api: port $Port already listening (PID $($listening[0].OwningProcess)); leaving it be"
    exit 0
}

# A CLI pipeline or backfill holds the store read-write. Starting the server
# now would only fail on the lock, and it would take the scheduler down with
# it. Better to skip this launch; the task fires again at next logon.
$writer = Get-CimInstance Win32_Process -Filter "Name like '%python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match 'alpha500\.cli\s+(pipeline|backfill|rebuild|materialise|indices|marketcap)' }
if ($writer) {
    Write-Line "start_api: a CLI writer is running (PID $($writer[0].ProcessId)); not starting"
    exit 0
}

if (-not (Test-Path $python)) {
    Write-Line "start_api: no interpreter at $python"
    exit 1
}

Write-Line "start_api: launching serve --with-scheduler"
Start-Process -FilePath $python `
    -ArgumentList '-m', 'alpha500.cli', 'serve', '--with-scheduler' `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput (Join-Path $RepoRoot 'data/api.log') `
    -RedirectStandardError (Join-Path $RepoRoot 'data/api.err.log') `
    -WindowStyle Hidden

# Confirm it actually came up, rather than reporting success on a launch that
# died on startup - a silent failure here means no pipeline that night.
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Seconds 1
    $up = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalPort -eq $Port }
    if ($up) {
        Write-Line "start_api: up on port $Port (PID $($up[0].OwningProcess))"
        exit 0
    }
}

Write-Line "start_api: did not reach port $Port within 20s - see the lines above"
exit 1
