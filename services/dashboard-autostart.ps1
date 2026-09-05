<#
    Bật/tắt việc chạy dashboard AI Hub cùng lúc đăng nhập Windows.

        .\services\dashboard-autostart.ps1 -Install
        .\services\dashboard-autostart.ps1 -Status
        .\services\dashboard-autostart.ps1 -Uninstall

    Dùng Scheduled Task chứ không phải shortcut trong thư mục Startup, vì task
    chạy ẩn hoàn toàn (không nháy cửa sổ console) và khởi động lại được khi lỗi.

    Không cần quyền admin: task đăng ký ở phạm vi người dùng hiện tại.

    Server rất nhẹ — khoảng 20 MB RAM, không nạp model nào — nên để nó thường trú
    là hợp lý. Khác hẳn Ollama, vốn có thể giữ nhiều GB (xem README.md trong thư
    mục này).
#>

[CmdletBinding(DefaultParameterSetName = 'Status')]
param(
    [Parameter(ParameterSetName = 'Install')]   [switch]$Install,
    [Parameter(ParameterSetName = 'Uninstall')] [switch]$Uninstall,
    [Parameter(ParameterSetName = 'Status')]    [switch]$Status,
    [int]$Port = 7860
)

$ErrorActionPreference = 'Stop'

$TaskName = 'AI Hub Dashboard'
$HUB      = Split-Path -Parent $PSScriptRoot

function Get-Task { Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue }

if ($Uninstall) {
    if (Get-Task) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "✓ đã gỡ task '$TaskName'" -ForegroundColor Green
    } else {
        Write-Host "task '$TaskName' vốn chưa được cài"
    }
    return
}

if ($Install) {
    # pythonw = không cửa sổ console. Ưu tiên venv riêng của hub.
    $py = Join-Path $HUB '.venv\Scripts\pythonw.exe'
    if (-not (Test-Path $py)) {
        $py = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
    }
    if (-not $py) { throw 'không tìm thấy pythonw.exe' }

    $server = Join-Path $HUB 'web\server.py'
    if (-not (Test-Path $server)) { throw "không thấy $server" }

    $action = New-ScheduledTaskAction -Execute $py `
        -Argument "`"$server`" $Port --no-open" -WorkingDirectory $HUB
    $trigger  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries -StartWhenAvailable `
        -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive

    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
        -Settings $settings -Principal $principal -Force `
        -Description "Dashboard AI Hub tren http://127.0.0.1:$Port" | Out-Null

    Write-Host "✓ đã cài '$TaskName' — chạy khi đăng nhập, cổng $Port" -ForegroundColor Green
    Write-Host "  bật ngay bây giờ:  Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host "  log:               $HUB\models\run\web.log"
    return
}

# Mặc định: báo trạng thái.
$t = Get-Task
if (-not $t) {
    Write-Host "task '$TaskName' chưa cài. Cài bằng: .\services\dashboard-autostart.ps1 -Install"
} else {
    $i = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "task '$TaskName': $($t.State)"
    Write-Host "  chạy lần cuối: $($i.LastRunTime)  (mã $($i.LastTaskResult))"
}
