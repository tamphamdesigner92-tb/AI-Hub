<#
    AI Hub — hoàn tác migrate.ps1. Đưa dữ liệu về đúng cache mặc định ban đầu.

    Cùng nguyên tắc an toàn như migrate: copy về chỗ cũ, đối chiếu, rồi mới xoá
    bản trong kho. Junction bị gỡ bằng rmdir (KHÔNG phải Remove-Item -Recurse) —
    nhầm chỗ này sẽ xoá sạch dữ liệu thật ở đầu bên kia.
#>

[CmdletBinding()]
param([switch]$DryRun)

$ErrorActionPreference = 'Stop'

function Info($m) { Write-Host "▸ $m" -ForegroundColor Cyan }
function Ok  ($m) { Write-Host "✓ $m" -ForegroundColor Green }
function Warn($m) { Write-Host "! $m" -ForegroundColor Yellow }
function Die ($m) { Write-Host "✗ $m" -ForegroundColor Red; exit 1 }

$HUB   = Split-Path -Parent $PSScriptRoot
$STORE = Join-Path $HUB 'models'
$env:OLLAMA_NOPRUNE = '1'

Write-Host 'Sẽ đưa toàn bộ model về ~\.ollama và ~\.cache. Gõ ROLLBACK để xác nhận:' -ForegroundColor Yellow
if (-not $DryRun) {
    $ans = Read-Host
    if ($ans -ne 'ROLLBACK') { Die 'đã huỷ' }
}

if (-not $DryRun) {
    Get-Process ollama, 'ollama app' -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

function Get-TreeSize($path) {
    $m = Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue |
         Measure-Object -Sum Length
    [pscustomobject]@{ Files = [int]$m.Count; Bytes = [int64]$m.Sum }
}

# Junction hiện ra như thư mục; Remove-Item -Recurse sẽ đi xuyên qua nó và xoá
# dữ liệu thật. rmdir chỉ gỡ điểm nối.
function Remove-Junction($path) {
    $null = cmd /c rmdir "$path"
    if ($LASTEXITCODE -ne 0) { Die "không gỡ được liên kết $path" }
}

$pairs = @(
    @{ Legacy = Join-Path $env:USERPROFILE '.ollama\models';     Store = 'ollama'  },
    @{ Legacy = Join-Path $env:USERPROFILE '.cache\huggingface'; Store = 'hf'      },
    @{ Legacy = Join-Path $env:USERPROFILE '.cache\whisper';     Store = 'whisper' },
    @{ Legacy = Join-Path $env:USERPROFILE '.cache\torch';       Store = 'torch'   }
)

foreach ($pair in $pairs) {
    $src = $pair.Legacy
    $dst = Join-Path $STORE $pair.Store
    $item = Get-Item -LiteralPath $src -Force -ErrorAction SilentlyContinue

    if (-not $item -or -not $item.LinkType) {
        Warn "$src không phải liên kết — bỏ qua"
        continue
    }
    if (-not (Test-Path -LiteralPath $dst)) {
        Warn "$dst không có dữ liệu — chỉ gỡ liên kết"
        if (-not $DryRun) { Remove-Junction $src }
        continue
    }

    $before = Get-TreeSize $dst
    Info "trả $dst ($([math]::Round($before.Bytes / 1GB, 2)) GB) → $src"
    if ($DryRun) { continue }

    Remove-Junction $src
    robocopy $dst $src /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        Die "robocopy lỗi (mã $LASTEXITCODE) — dữ liệu vẫn còn ở $dst"
    }
    $after = Get-TreeSize $src
    if ($after.Bytes -ne $before.Bytes -or $after.Files -ne $before.Files) {
        Die "copy không khớp — giữ nguyên $dst, không xoá gì cả"
    }
    Remove-Item -LiteralPath $dst -Recurse -Force
    Ok "trả về $src"
}

$alias = Join-Path $env:USERPROFILE '.aihub'
$aliasItem = Get-Item -LiteralPath $alias -Force -ErrorAction SilentlyContinue
if ($aliasItem -and $aliasItem.LinkType) {
    if (-not $DryRun) { Remove-Junction $alias }
    Ok "gỡ $alias"
}

# Gỡ biến môi trường mức người dùng do migrate -SetUserEnv ghi vào.
if (-not $DryRun) {
    $envFile = Join-Path $HUB 'env\aihub.env'
    if (Test-Path $envFile) {
        foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
            $t = $line.Trim()
            if (-not $t -or $t.StartsWith('#')) { continue }
            $i = $t.IndexOf('='); if ($i -lt 1) { continue }
            $name = $t.Substring(0, $i).Trim()
            if ([Environment]::GetEnvironmentVariable($name, 'User')) {
                [Environment]::SetEnvironmentVariable($name, $null, 'User')
            }
        }
        Ok 'đã gỡ biến môi trường mức người dùng'
    }
}

Warn "Còn 1 việc cần quyền admin:  Remove-MpPreference -ExclusionPath `"$STORE`""
Ok 'ROLLBACK XONG. Mở terminal mới rồi chạy: ollama list'
