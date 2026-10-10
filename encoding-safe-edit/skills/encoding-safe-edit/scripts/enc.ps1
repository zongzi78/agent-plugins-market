# enc.ps1 - encoding-safe-edit launcher (PowerShell, Windows)
# ASCII-only by design: no non-ASCII characters, no BOM, safe under any code page.
# User-facing text comes from enc.py (UTF-8, no BOM); this launcher emits only
# English JSON when no usable runtime can be found.
# Zero-dependency bootstrap: probe a runtime via --version, then forward args to enc.py.
# Candidate order: uv -> python3 -> python.
#   enc.ps1 selfcheck
#   enc.ps1 --runtime auto|uv|python3|python <subcommand> [options...]
param()

$ErrorActionPreference = 'Continue'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$impl = Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) 'enc.py'
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

function Emit-Err([string]$msg, [string]$hint) {
    [Console]::Out.WriteLine('{"ok":false,"error":"' + $msg + '","exitCode":1,"hint":"' + $hint + '"}')
}

$rest = @($args)
$runtime = 'auto'
for ($i = 0; $i -lt $rest.Count; $i++) {
    if ($rest[$i] -eq '--runtime' -and $i + 1 -lt $rest.Count) {
        $runtime = $rest[$i + 1]
        $rest = @($rest | Select-Object -First $i) + @($rest | Select-Object -Skip ($i + 2))
        break
    }
    if ($rest[$i] -like '--runtime=*') {
        $runtime = $rest[$i].Substring(10)
        $rest = @($rest | Select-Object -First $i) + @($rest | Select-Object -Skip ($i + 1))
        break
    }
}

if ($runtime -notin @('auto', 'uv', 'python3', 'python')) {
    Emit-Err ('invalid --runtime value: ' + $runtime) 'allowed: auto|uv|python3|python'
    exit 1
}

if ($rest.Count -ge 1 -and $rest[0] -eq 'selfcheck') {
    $items = @()
    foreach ($n in $candidates) { $items += (Probe $n) }
    $sel = @($items | Where-Object { $_.usable } | Select-Object -First 1)
    $obj = @{
        ok             = ($sel.Count -gt 0)
        launcher       = 'enc.ps1'
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
if ($null -eq $chosen) {
    Emit-Err ('no usable Python runtime (probed: ' + ($order -join ', ') + ')') 'install uv or python3/python; refusing to run in an unverified environment'
    exit 1
}

$full = @()
$full += $chosen.prefix
$full += $impl
$full += $rest
& $full[0] @($full | Select-Object -Skip 1)
exit $LASTEXITCODE
