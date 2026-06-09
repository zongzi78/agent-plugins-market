# Capture-Engine.ps1
# Window screenshot capture engine with 3-tier fallback and uniformity detection.
# Requires: Win32-APIs.ps1 (dot-sourced before this file)

function Test-ImageUniformity {
    <#
    .SYNOPSIS
    Checks if a bitmap is visually uniform (all sampled pixels are the same color).
    .DESCRIPTION
    Samples 9 points (4 corners + 4 edge midpoints + center) from the bitmap.
    Returns $true if all samples are within ±2 per RGB channel of the first sample,
    indicating a likely failed capture (blank canvas).
    #>
    param([IntPtr]$hBitmap, [int]$width, [int]$height)

    $bitmap = [System.Drawing.Bitmap]::FromHbitmap($hBitmap)
    try {
        # Sample coordinates at 10%, 50%, 90% of width/height
        $xs = @([int]($width * 0.1), [int]($width * 0.5), [int]($width * 0.9))
        $ys = @([int]($height * 0.1), [int]($height * 0.5), [int]($height * 0.9))

        $reference = $bitmap.GetPixel($xs[0], $ys[0])
        $tolerance = 2

        foreach ($y in $ys) {
            foreach ($x in $xs) {
                $pixel = $bitmap.GetPixel($x, $y)
                if ([Math]::Abs($pixel.R - $reference.R) -gt $tolerance -or
                    [Math]::Abs($pixel.G - $reference.G) -gt $tolerance -or
                    [Math]::Abs($pixel.B - $reference.B) -gt $tolerance) {
                    return $false  # Variation found — image is valid
                }
            }
        }
        return $true  # All samples identical — likely failed capture
    }
    finally {
        $bitmap.Dispose()
    }
}

