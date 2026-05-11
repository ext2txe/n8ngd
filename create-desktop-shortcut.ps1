$desktopPath = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopPath "n8ngd.lnk"
$runScriptPath = Join-Path $PSScriptRoot "run.ps1"
$powerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if (-not (Test-Path $runScriptPath)) {
    Write-Error "Run script not found at $runScriptPath"
    exit 1
}

if (-not (Test-Path $powerShellExe)) {
    Write-Error "Windows PowerShell not found at $powerShellExe"
    exit 1
}

$wshShell = New-Object -ComObject WScript.Shell
$shortcut = $wshShell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $powerShellExe
$shortcut.Arguments = '-ExecutionPolicy Bypass -File "' + $runScriptPath + '"'
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Description = "Launch n8ngd"
$shortcut.Save()

Write-Host "Desktop shortcut created at $shortcutPath"
