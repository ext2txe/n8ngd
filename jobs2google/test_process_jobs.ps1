$python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$scriptPath = Join-Path $PSScriptRoot "process-jobs.py"
$sourceFolder = "D:\src\n8ngd\j2gtest\j2gincoming"
$expectedDestinationFolder = "/upwork/20260511"
$destinationArgument = "/upwork"
$tokenPath = Join-Path $env:LOCALAPPDATA "jobs2google\google_drive_token.json"

if (-not (Test-Path $python)) {
    Write-Error "Virtual environment Python not found at $python"
    exit 1
}

if (-not (Test-Path $scriptPath)) {
    Write-Error "Script not found at $scriptPath"
    exit 1
}

if (-not (Test-Path $sourceFolder)) {
    Write-Error "Source folder not found at $sourceFolder"
    exit 1
}

Write-Host "Source folder: $sourceFolder"
Write-Host "Expected final Google Drive folder: $expectedDestinationFolder"
Write-Host "process-jobs.py destination argument: $destinationArgument"
Write-Host "jobs2google token file: $tokenPath"

if (-not (Test-Path $tokenPath)) {
    Write-Error "jobs2google token file not found at $tokenPath. Run authorize_jobs2google.py first."
    exit 1
}

# process-jobs.py appends the current date folder automatically, so the hardwired
# destination argument remains /upwork in order to produce the requested final
# destination folder /upwork/20260511.
& $python $scriptPath $sourceFolder $destinationArgument
exit $LASTEXITCODE