function Capture-WindowScreenshot {
    param(
        [hashtable]$window,
        [string]$outputPath
    )

    $hwnd = [IntPtr]::new($window.hwnd)
    $wasMinimized = $false
    $wasTopmost = $false
    $originalFgHwnd = [IntPtr]::Zero

    try {
        # --- Pre-capture: restore minimized window ---
        if ([Win32]::IsIconic($hwnd)) {
            [Win32]::ShowWindow($hwnd, $script:SW_RESTORE) | Out-Null
            $wasMinimized = $true
            Start-Sleep -Milliseconds 300
        }

        # --- Pre-capture: handle UWP apps ---
        $actualHwnd = $hwnd
        if ($window.class -eq "ApplicationFrameWindow") {
            $child = [Win32]::GetWindow($hwnd, $script:GW_CHILD)
            if ($child -ne [IntPtr]::Zero) {
                $actualHwnd = $child
            }
        }

        # --- Pre-capture: get window dimensions ---
        $rect = New-Object RECT
        [Win32]::GetWindowRect($actualHwnd, [ref]$rect) | Out-Null
        $width = $rect.Right - $rect.Left
        $height = $rect.Bottom - $rect.Top

        if ($width -le 0 -or $height -le 0) {
            return @{
                success = $false
                error = "Invalid window size (${width}x${height}), window may not be visible"
            }
        }

        $captured = $false
        $finalMethod = ""

        # ============================================================
        # Tier 1: PrintWindow with PW_RENDERFULLCONTENT
        # ============================================================
        $screenDC = [Win32]::GetDC([IntPtr]::Zero)
        $memDC = [Win32]::CreateCompatibleDC($screenDC)
        $hBitmap = [Win32]::CreateCompatibleBitmap($screenDC, $width, $height)
        $oldBitmap = [Win32]::SelectObject($memDC, $hBitmap)

        $pwResult = [Win32]::PrintWindow($actualHwnd, $memDC, $script:PW_RENDERFULLCONTENT)
        if ($pwResult -and -not (Test-ImageUniformity $hBitmap $width $height)) {
            $captured = $true
            $finalMethod = "PrintWindow"
        }
        else {
            # Cleanup before next tier
            [Win32]::SelectObject($memDC, $oldBitmap) | Out-Null
            [Win32]::DeleteObject($hBitmap) | Out-Null
            [Win32]::DeleteDC($memDC) | Out-Null
            [Win32]::ReleaseDC([IntPtr]::Zero, $screenDC) | Out-Null
        }

        # ============================================================
        # Tier 2: PrintWindow with flags=0 (WM_PRINTCLIENT)
        # ============================================================
        if (-not $captured) {
            $screenDC = [Win32]::GetDC([IntPtr]::Zero)
            $memDC = [Win32]::CreateCompatibleDC($screenDC)
            $hBitmap = [Win32]::CreateCompatibleBitmap($screenDC, $width, $height)
            $oldBitmap = [Win32]::SelectObject($memDC, $hBitmap)

            $pwResult = [Win32]::PrintWindow($actualHwnd, $memDC, 0)
            if ($pwResult -and -not (Test-ImageUniformity $hBitmap $width $height)) {
                $captured = $true
                $finalMethod = "PrintWindow-client"
            }
            else {
                [Win32]::SelectObject($memDC, $oldBitmap) | Out-Null
                [Win32]::DeleteObject($hBitmap) | Out-Null
                [Win32]::DeleteDC($memDC) | Out-Null
                [Win32]::ReleaseDC([IntPtr]::Zero, $screenDC) | Out-Null
            }
        }

        # ============================================================
        # Tier 3: Bring to top + BitBlt screen capture
        # ============================================================
        if (-not $captured) {
            # Save current foreground window for restoration
            $originalFgHwnd = [Win32]::GetForegroundWindow()

            # Bypass Windows foreground restriction: simulate Alt key
            # This releases the lock that prevents background processes from calling SetForegroundWindow
            [Win32]::keybd_event(0x12, 0, 0x01, [UIntPtr]::Zero)  # Alt down (EXTENDEDKEY)
            [Win32]::keybd_event(0x12, 0, 0x01 -bor 0x02, [UIntPtr]::Zero)  # Alt up (EXTENDEDKEY | KEYUP)

            # Bring target to foreground
            [Win32]::SetForegroundWindow($hwnd) | Out-Null
            [Win32]::BringWindowToTop($hwnd) | Out-Null
            Start-Sleep -Milliseconds 200

            # Also set as topmost to prevent other windows from covering it
            [Win32]::SetWindowPos($hwnd, $script:HWND_TOPMOST, 0, 0, 0, 0,
                ($script:SWP_NOMOVE -bor $script:SWP_NOSIZE)) | Out-Null
            $wasTopmost = $true
            Start-Sleep -Milliseconds 500

            # Re-read rect in case position changed
            [Win32]::GetWindowRect($actualHwnd, [ref]$rect) | Out-Null
            $width = $rect.Right - $rect.Left
            $height = $rect.Bottom - $rect.Top

            if ($width -gt 0 -and $height -gt 0) {
                $screenDC = [Win32]::GetDC([IntPtr]::Zero)
                $memDC = [Win32]::CreateCompatibleDC($screenDC)
                $hBitmap = [Win32]::CreateCompatibleBitmap($screenDC, $width, $height)
                $oldBitmap = [Win32]::SelectObject($memDC, $hBitmap)

                # BitBlt: copy screen region where the window is
                $bltResult = [Win32]::BitBlt($memDC, 0, 0, $width, $height,
                    $screenDC, $rect.Left, $rect.Top, $script:SRCCOPY)
                if ($bltResult) {
                    $captured = $true
                    $finalMethod = "BitBlt"
                }
                else {
                    [Win32]::SelectObject($memDC, $oldBitmap) | Out-Null
                    [Win32]::DeleteObject($hBitmap) | Out-Null
                    [Win32]::DeleteDC($memDC) | Out-Null
                    [Win32]::ReleaseDC([IntPtr]::Zero, $screenDC) | Out-Null
                }
            }

            # Restore original foreground window (also restores Z-order)
            if ($originalFgHwnd -ne [IntPtr]::Zero) {
                [Win32]::SetForegroundWindow($originalFgHwnd) | Out-Null
            }
            else {
                [Win32]::SetWindowPos($hwnd, $script:HWND_NOTOPMOST, 0, 0, 0, 0,
                    ($script:SWP_NOMOVE -bor $script:SWP_NOSIZE)) | Out-Null
            }
            $wasTopmost = $false
        }

        # ============================================================
        # Result
        # ============================================================
        if (-not $captured) {
            return @{
                success = $false
                error = "All capture methods failed. The application may not support WM_PRINT and screen capture was not possible."
            }
        }

        # Save as PNG
        $bitmap = [System.Drawing.Bitmap]::FromHbitmap($hBitmap)
        $bitmap.Save($outputPath, [System.Drawing.Imaging.ImageFormat]::Png)
        $bitmap.Dispose()

        # Cleanup GDI resources from the successful capture
        if ($oldBitmap -ne [IntPtr]::Zero -and $memDC -ne [IntPtr]::Zero) {
            [Win32]::SelectObject($memDC, $oldBitmap) | Out-Null
        }
        if ($hBitmap -ne [IntPtr]::Zero) { [Win32]::DeleteObject($hBitmap) | Out-Null }
        if ($memDC -ne [IntPtr]::Zero) { [Win32]::DeleteDC($memDC) | Out-Null }
        if ($screenDC -ne [IntPtr]::Zero) { [Win32]::ReleaseDC([IntPtr]::Zero, $screenDC) | Out-Null }

        return @{
            success = $true
            path = $outputPath
            width = $width
            height = $height
            processName = $window.processName
            pid = $window.pid
            windowTitle = $window.title
            method = $finalMethod
        }
    }
    finally {
        # Safety net: restore foreground window if Tier 3 errored mid-way
        if ($wasTopmost) {
            if ($originalFgHwnd -ne [IntPtr]::Zero) {
                [Win32]::SetForegroundWindow($originalFgHwnd) | Out-Null
            }
            else {
                [Win32]::SetWindowPos($hwnd, $script:HWND_NOTOPMOST, 0, 0, 0, 0,
                    ($script:SWP_NOMOVE -bor $script:SWP_NOSIZE)) | Out-Null
            }
        }
        # Restore minimized state
        if ($wasMinimized) {
            [Win32]::ShowWindow($hwnd, $script:SW_MINIMIZE) | Out-Null
        }
    }
}
