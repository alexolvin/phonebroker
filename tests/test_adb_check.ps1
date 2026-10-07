# test_adb_check.ps1 — Validates the ADB device check logic from phone.ps1.
# Run: pwsh -NoProfile -File tests/test_adb_check.ps1
# Exits 0 if all pass, 1 otherwise.

$Serial = "TESTSERIAL"
$Tab = [char]9

function Test-AdbCheck([string[]]$lines) {
    $adbOutput = $lines -join "`n"
    return ($adbOutput -match "(?m)^$Serial\s+device$")
}

$fail = 0

# Test 1: device present
$out1 = @("List of devices attached", "$Serial${Tab}device", "")
if (Test-AdbCheck $out1) {
    Write-Host "[PASS] device present"
} else {
    Write-Host "[FAIL] device present (expected match, got no match)"
    $fail++
}

# Test 2: unauthorized
$out2 = @("List of devices attached", "$Serial${Tab}unauthorized", "")
if (-not (Test-AdbCheck $out2)) {
    Write-Host "[PASS] unauthorized (expected no match)"
} else {
    Write-Host "[FAIL] unauthorized (expected no match, got match)"
    $fail++
}

# Test 3: empty list
$out3 = @("List of devices attached", "")
if (-not (Test-AdbCheck $out3)) {
    Write-Host "[PASS] empty list (expected no match)"
} else {
    Write-Host "[FAIL] empty list (expected no match, got match)"
    $fail++
}

# Test 4: different serial
$out4 = @("List of devices attached", "99999999${Tab}device", "")
if (-not (Test-AdbCheck $out4)) {
    Write-Host "[PASS] different serial (expected no match)"
} else {
    Write-Host "[FAIL] different serial (expected no match, got match)"
    $fail++
}

if ($fail -gt 0) {
    Write-Host "`n$fail test(s) FAILED"
    exit 1
}
Write-Host "`nAll ADB check tests passed."
exit 0
