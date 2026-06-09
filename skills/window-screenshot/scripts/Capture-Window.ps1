# Capture-Window.ps1
# Windows screenshot tool — main entry point
# Captures specified windows via PrintWindow API with BitBlt fallback.

param(
    [string]$ProcessName,
    [int]$ProcessId,
    [string]$WindowTitle,
    [string]$WindowClass,
    [string]$Hwnd,
    [string]$OutputPath,
    [switch]$ListWindows
)

# Load modules
. (Join-Path $PSScriptRoot "Win32-APIs.ps1")
. (Join-Path $PSScriptRoot "Window-Manager.ps1")
. (Join-Path $PSScriptRoot "Capture-Engine.ps1")

# ============================================================
# ListWindows mode
# ============================================================
if ($ListWindows) {
    $windows = Get-WindowList
    $result = @{
        success = $true
        windows = $windows
    }
    Write-Output (Output-Json $result)
    exit 0
}

# ============================================================
# Validate: at least one matching criteria required
# ============================================================
if (-not $ProcessName -and $ProcessId -le 0 -and -not $WindowTitle -and -not $WindowClass -and -not $Hwnd) {
    $errorResult = @{
        success = $false
        error = "Please provide at least one matching criteria: -ProcessName, -ProcessId, -WindowTitle, -WindowClass, or -Hwnd"
    }
    Write-Error (Output-Json $errorResult)
    Write-Output (Output-Json $errorResult)
    exit 1
}

# ============================================================
# Enumerate and match windows
# ============================================================
$allWindows = Get-WindowList
$matches = Find-TargetWindows -allWindows $allWindows -ProcessName $ProcessName -ProcessId $ProcessId -WindowTitle $WindowTitle -WindowClass $WindowClass -Hwnd $Hwnd

if ($matches.Count -eq 0) {
    $errorResult = @{
        success = $false
        error = "No matching window found. Use -ListWindows to see available windows."
    }
    Write-Error (Output-Json $errorResult)
    Write-Output (Output-Json $errorResult)
    exit 1
}

if ($matches.Count -gt 1) {
    $uniquePids = @($matches | ForEach-Object { $_.pid } | Select-Object -Unique)
    if ($uniquePids.Count -eq 1) {
        # All same PID — pick the largest window
        $targetWindow = $matches | Sort-Object {
            $h = [IntPtr]::new($_.hwnd)
            $r = New-Object RECT
            [Win32]::GetWindowRect($h, [ref]$r) | Out-Null
            ($r.Right - $r.Left) * ($r.Bottom - $r.Top)
        } -Descending | Select-Object -First 1
    }
    else {
        # Different PIDs — return list for user to choose
        $errorResult = @{
            success = $false
            error = "Found $($matches.Count) matching windows from $($uniquePids.Count) different processes"
            windows = $matches
            hint = "Use -ProcessId or -Hwnd to select a specific window"
        }
        Write-Error (Output-Json $errorResult)
        Write-Output (Output-Json $errorResult)
        exit 2
    }
}
else {
    $targetWindow = $matches[0]
}

# ============================================================
# Generate output path
# ============================================================
if (-not $OutputPath) {
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $OutputPath = Join-Path $env:TEMP "screenshot_${timestamp}.png"
}

$outputDir = Split-Path $OutputPath -Parent
if ($outputDir -and -not (Test-Path $outputDir)) {
    New-Item -ItemType Directory -Path $outputDir -Force | Out-Null
}

# ============================================================
# Capture and output
# ============================================================
$result = Capture-WindowScreenshot -window $targetWindow -outputPath $OutputPath
Write-Output (Output-Json $result)

if ($result.success) {
    exit 0
}
else {
    Write-Error (Output-Json $result)
    exit 1
}
