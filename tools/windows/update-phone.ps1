# update-phone.ps1 — Run once in PowerShell to update phone access.
# Updates SSH config, rewrites phone.ps1, then runs T11 verification.
#
# Usage: .\update-phone.ps1 -Serial <adb-serial> [-ToolsRoot C:\Tools]

param(
    [string]$Serial,
    [string]$ToolsRoot = "C:\Tools"
)

if ($PSVersionTable.PSVersion.Major -lt 5) {
    Write-Error "PowerShell 5.1+ required (current: $($PSVersionTable.PSVersion))"
    exit 1
}

if (-not $Serial) {
    Write-Error "Specify -Serial <adb-serial> (see 'adb devices' on the host)"
    exit 1
}

$ErrorActionPreference = "Stop"

function Show-Error([string]$msg) {
    Add-Type -AssemblyName System.Windows.Forms
    [System.Windows.Forms.MessageBox]::Show($msg, "Phone Setup Error", "OK", "Error") | Out-Null
    exit 1
}

try {
    Write-Host "=== PhoneBroker: update-phone ===" -ForegroundColor Cyan

    # 1. Update SSH config
    $sshConfig = Join-Path $env:USERPROFILE ".ssh\config"
    if (-not (Test-Path $sshConfig)) {
        Show-Error "SSH config not found: $sshConfig"
    }

    $content = Get-Content $sshConfig -Raw
    # In the "Host phone" block: ensure User phonebroker and Port 2222
    $lines = $content -split "`n"
    $inPhoneBlock = $false
    $modified = $false
    $hasPort2222 = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*Host\s+phone\s*$") {
            $inPhoneBlock = $true
        }
        elseif ($inPhoneBlock -and $lines[$i] -match "^\s*Host\s") {
            $inPhoneBlock = $false
        }
        elseif ($inPhoneBlock) {
            if ($lines[$i] -match "^\s*User\s+user\s*$") {
                $lines[$i] = $lines[$i] -replace "User\s+user", "User phonebroker"
                $modified = $true
            }
            if ($lines[$i] -match "^\s*Port\s+22\s*$") {
                $lines[$i] = $lines[$i] -replace "Port\s+22", "Port 2222"
                $modified = $true
            }
            if ($lines[$i] -match "^\s*Port\s+2222\s*$") {
                $hasPort2222 = $true
            }
        }
    }
    # Add Port 2222 if not present in phone block
    if ($inPhoneBlock -or $modified) {
        if (-not $hasPort2222) {
            # Insert Port 2222 after the Host phone line
            for ($i = 0; $i -lt $lines.Count; $i++) {
                if ($lines[$i] -match "^\s*Host\s+phone\s*$") {
                    $newLines = @()
                    for ($j = 0; $j -lt $lines.Count; $j++) {
                        $newLines += $lines[$j]
                        if ($j -eq $i) { $newLines += "    Port 2222" }
                    }
                    $lines = $newLines
                    break
                }
            }
            $modified = $true
        }
    }
    if ($modified) {
        ($lines -join "`n") | Set-Content $sshConfig -NoNewline
        Write-Host "[OK] SSH config updated: User phonebroker, Port 2222" -ForegroundColor Green
    } else {
        Write-Host "[OK] SSH config already correct" -ForegroundColor Green
    }

    # TCP check: verify port 2222 is reachable (host from SSH config phone block)
    $checkHost = $null
    $inPhoneBlock = $false
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^\s*Host\s+phone\s*$") {
            $inPhoneBlock = $true
        }
        elseif ($inPhoneBlock -and $lines[$i] -match "^\s*Host\s") {
            break
        }
        elseif ($inPhoneBlock -and $lines[$i] -match "^\s*Hostname\s+(\S+)") {
            $checkHost = $Matches[1]
            break
        }
    }
    if (-not $checkHost) { $checkHost = "phone" }
    Write-Host "Checking TCP ${checkHost}:2222..."
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect($checkHost, 2222)
        $tcp.Close()
        Write-Host "[OK] TCP ${checkHost}:2222 reachable" -ForegroundColor Green
    } catch {
        Show-Error "Cannot reach ${checkHost}:2222. Check Tailscale connection and that phonebroker-sshd is running.`n$($_.Exception.Message)"
    }

    # 2. Rewrite phone.ps1
    $phoneDir = Join-Path $ToolsRoot "phone"
    $phoneScript = Join-Path $phoneDir "phone.ps1"
    if (-not (Test-Path $phoneDir)) {
        New-Item -ItemType Directory -Path $phoneDir -Force | Out-Null
    }

    $scriptContent = @'
# phone.ps1 — Open phone screen via maintenance + scrcpy
$ErrorActionPreference = "Stop"
$Serial = "__PHONEBROKER_SERIAL__"
$AdbExe = "__TOOLS_ROOT__\scrcpy\adb.exe"
$ScrcpyExe = "__TOOLS_ROOT__\scrcpy\scrcpy.exe"
Add-Type -AssemblyName System.Windows.Forms

