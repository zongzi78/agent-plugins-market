# detect.ps1 - encoding-safe-edit zero-dependency gate probe (PowerShell)
# Outputs a single category token:
#   utf-8-bom | utf-16le | utf-16be | nul-heavy | ascii | utf-8+gbk-dual | utf-8 | gbk | gb18030 | unknown
# Strict decoders MUST use ExceptionFallback explicitly
# (.NET default best-fit fallback never throws and cannot be used for strict checks).
# NOTE: keep this file pure ASCII (PowerShell 5.1 reads no-BOM files as ANSI).
param(
    [Parameter(Mandatory = $true)][string]$Path
)
$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { Write-Output 'unknown'; exit 0 }
$b = [System.IO.File]::ReadAllBytes((Resolve-Path -LiteralPath $Path))
$strict = {
    param($enc, $bytes)
    try {
        if ($null -eq $bytes -or $bytes.Length -eq 0) { return $true }
        [void]$enc.GetString($bytes)
        return $true
    } catch { return $false }
}
$utf8s = New-Object System.Text.UTF8Encoding($false, $true)
$gbk = [System.Text.Encoding]::GetEncoding(936, [System.Text.EncoderFallback]::ExceptionFallback, [System.Text.DecoderFallback]::ExceptionFallback)
$gb18030 = [System.Text.Encoding]::GetEncoding(54936, [System.Text.EncoderFallback]::ExceptionFallback, [System.Text.DecoderFallback]::ExceptionFallback)
$u16le = [System.Text.Encoding]::GetEncoding(1200, [System.Text.EncoderFallback]::ExceptionFallback, [System.Text.DecoderFallback]::ExceptionFallback)
$u16be = [System.Text.Encoding]::GetEncoding(1201, [System.Text.EncoderFallback]::ExceptionFallback, [System.Text.DecoderFallback]::ExceptionFallback)
$rest = { param($arr, $start) if ($arr.Length -gt $start) { $arr[$start..($arr.Length-1)] } else { @() } }
$nulHeavy = $b.Length -gt 0 -and (($b | Where-Object { $_ -eq 0 }).Count / $b.Length) -gt 0.01
if ($b.Length -ge 4 -and $b[0] -eq 0xFF -and $b[1] -eq 0xFE -and $b[2] -eq 0x00 -and $b[3] -eq 0x00) { Write-Output 'unknown'; exit 0 }
elseif ($b.Length -ge 4 -and $b[0] -eq 0x00 -and $b[1] -eq 0x00 -and $b[2] -eq 0xFE -and $b[3] -eq 0xFF) { Write-Output 'unknown'; exit 0 }
elseif ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) {
    if (& $strict $utf8s (& $rest $b 3)) { Write-Output 'utf-8-bom' } else { Write-Output 'unknown' }
    exit 0
}
elseif ($b.Length -ge 2 -and $b[0] -eq 0xFF -and $b[1] -eq 0xFE) {
    if (& $strict $u16le (& $rest $b 2)) { Write-Output 'utf-16le' } else { Write-Output 'unknown' }
    exit 0
}
elseif ($b.Length -ge 2 -and $b[0] -eq 0xFE -and $b[1] -eq 0xFF) {
    if (& $strict $u16be (& $rest $b 2)) { Write-Output 'utf-16be' } else { Write-Output 'unknown' }
    exit 0
}
elseif ($nulHeavy) { Write-Output 'nul-heavy'; exit 0 }
elseif ($b.Length -eq 0 -or -not ($b | Where-Object { $_ -ge 0x80 })) { Write-Output 'ascii'; exit 0 }
elseif (& $strict $utf8s $b) {
    if (& $strict $gbk $b) { Write-Output 'utf-8+gbk-dual' } else { Write-Output 'utf-8' }
    exit 0
}
elseif (& $strict $gbk $b) { Write-Output 'gbk'; exit 0 }
elseif (& $strict $gb18030 $b) { Write-Output 'gb18030'; exit 0 }
else { Write-Output 'unknown'; exit 0 }