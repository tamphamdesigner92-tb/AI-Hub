<#
    Mở dashboard AI Hub. Tự bật server nếu chưa chạy.

    Logic nằm ở file .ps1 này chứ không nhúng inline trong .cmd: gốc hub là
    "E:\AI Hub" — có dấu cách — và việc trích dẫn lồng nhau qua cmd → powershell
    → Start-Process làm đường dẫn bị tách làm đôi.
#>

[CmdletBinding()]
param(
    [int]$Port = 0,
    [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'

$HUB = if ($env:AIHUB_HOME) { $env:AIHUB_HOME } else { Split-Path -Parent $PSScriptRoot }
if ($Port -le 0) {
    $Port = if ($env:AIHUB_WEB_PORT) { [int]$env:AIHUB_WEB_PORT } else { 7860 }
}
$url = "http://127.0.0.1:$Port"
$log = Join-Path $HUB 'models\run\web.log'

function Test-Up {
    # /api/ping chứ không phải /api/status: status có gọi sang Ollama, mà trên
    # Windows một kết nối tới cổng không ai nghe mất ~2 giây mới thất bại. Thăm
    # dò bằng status sẽ báo "dashboard hỏng" mỗi khi Ollama đơn giản là đang tắt.
    try {
        $null = Invoke-WebRequest -Uri "$url/api/ping" -TimeoutSec 3 -UseBasicParsing
        return $true
    } catch { return $false }
}

if (-not (Test-Up)) {
    Write-Host 'Đang bật dashboard…'

    # pythonw = không cửa sổ console. Không có thì dùng python thường.
    $py = Join-Path $HUB '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path -LiteralPath $py)) {
        $py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    }
    if (-not $py) {
        $py = Join-Path $HUB '.venv\Scripts\python.exe'
    }
    if (-not (Test-Path -LiteralPath $py)) {
        $py = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
    }
    if (-not $py) { throw 'không tìm thấy python' }

    $server = Join-Path $HUB 'web\server.py'
    if (-not (Test-Path -LiteralPath $server)) { throw "không thấy $server" }
    $null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $log)

    # Mỗi đối số tự bọc nháy: Start-Process nối mảng bằng dấu cách và KHÔNG tự
    # thêm nháy, nên đường dẫn có dấu cách sẽ bị tách nếu thiếu bước này.
    Start-Process -FilePath $py -WindowStyle Hidden `
        -ArgumentList @("`"$server`"", "$Port", '--no-open')

    foreach ($i in 1..20) {
        Start-Sleep -Milliseconds 400
        if (Test-Up) { break }
    }
}

if (-not (Test-Up)) {
    Write-Error "Server không lên được. Xem log: $log"
    exit 1
}

Write-Host $url
if (-not $NoOpen) { Start-Process $url }
