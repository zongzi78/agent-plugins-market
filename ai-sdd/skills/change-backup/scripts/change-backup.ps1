# change-backup.ps1 - change-backup launcher (PowerShell, Windows)
# Zero-dependency launcher: probes a usable runtime by EXECUTING --version,
# then forwards all args to change-backup.py.
# Candidate order: uv -> python3 -> python.
#   change-backup.ps1 selfcheck
#   change-backup.ps1 --runtime auto|uv|python3|python <subcommand> [options]
# Keep this file pure ASCII (PS5.1 reads no-BOM as ANSI).
param()

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$impl = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'change-backup.py'
$candidates = @('uv', 'python3', 'python')

function Set-UvCache {
    $t = [System.IO.Path]::GetTempPath()
    $env:UV_CACHE_DIR = Join-Path $t 'uv\cache'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $t 'uv\python'
    $env:UV_PYTHON_CACHE_DIR = Join-Path $t 'uv\pycache'
}

function Get-Spec([string]$n) {
    if ($n -eq 'uv') {
        Set-UvCache
        return @{ name = 'uv'; prefix = @('uv', 'run', '--no-project', 'python'); probe = @('uv', 'run', '--no-project', 'python', '--version') }
    }
    if ($n -eq 'python3') { return @{ name = 'python3'; prefix = @('python3'); probe = @('python3', '--version') } }
    return @{ name = 'python'; prefix = @('python'); probe = @('python', '--version') }
}

function Run-Cmd([string[]]$c) {
    try {
        $out = & $c[0] @($c | Select-Object -Skip 1) 2>&1 | Out-String
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
    } catch {
        return @{ code = 999; out = '' }
    }
    return @{ code = $code; out = $out }
}

function Probe([string]$n) {
    $s = Get-Spec $n
    $r = Run-Cmd $s.probe
    $ok = ($r.code -eq 0) -and ($r.out -match 'Python \d+\.\d+')
    $ver = $null
    if ($ok) { $ver = (($r.out.Trim() -split "`r?`n") | Where-Object { $_ -match 'Python \d+\.\d+' } | Select-Object -First 1) }
    return @{ name = $n; found = ($null -ne (Get-Command $n -ErrorAction SilentlyContinue)); usable = $ok; version = $ver; prefix = $s.prefix }
}

function Emit-NoRuntime([string[]]$probed) {
    $msg = 'no usable python runtime (probed: ' + ($probed -join ', ') + ')'
    [Console]::Out.WriteLine('{"ok":false,"error":"' + $msg + '","exitCode":1,"hint":"install uv, or python3/python; refusing to work rather than working unsafely"}')
}
$rest = @($args)
$runtime = 'auto'
if ($rest.Count -ge 2 -and $rest[0] -eq '--runtime') {
    $runtime = $rest[1]
    $rest = @($rest | Select-Object -Skip 2)
}

if ($runtime -notin @('auto', 'uv', 'python3', 'python')) {
    [Console]::Out.WriteLine('{"ok":false,"error":"unknown runtime: ' + $runtime + '","exitCode":1,"hint":"use auto|uv|python3|python"}')
    exit 1
}

if ($rest.Count -ge 1 -and $rest[0] -eq 'selfcheck') {
    $items = @()
    foreach ($n in $candidates) { $items += (Probe $n) }
    $sel = @($items | Where-Object { $_.usable } | Select-Object -First 1)
    $obj = @{
        ok             = ($sel.Count -gt 0)
        launcher       = 'change-backup.ps1'
        implementation = $impl
        candidates     = $items
        selected       = $(if ($sel.Count -gt 0) { $sel[0].name } else { $null })
    }
    [Console]::Out.WriteLine(($obj | ConvertTo-Json -Depth 5 -Compress))
    if ($sel.Count -gt 0) { exit 0 } else { exit 1 }
}

$order = @($candidates)
if ($runtime -ne 'auto') { $order = @($runtime) }

$chosen = $null
foreach ($n in $order) {
    $p = Probe $n
    if ($p.usable) { $chosen = $p; break }
}
if ($null -eq $chosen) { Emit-NoRuntime $order; exit 1 }

$full = @()
$full += $chosen.prefix
$full += $impl
$full += $rest
& $full[0] @($full | Select-Object -Skip 1)
exit $LASTEXITCODE