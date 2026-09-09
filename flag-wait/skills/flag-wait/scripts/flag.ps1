# flag.ps1 - flag-wait launcher (PowerShell, Windows)
# Zero-dependency launcher: probe a usable runtime by EXECUTING --version,
# then forward all args to flag.py.
# Candidate order: uv -> python3 -> python.
#   flag.ps1 selfcheck                     -> runtime list (handled natively)
#   flag.ps1 --runtime auto|uv|python3|python <subcommand> [options...]
# Keep this file pure ASCII (PS5.1 reads no-BOM as ANSI).
param()

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-VersionOutput {
    param([string[]]$Cmd)
    $oldEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $exe = $Cmd[0]
        $rest = @($Cmd | Select-Object -Skip 1)
        $out = & $exe @rest 2>&1 | Out-String
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
        return @{ Code = $code; Out = $out }
    } catch {
        return @{ Code = 999; Out = '' }
    } finally {
        $ErrorActionPreference = $oldEAP
    }
}

function Test-PythonCmd {
    param([string[]]$ProbeCmd)
    $r = Get-VersionOutput -Cmd $ProbeCmd
    $ok = ($r.Code -eq 0) -and ($r.Out -match 'Python \d+\.\d+')
    $found = $null -ne (Get-Command $ProbeCmd[0] -ErrorAction SilentlyContinue)
    return @{ found = $found; usable = $ok; version = $(if ($ok) { ($r.Out.Trim() -split "`r?`n")[0] } else { $null }) }
}

function Set-UvCache {
    $tmp = [System.IO.Path]::GetTempPath()
    $env:UV_CACHE_DIR = Join-Path $tmp "uv\cache"
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $tmp "uv\python"
    $env:UV_PYTHON_CACHE_DIR = Join-Path $tmp "uv\pycache"
}

function Test-UvCmd {
    Set-UvCache
    $r = Get-VersionOutput -Cmd @('uv', 'run', '--no-project', 'python', '--version')
    $ok = ($r.Code -eq 0) -and ($r.Out -match 'Python \d+\.\d+')
    $found = $null -ne (Get-Command 'uv' -ErrorAction SilentlyContinue)
    $verLine = $(if ($ok) { (($r.Out.Trim() -split "`r?`n") | Where-Object { $_ -match 'Python \d+\.\d+' } | Select-Object -First 1) } else { $null })
    return @{ found = $found; usable = $ok; version = $verLine }
}

function Write-Json {
    param([string]$Text)
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::WriteLine($Text)
}

function Invoke-Selfcheck {
    $py3 = Test-PythonCmd -ProbeCmd @('python3', '--version')
    $py = Test-PythonCmd -ProbeCmd @('python', '--version')
    $uv = Test-UvCmd
    $selected = $null
    if ($uv.usable) { $selected = 'uv' }
    elseif ($py3.usable) { $selected = 'python3' }
    elseif ($py.usable) { $selected = 'python' }
    $obj = @{ ok = ($null -ne $selected); runtimes = @{
        'python3' = $py3; 'python' = $py; 'uv' = $uv
    }; selectedRuntime = $selected;
        message = $(if ($null -eq $selected) { 'no usable runtime; install Python or use --runtime to force' } else { $null }) }
    Write-Json ($obj | ConvertTo-Json -Depth 5 -Compress)
    exit 0
}

# ---- parse args ----
$runtime = 'auto'
$rest = @()
for ($i = 0; $i -lt $args.Count; $i++) {
    $a = $args[$i]
    if ($a -eq '--runtime') {
        if ($i + 1 -lt $args.Count) { $runtime = $args[$i + 1]; $i++ } else { $runtime = '' }
    } elseif ($a -like '--runtime=*') {
        $runtime = $a.Substring(10)
    } else {
        $rest += $a
    }
}

if ($runtime -notin @('auto', 'uv', 'python3', 'python')) {
    Write-Json '{"ok":false,"error":"invalid --runtime value; use auto|uv|python3|python","exitCode":1,"hint":null}'
    exit 1
}

if ($rest.Count -gt 0 -and $rest[0] -eq 'selfcheck') {
    Invoke-Selfcheck
}

if ($runtime -eq 'auto') {
    $uv = Test-UvCmd
    if ($uv.usable) { Set-UvCache; & uv run --no-project python (Join-Path $scriptDir 'flag.py') @rest; exit $LASTEXITCODE }
    $py3 = Test-PythonCmd -ProbeCmd @('python3', '--version')
    if ($py3.usable) { & python3 (Join-Path $scriptDir 'flag.py') @rest; exit $LASTEXITCODE }
    $py = Test-PythonCmd -ProbeCmd @('python', '--version')
    if ($py.usable) { & python (Join-Path $scriptDir 'flag.py') @rest; exit $LASTEXITCODE }
    Write-Json '{"ok":false,"error":"no usable runtime (uv/python3/python all unavailable)","exitCode":1,"hint":"install Python, or use --runtime to force"}'
    exit 1
}
if ($runtime -eq 'uv') {
    Set-UvCache
    $uv = Test-UvCmd
    if ($uv.usable) { & uv run --no-project python (Join-Path $scriptDir 'flag.py') @rest; exit $LASTEXITCODE }
    Write-Json '{"ok":false,"error":"no usable runtime uv","exitCode":1,"hint":"install uv, or use --runtime auto"}'
    exit 1
}
if ($runtime -eq 'python3') {
    $py3 = Test-PythonCmd -ProbeCmd @('python3', '--version')
    if ($py3.usable) { & python3 (Join-Path $scriptDir 'flag.py') @rest; exit $LASTEXITCODE }
    Write-Json '{"ok":false,"error":"no usable runtime python3","exitCode":1,"hint":"install python3, or use --runtime auto"}'
    exit 1
}
if ($runtime -eq 'python') {
    $py = Test-PythonCmd -ProbeCmd @('python', '--version')
    if ($py.usable) { & python (Join-Path $scriptDir 'flag.py') @rest; exit $LASTEXITCODE }
    Write-Json '{"ok":false,"error":"no usable runtime python","exitCode":1,"hint":"install python, or use --runtime auto"}'
    exit 1
}