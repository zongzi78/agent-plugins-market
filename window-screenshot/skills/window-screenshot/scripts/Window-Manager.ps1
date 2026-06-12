# Window-Manager.ps1
# Window enumeration, filtering, and JSON output helpers.
# Requires: Win32-APIs.ps1 (dot-sourced before this file)

function Get-WindowList {
    $windows = [System.Collections.ArrayList]::new()

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

        $proc = Get-Process -Id $processId -ErrorAction SilentlyContinue
        $procName = if ($proc) { $proc.ProcessName } else { "unknown" }

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
        $filtered = $filtered | Where-Object { $_.title -like "*$WindowTitle*" }
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
