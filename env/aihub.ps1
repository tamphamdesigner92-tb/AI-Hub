# AI Hub — nạp biến môi trường vào phiên PowerShell.
#
#   . "E:\AI Hub\env\aihub.ps1"
#
# Cho vào profile để mọi terminal mới đều có:
#   notepad $PROFILE
#   . "E:\AI Hub\env\aihub.ps1"
#
# Script đọc lại aihub.env chứ không chép giá trị vào đây — một nguồn sự thật,
# sửa một chỗ là mọi shell nhận cùng lúc.

$ErrorActionPreference = 'Stop'

$hub     = Split-Path -Parent $PSScriptRoot
$envFile = Join-Path $PSScriptRoot 'aihub.env'

if (-not (Test-Path $envFile)) {
    Write-Warning "AI Hub: khong thay $envFile"
    return
}

foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
    $t = $line.Trim()
    if (-not $t -or $t.StartsWith('#')) { continue }
    $i = $t.IndexOf('=')
    if ($i -lt 1) { continue }
    $name  = $t.Substring(0, $i).Trim()
    $value = $t.Substring($i + 1).Trim()
    # Đường dẫn có thể ghi %USERPROFILE% để chép được sang máy khác.
    $value = [Environment]::ExpandEnvironmentVariables($value)
    Set-Item -Path "Env:$name" -Value $value
}

# AIHUB_HOME lấy theo vị trí thật của script — đây là giá trị chắc chắn đúng.
# Nếu nó lệch với aihub.env thì các đường dẫn kho trong file cũng đang sai theo,
# nên báo ngay thay vì để hub đọc kho ở chỗ không còn tồn tại.
if ($env:AIHUB_HOME -and $env:AIHUB_HOME -ne $hub) {
    Write-Warning "AI Hub: aihub.env khai AIHUB_HOME=$($env:AIHUB_HOME) nhung hub that su o $hub."
    Write-Warning "        Sua lai duong dan trong env\aihub.env va registry.toml."
}
$env:AIHUB_HOME = $hub

$binDir = Join-Path $hub 'bin'
if (($env:PATH -split ';') -notcontains $binDir) {
    $env:PATH = "$binDir;$env:PATH"
}