function Show-PhoneError([string]$title, [string]$msg) {
    [System.Windows.Forms.MessageBox]::Show($msg, $title, "OK", "Error") | Out-Null
    exit 1
}

# ─── Single instance: named mutex ──────────────────────────────────────────
$mutex = New-Object System.Threading.Mutex($false, "Global\phonebroker-phone-ps1")
if (-not $mutex.WaitOne(0)) {
    Show-PhoneError "Phone" "Сессия с телефоном уже открыта."
}

# ─── Kill orphaned processes from previous runs ───────────────────────────
Get-Process scrcpy -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process -Name "adb" -ErrorAction SilentlyContinue |
    Where-Object { $_.Path -like "__TOOLS_ROOT__\scrcpy\*" } | Stop-Process -Force
Start-Sleep -Milliseconds 500

# ─── SSH: maintenance + ADB tunnel ────────────────────────────────────────
$ssh = New-Object System.Diagnostics.Process
$ssh.StartInfo.FileName = "ssh"
$ssh.StartInfo.Arguments = "-T -L 5038:127.0.0.1:5037 phone"
$ssh.StartInfo.UseShellExecute = $false
$ssh.StartInfo.RedirectStandardInput = $true
$ssh.StartInfo.RedirectStandardOutput = $true
$ssh.StartInfo.RedirectStandardError = $true
$ssh.StartInfo.WindowStyle = "Hidden"
[void]$ssh.Start()

$stderrBuf = New-Object System.Collections.Generic.List[string]
$null = Register-ObjectEvent -InputObject $ssh -EventName ErrorDataReceived -Action {
    if ($EventArgs.Data) { $Script:stderrBuf.Add($EventArgs.Data) }
} -SourceIdentifier "sshErr"
$ssh.BeginErrorReadLine()

# ─── Wait for MAINTENANCE_ACTIVE (up to 90s) ──────────────────────────────
$active = $false
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    if ($ssh.HasExited) { break }
    if ($ssh.StandardOutput.Peek() -ge 0) {
        $line = $ssh.StandardOutput.ReadLine()
        if ($line -match "MAINTENANCE_ACTIVE") { $active = $true; break }
    } else {
        Start-Sleep -Milliseconds 200
    }
}

if (-not $active) {
    $reason = "Timeout waiting for MAINTENANCE_ACTIVE"
    if ($ssh.HasExited) {
        $reason = "SSH exited before MAINTENANCE_ACTIVE (code $($ssh.ExitCode))"
    }
    $last5 = ($stderrBuf | Select-Object -Last 10) -join "`n"
    if (-not $last5) { $last5 = "(no stderr output)" }
    $ssh.Kill() | Out-Null
    $mutex.ReleaseMutex()
    Show-PhoneError "Phone Error" "$reason`n`nLast stderr:`n$last5"
}

# ─── ADB via tunnel ───────────────────────────────────────────────────────
$env:ADB_SERVER_SOCKET = "tcp:localhost:5038"

# Pre-check: device visible through tunnel
$adbOutput = (& $AdbExe devices 2>&1) -join "`n"
if ($adbOutput -notmatch "(?m)^$Serial\s+device$") {
    $ssh.StandardInput.Close()
    $mutex.ReleaseMutex()
    Show-PhoneError "ADB Error" "Device $Serial not found via tunnel.`n`nadb devices output:`n$adbOutput"
}

# Clean ADB forwards before scrcpy
& $AdbExe forward --remove-all 2>&1 | Out-Null

# ─── Launch scrcpy (redirected output, no console pause) ──────────────────
$scrcpy = New-Object System.Diagnostics.Process
$scrcpy.StartInfo.FileName = $ScrcpyExe
$scrcpy.StartInfo.Arguments = "--max-size=1080 --force-adb-forward --port=27183"
$scrcpy.StartInfo.UseShellExecute = $false
$scrcpy.StartInfo.RedirectStandardError = $true
$scrcpy.StartInfo.RedirectStandardOutput = $true
$scrcpyStartBuf = New-Object System.Collections.Generic.List[string]
$null = Register-ObjectEvent -InputObject $scrcpy -EventName ErrorDataReceived -Action {
    if ($EventArgs.Data) { $Script:scrcpyStartBuf.Add($EventArgs.Data) }
} -SourceIdentifier "scrcpyErr"
[void]$scrcpy.Start()
$scrcpy.BeginErrorReadLine()

# Give scrcpy a moment to start (video window appears)
Start-Sleep -Seconds 3
if ($scrcpy.HasExited) {
    $errOut = ($scrcpyStartBuf -join "`n")
    if (-not $errOut) { $errOut = "(no output)" }
    $ssh.StandardInput.Close()
    $mutex.ReleaseMutex()
    Show-PhoneError "scrcpy Error" "scrcpy exited immediately (code $($scrcpy.ExitCode)).`n`n$errOut"
}

