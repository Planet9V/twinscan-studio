<#
.SYNOPSIS
  Install or uninstall a Windows 11 Scheduled Task that automatically streams
  all local USB / laptop cameras into TwinScan Overwatch at user logon with
  zero visible terminal windows.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\scripts\install_camera_autostart.ps1
  powershell -ExecutionPolicy Bypass -File .\scripts\install_camera_autostart.ps1 -Uninstall
#>
param(
  [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "EigeniaTwinScanCameraBridge"
$RepoDir = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

if ($Uninstall) {
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "Removed scheduled task '$TaskName'."
  exit 0
}

$PythonExe = Join-Path $RepoDir ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $PythonExe)) {
  $PythonExe = Join-Path $RepoDir ".venv\Scripts\python.exe"
}
if (-not (Test-Path $PythonExe)) {
  $PythonExe = (Get-Command python).Source
}

$ArgsStr = "-m src.bridge.mac_camera_bridge --all-cameras --width 1920 --height 1080 --fps 10"
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $ArgsStr -WorkingDirectory $RepoDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -RestartCount 999 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit (New-TimeSpan -Days 0)

Register-ScheduledTask `
  -TaskName $TaskName `
  -Action $Action `
  -Trigger $Trigger `
  -Settings $Settings `
  -Description "Eigenia TwinScan Studio automatic multi-camera Overwatch bridge" `
  -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Write-Host "Installed & started Windows 11 auto-start task '$TaskName' ($PythonExe)."
