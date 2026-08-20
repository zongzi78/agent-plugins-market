# enc.ps1 - encoding-safe-edit launcher (PowerShell, Windows)
# Zero-dependency launcher: probe a usable runtime by EXECUTING --version
# (existence alone is not enough; python3 may be a WindowsApps store stub),
# then forward all args to enc.py (preferred) or enc.js (fallback).
# Candidate order: python3 -> python -> py -3 -> uv(run) -> node.
#   enc.ps1 selfcheck                 -> runtime list (handled natively)
#   enc.ps1 --runtime auto|python3|python|py -3|uv|node <subcommand> [options...]
# Keep this file pure ASCII (PS5.1 reads no-BOM as ANSI).
param()

$ErrorActionPreference = 'Stop'
# Forward enc.py/enc.js output with UTF-8 console encoding (cp936 console would garble Chinese)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

function Get-VersionOutput {
    param([string[]]$Cmd)
    # Localize EAP=Continue: external stderr (e.g. uv WARN) must not become a
    # terminating error; store-stub failures land in the output stream without a
    # "Python ..." signature, so usable stays false.
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

function Test-UvCmd {
    # Probe must actually launch Python (uv existing does not mean it can provide an interpreter)
    $r = Get-VersionOutput -Cmd @('uv', 'run', '--no-project', 'python', '--version')
    $ok = ($r.Code -eq 0) -and ($r.Out -match 'Python \d+\.\d+')
    $found = $null -ne (Get-Command 'uv' -ErrorAction SilentlyContinue)
    $verLine = $(if ($ok) { (($r.Out.Trim() -split "`r?`n") | Where-Object { $_ -match 'Python \d+\.\d+' } | Select-Object -First 1) } else { $null })
    return @{ found = $found; usable = $ok; version = $verLine }
}

function Test-NodeCmd {
    $r = Get-VersionOutput -Cmd @('node', '--version')
    $ok = ($r.Code -eq 0) -and ($r.Out -match 'v\d+\.\d+')
    $found = $null -ne (Get-Command 'node' -ErrorAction SilentlyContinue)
    return @{ found = $found; usable = $ok; version = $(if ($ok) { ($r.Out.Trim() -split "`r?`n")[0] } else { $null }) }
}

function Write-Json {
    param([string]$Text)
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    [Console]::WriteLine($Text)
}

function Invoke-Selfcheck {
    $py3 = Test-PythonCmd -ProbeCmd @('python3', '--version')
    $py = Test-PythonCmd -ProbeCmd @('python', '--version')
    $pyLauncher = Test-PythonCmd -ProbeCmd @('py', '-3', '--version')
    $uv = Test-UvCmd
    $node = Test-NodeCmd
    $selected = $null
    if ($py3.usable) { $selected = 'python3' }
    elseif ($py.usable) { $selected = 'python' }
    elseif ($pyLauncher.usable) { $selected = 'py -3' }
    elseif ($uv.usable) { $selected = 'uv' }
    elseif ($node.usable) { $selected = 'node' }
    $obj = @{ ok = ($null -ne $selected); runtimes = @{
        'python3' = $py3; 'python' = $py; 'py -3' = $pyLauncher; 'uv' = $uv; 'node' = $node
    }; selectedRuntime = $selected;
        message = $(if ($null -eq $selected) { 'no usable runtime; install Python or Node, or use --runtime to force' } else { $null }) }
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
    }
    elseif ($a -like '--runtime=*') {
        $runtime = $a.Substring(10)
    }
    else { $rest += $a }
}

if ($runtime -notin @('auto', 'python3', 'python', 'py -3', 'uv', 'node')) {
    Write-Json '{"ok":false,"error":"invalid --runtime value; use auto|python3|python|py -3|uv|node","exitCode":1,"hint":null}'
    exit 1
}

if ($rest.Count -gt 0 -and $rest[0] -eq 'selfcheck') {
    Invoke-Selfcheck
}

if ($runtime -eq 'auto') {
    $py3 = Test-PythonCmd -ProbeCmd @('python3', '--version')
    if ($py3.usable) { & python3 (Join-Path $scriptDir 'enc.py') @rest; exit $LASTEXITCODE }
    $py = Test-PythonCmd -ProbeCmd @('python', '--version')
    if ($py.usable) { & python (Join-Path $scriptDir 'enc.py') @rest; exit $LASTEXITCODE }
    $pyLauncher = Test-PythonCmd -ProbeCmd @('py', '-3', '--version')
    if ($pyLauncher.usable) { & py -3 (Join-Path $scriptDir 'enc.py') @rest; exit $LASTEXITCODE }
    $uv = Test-UvCmd
    if ($uv.usable) { & uv run --no-project python (Join-Path $scriptDir 'enc.py') @rest; exit $LASTEXITCODE }
    $node = Test-NodeCmd
    if ($node.usable) { & node (Join-Path $scriptDir 'enc.js') @rest; exit $LASTEXITCODE }
    Write-Json '{"ok":false,"error":"no usable runtime (python3/python/py -3/uv/node all unavailable)","exitCode":1,"hint":"install Python or Node, or use --runtime to force"}'
    exit 1
}
if ($runtime -eq 'python3') {
    $py3 = Test-PythonCmd -ProbeCmd @('python3', '--version')
    if ($py3.usable) { & python3 (Join-Path $scriptDir 'enc.py') @rest; exit $LASTEXITCODE }
    Write-Json '{"ok":false,"error":"no usable runtime python3","exitCode":1,"hint":"install python3, or use --runtime auto"}'
    exit 1
}
if ($runtime -eq 'python') {
    $py = Test-PythonCmd -ProbeCmd @('python', '--version')
    if ($py.usable) { & python (Join-Path $scriptDir 'enc.py') @rest; exit $LASTEXITCODE }
    Write-Json '{"ok":false,"error":"no usable runtime python","exitCode":1,"hint":"install python, or use --runtime auto"}'
    exit 1
}
if ($runtime -eq 'py -3') {
    $pyLauncher = Test-PythonCmd -ProbeCmd @('py', '-3', '--version')
    if ($pyLauncher.usable) { & py -3 (Join-Path $scriptDir 'enc.py') @rest; exit $LASTEXITCODE }
    Write-Json '{"ok":false,"error":"no usable runtime py -3","exitCode":1,"hint":"install Python launcher, or use --runtime auto"}'
    exit 1
}
if ($runtime -eq 'uv') {
    $uv = Test-UvCmd
    if ($uv.usable) { & uv run --no-project python (Join-Path $scriptDir 'enc.py') @rest; exit $LASTEXITCODE }
    Write-Json '{"ok":false,"error":"no usable runtime uv","exitCode":1,"hint":"install uv, or use --runtime auto"}'
    exit 1
}
if ($runtime -eq 'node') {
    $node = Test-NodeCmd
    if ($node.usable) { & node (Join-Path $scriptDir 'enc.js') @rest; exit $LASTEXITCODE }
    Write-Json '{"ok":false,"error":"no usable runtime node","exitCode":1,"hint":"install Node, or use --runtime auto"}'
    exit 1
}