# ─── Wait for scrcpy to close (normal exit path) ──────────────────────────
$scrcpy.WaitForExit()
if ($scrcpy.ExitCode -ne 0) {
    $errOut = ($scrcpyStartBuf -join "`n")
    if (-not $errOut) { $errOut = "(no output)" }
    $ssh.StandardInput.Close()
    $mutex.ReleaseMutex()
    Show-PhoneError "scrcpy Error" "scrcpy exited with code $($scrcpy.ExitCode).`n`n$errOut"
}

# ─── Cleanup: close ssh, read sync result ─────────────────────────────────
$ssh.StandardInput.Close()

# Read remaining stdout (sync result), up to 10s
$syncLines = @()
$syncDeadline = (Get-Date).AddSeconds(10)
while ((Get-Date) -lt $syncDeadline) {
    if ($ssh.HasExited) {
        while ($ssh.StandardOutput.Peek() -ge 0) {
            $line = $ssh.StandardOutput.ReadLine()
            if ($line -match "^SYNC") { $syncLines += $line }
        }
        break
    }
    if ($ssh.StandardOutput.Peek() -ge 0) {
        $line = $ssh.StandardOutput.ReadLine()
        if ($line -match "^SYNC") { $syncLines += $line }
    } else {
        Start-Sleep -Milliseconds 100
    }
}

# Wait for ssh to fully exit
if (-not $ssh.HasExited) {
    $ssh.WaitForExit(3000) | Out-Null
    if (-not $ssh.HasExited) {
        $ssh.Kill() | Out-Null
        $ssh.WaitForExit()
    }
}

# Show sync window if changes
$bound = @($syncLines | Where-Object { $_ -match "^SYNC_BOUND: (.+)" } | ForEach-Object { $_ -replace "^SYNC_BOUND: ", "" })
$unavail = @($syncLines | Where-Object { $_ -match "^SYNC_UNAVAILABLE: (.+)" } | ForEach-Object { $_ -replace "^SYNC_UNAVAILABLE: ", "" })
$unassigned = @($syncLines | Where-Object { $_ -match "^SYNC_UNASSIGNED: (.+)" } | ForEach-Object { $_ -replace "^SYNC_UNASSIGNED: ", "" })

$changes = @()
if ($bound.Count -gt 0) { $changes += "Привязано: " + ($bound -join ", ") }
if ($unavail.Count -gt 0) { $changes += "Недоступно: " + ($unavail -join ", ") }
if ($unassigned.Count -gt 0) { $changes += "Новые без площадки: " + ($unassigned -join ", ") }

if ($changes.Count -gt 0) {
    [System.Windows.Forms.MessageBox]::Show(($changes -join "`n"), "PhoneBroker — синхронизация")
}

Unregister-Event -SourceIdentifier "sshErr" -ErrorAction SilentlyContinue
Unregister-Event -SourceIdentifier "scrcpyErr" -ErrorAction SilentlyContinue
$mutex.ReleaseMutex()
'@
$scriptContent = $scriptContent.Replace("__PHONEBROKER_SERIAL__", $Serial)
$scriptContent = $scriptContent.Replace("__TOOLS_ROOT__", $ToolsRoot)

    $utf8Bom = New-Object System.Text.UTF8Encoding $true
    [System.IO.File]::WriteAllText($phoneScript, $scriptContent, $utf8Bom)
    Write-Host "[OK] phone.ps1 updated" -ForegroundColor Green

    # 3. Run T11 verification
    Write-Host ""
    Write-Host "=== T11: SSH forced command verification ===" -ForegroundColor Cyan
    Write-Host "Running: ssh -T phone (empty stdin, forced command should output MAINTENANCE_ACTIVE)" -ForegroundColor Yellow

    $t11Result = $null | & ssh -T -o ConnectTimeout=10 -o BatchMode=yes phone 2>&1
    $t11Output = $t11Result -join "`n"

    Write-Host "--- Output ---"
    Write-Host $t11Output
    Write-Host "--- End ---"

    # Success: MAINTENANCE_ACTIVE present, uid= absent
    # Failure: anything else
    if ($t11Output -match "MAINTENANCE_ACTIVE" -and $t11Output -notmatch "uid=") {
        Write-Host "[PASS] T11: forced command works (MAINTENANCE_ACTIVE, no uid=)" -ForegroundColor Green
    } else {
        $errDetail = "T11 FAILED. Expected: MAINTENANCE_ACTIVE (no uid=)."
        if ($t11Output -match "locked") {
            $errDetail += "`nCause: account is locked. Fix: sudo usermod -p '*' phonebroker"
        }
        $errDetail += "`n`nActual output:`n$t11Output"
        Show-Error "T11 Failed" $errDetail
    }

    # Ensure maintenance is ended (the ssh session above may have started it)
    Start-Sleep -Seconds 2

    Write-Host ""
    Write-Host "=== Done ===" -ForegroundColor Cyan
    Write-Host "Now double-click the 'Телефон' shortcut (T10)." -ForegroundColor Yellow

} catch {
    Show-Error $_.Exception.Message
}
