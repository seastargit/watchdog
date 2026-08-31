<#
Install Inode Monitor as a Windows service using nssm (Non-Sucking Service Manager)
Requirements:
- nssm.exe available in PATH, or set $nssmPath accordingly.
- Adjust $pythonPath and $scriptPath to match your environment.

Usage (run as Administrator):
  .\install_inodemonitor_nssm.ps1 -PythonPath 'C:\Python39\python.exe' -RepoPath 'C:\path\to\repo'
#>
param(
    [string]$NssmPath = "nssm",
    [string]$PythonPath = "C:\\Python39\\python.exe",
    [string]$RepoPath = "C:\\path\\to\\repo",
    [string]$ServiceName = "InodeMonitor"
)

$scriptPath = Join-Path $RepoPath "tools\inode_monitor.py"
$configPath = Join-Path $RepoPath "tools\inode_monitor.ini"

if (-not (Test-Path $scriptPath)) {
    Write-Error "Monitor script not found: $scriptPath"
    exit 2
}

$exec = $PythonPath
$args = "`"$scriptPath`" `"$configPath`""

Write-Output "Installing service $ServiceName using nssm..."
& $NssmPath install $ServiceName $exec $args
& $NssmPath set $ServiceName AppDirectory $RepoPath
& $NssmPath set $ServiceName DisplayName "iNode TCP Monitor"
& $NssmPath set $ServiceName Start SERVICE_AUTO_START

Write-Output "Service installed. Start it with: nssm start $ServiceName"
