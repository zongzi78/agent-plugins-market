# Window-Manager.ps1
# Window enumeration, filtering, and JSON output helpers.
# Requires: Win32-APIs.ps1 (dot-sourced before this file)

$script:ProcessNameLookupBlocked = $false

function Get-WindowList {
    $windows = [System.Collections.ArrayList]::new()
    $script:ProcessNameLookupBlocked = $false

    # Probe once whether Get-Process works in this environment at all.
    # Querying our own process always succeeds in a healthy environment,
    # so any failure here means the environment restricts process lookup.
    try {
        $null = Get-Process -Id $PID -ErrorAction Stop
    }
    catch {
        $script:ProcessNameLookupBlocked = $true
    }

    $callback = [EnumWindowsProc]{
        param([IntPtr]$hwnd, [IntPtr]$lParam)

        if (-not [Win32]::IsWindowVisible($hwnd)) { return $true }

        $titleLen = [Win32]::GetWindowTextLength($hwnd)
        if ($titleLen -eq 0) { return $true }

        $title = New-Object System.Text.StringBuilder($titleLen + 1)
        [Win32]::GetWindowText($hwnd, $title, $title.Capacity) | Out-Null

        $class = New-Object System.Text.StringBuilder(256)
        [Win32]::GetClassName($hwnd, $class, 256) | Out-Null

        $processId = 0
        [Win32]::GetWindowThreadProcessId($hwnd, [ref]$processId) | Out-Null

        # Best-effort process name lookup. A "process not found" race (or
        # PID 0 system windows) is normal and must NOT set the blocked flag;
        # any other failure (e.g. access denied under a restricted token)
        # means process name lookup is impaired in this environment.
        $procName = "unknown"
        try {
            $proc = Get-Process -Id $processId -ErrorAction Stop
            if ($proc) { $procName = $proc.ProcessName }
        }
        catch {
            if ($_.FullyQualifiedErrorId -ne 'NoProcessFoundForGivenId,Microsoft.PowerShell.Commands.GetProcessCommand') {
                $script:ProcessNameLookupBlocked = $true
            }
        }

        [void]$windows.Add(@{
            pid = $processId
            processName = $procName
            title = $title.ToString()
            class = $class.ToString()
            hwnd = $hwnd.ToInt64()
        })
        return $true
    }

    [Win32]::EnumWindows($callback, [IntPtr]::Zero) | Out-Null
    return $windows
}

function Find-TargetWindows {
    param(
        [array]$allWindows,
        [string]$ProcessName,
        [int]$ProcessId,
        [string]$WindowTitle,
        [string]$WindowClass,
        [string]$Hwnd
    )

    $filtered = $allWindows

    if ($ProcessId -gt 0) {
        $filtered = $filtered | Where-Object { $_.pid -eq $ProcessId }
    }
    if ($ProcessName) {
        $filtered = $filtered | Where-Object { $_.processName -ieq $ProcessName }
    }
    if ($WindowTitle) {
        # Escape wildcard characters so -WindowTitle is a literal substring
        # match (prevents WildcardPatternException on titles containing "[").
        $escapedTitle = [WildcardPattern]::Escape($WindowTitle)
        $filtered = $filtered | Where-Object { $_.title -like "*$escapedTitle*" }
    }
    if ($WindowClass) {
        $filtered = $filtered | Where-Object { $_.class -ieq $WindowClass }
    }
    if ($Hwnd) {
        $hwndValue = [Convert]::ToInt64($Hwnd, 16)
        $filtered = $filtered | Where-Object { $_.hwnd -eq $hwndValue }
    }

    return ,@($filtered)
}

function Output-Json {
    param([hashtable]$data)
    $data | ConvertTo-Json -Depth 5
}