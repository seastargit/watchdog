<#
Register a Scheduled Task to run the inode monitor at system startup (Windows Task Scheduler).
This creates a basic task that runs on system startup. Run in an elevated PowerShell session.
Usage:
  .\install_inodemonitor_schtasks.ps1 -PythonPath 'C:\Python39\python.exe' -RepoPath 'C:\path\to\repo'
#>
param(
    [string]$PythonPath = "C:\\Python39\\python.exe",
    [string]$RepoPath = "C:\\path\\to\\repo",
    [string]$TaskName = "InodeMonitor",
    [string]$Author = "InodeMonitor"
)

$script = Join-Path $RepoPath "tools\inode_monitor.py"
$config = Join-Path $RepoPath "tools\inode_monitor.ini"

if (-not (Test-Path $script)) {
    Write-Error "Monitor script not found: $script"
    exit 2
}

$action = New-ScheduledTaskAction -Execute $PythonPath -Argument "`"$script`" `"$config`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Description "iNode TCP Monitor"

Write-Output "Scheduled task '$TaskName' registered. Use Get-ScheduledTask / Start-ScheduledTask to manage it."
