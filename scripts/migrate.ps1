<#
    AI Hub — chuyển cache model mặc định vào kho hub, rồi liên kết ngược về chỗ cũ.
    An toàn để chạy lại nhiều lần (idempotent).

    ⚠️  OLLAMA_NOPRUNE=1 là bắt buộc: `ollama serve` prune blob vô chủ khi khởi
        động. Nếu nó chạy giữa lúc manifest đã dời mà blob chưa, toàn bộ kho sẽ
        bị xoá.

    Khác bản macOS ở một điểm quan trọng: ở đó cache và hub cùng volume APFS nên
    `mv` là rename tức thì. Trên Windows cache thường ở C: còn hub ở ổ khác, nên
    đây là COPY THẬT — vài chục GB, mất nhiều phút. Vì vậy script copy xong, đối
    chiếu dung lượng, rồi mới xoá nguồn: đứt điện giữa chừng thì dữ liệu gốc vẫn
    còn nguyên.

    Không cần quyền admin: thư mục được liên kết bằng junction.
#>

[CmdletBinding()]
param(
    # Chỉ in ra sẽ làm gì, không đụng vào đĩa.
    [switch]$DryRun,
    # Ghi biến môi trường ở mức người dùng để app khởi động từ Start Menu cũng thấy.
    [switch]$SetUserEnv,
    # Chỉ chuyển những kho này, ví dụ -Only ollama. Mặc định: tất cả.
    #
    # Chuyển từng phần là hợp lệ — mỗi cặp cache độc lập với nhau. Nhưng khi đó
    # ĐỪNG dùng -SetUserEnv: nó ghi cả HF_HOME, TORCH_HOME… trỏ vào kho hub còn
    # rỗng, và công cụ sẽ tải lại từ đầu thay vì dùng cache cũ vẫn nằm ở chỗ cũ.
    [ValidateSet('ollama', 'hf', 'whisper', 'torch')]
    [string[]]$Only
)

$ErrorActionPreference = 'Stop'

function Info($m) { Write-Host "▸ $m" -ForegroundColor Cyan }
function Ok  ($m) { Write-Host "✓ $m" -ForegroundColor Green }
function Warn($m) { Write-Host "! $m" -ForegroundColor Yellow }
function Die ($m) { Write-Host "✗ $m" -ForegroundColor Red; exit 1 }

$HUB   = Split-Path -Parent $PSScriptRoot
$STORE = Join-Path $HUB 'models'
$statePath = Join-Path $HUB '.migration-state.json'
$env:OLLAMA_NOPRUNE = '1'

Info "Hub:  $HUB"
Info "Kho:  $STORE"
if ($DryRun) { Warn 'DRY-RUN — không ghi gì lên đĩa' }

# ── Kiểm tra: là hub thật chứ không phải thư mục nào khác ────────────────────
if (-not (Test-Path (Join-Path $HUB 'registry.toml'))) {
    Die "Không thấy registry.toml trong $HUB — script nằm sai chỗ?"
}

# ── 1. Ollama phải tắt ───────────────────────────────────────────────────────
Info 'Kiểm tra Ollama đã tắt chưa…'
if (-not $DryRun) {
    Get-Process ollama, 'ollama app' -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}
$listening = Get-NetTCPConnection -LocalPort 11434 -State Listen -ErrorAction SilentlyContinue
if ($listening) {
    if ($DryRun) {
        Warn 'Cổng 11434 đang mở (Ollama chạy) — lần chạy thật sẽ tắt nó trước'
    } else {
        Die 'Cổng 11434 vẫn mở — Ollama còn chạy. Thoát Ollama từ khay hệ thống rồi chạy lại.'
    }
} else {
    Ok 'Ollama đã tắt, cổng 11434 đóng'
}

# ── 2. Bí danh %USERPROFILE%\.aihub ──────────────────────────────────────────
# Client Node và các script dùng đường dẫn cố định này để tìm hub.
$alias = Join-Path $env:USERPROFILE '.aihub'
$aliasItem = Get-Item -LiteralPath $alias -Force -ErrorAction SilentlyContinue
if ($aliasItem -and $aliasItem.LinkType) {
    if ($aliasItem.Target -contains $HUB) { Ok "$alias đã đúng" }
    else { Die "$alias trỏ sai chỗ: $($aliasItem.Target)" }
}
elseif ($aliasItem) {
    Die "$alias tồn tại nhưng không phải liên kết — xử lý thủ công"
}
elseif ($DryRun) { Info "sẽ tạo junction $alias → $HUB" }
else {
    $null = cmd /c mklink /J "$alias" "$HUB"
    if ($LASTEXITCODE -ne 0) { Die "không tạo được junction $alias" }
    Ok "đã tạo $alias"
}

# ── 3. Di chuyển từng cache ──────────────────────────────────────────────────
$pairs = @(
    @{ Legacy = Join-Path $env:USERPROFILE '.ollama\models';     Store = 'ollama'  },
    @{ Legacy = Join-Path $env:USERPROFILE '.cache\huggingface'; Store = 'hf'      },
    @{ Legacy = Join-Path $env:USERPROFILE '.cache\whisper';     Store = 'whisper' },
    @{ Legacy = Join-Path $env:USERPROFILE '.cache\torch';       Store = 'torch'   }
)

function Get-TreeSize($path) {
    $m = Get-ChildItem -LiteralPath $path -Recurse -File -Force -ErrorAction SilentlyContinue |
         Measure-Object -Sum Length
    [pscustomobject]@{ Files = [int]$m.Count; Bytes = [int64]$m.Sum }
}

if ($Only) {
    $pairs = @($pairs | Where-Object { $Only -contains $_.Store })
    Warn "chỉ chuyển: $($Only -join ', ') — các kho khác giữ nguyên tại chỗ cũ"
    if ($SetUserEnv) {
        Die ('-SetUserEnv cùng -Only sẽ trỏ biến của kho chưa chuyển vào thư mục ' +
             'rỗng, khiến công cụ tải lại từ đầu. Chạy -SetUserEnv sau khi đã ' +
             'chuyển hết.')
    }
}

foreach ($pair in $pairs) {
    $src = $pair.Legacy
    $dst = Join-Path $STORE $pair.Store
    $item = Get-Item -LiteralPath $src -Force -ErrorAction SilentlyContinue

    if ($item -and $item.LinkType) {
        if ($item.Target -contains $dst) { Ok "$src → đã trỏ về hub, bỏ qua" }
        else { Die "$src là liên kết nhưng trỏ tới $($item.Target) — xử lý thủ công" }
        continue
    }

    if (-not $item) {
        Warn "$src không tồn tại — chỉ tạo liên kết"
        if (-not $DryRun) {
            $null = New-Item -ItemType Directory -Force -Path $dst
            $null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $src)
            $null = cmd /c mklink /J "$src" "$dst"
        }
        continue
    }

    # Đích do bước dựng khung tạo sẵn và đang rỗng thì xoá đi; có dữ liệu thì dừng.
    if (Test-Path -LiteralPath $dst) {
        if ((Get-ChildItem -LiteralPath $dst -Force | Measure-Object).Count -gt 0) {
            Die "$dst đã có dữ liệu — dừng để tránh ghi đè"
        }
        if (-not $DryRun) { Remove-Item -LiteralPath $dst -Force }
    }

    $before = Get-TreeSize $src
    $gb = [math]::Round($before.Bytes / 1GB, 2)
    $sameVolume = (Split-Path -Qualifier $src) -eq (Split-Path -Qualifier $dst)
    $how = if ($sameVolume) { 'cùng ổ, nhanh' } else { 'KHÁC Ổ — copy thật, sẽ lâu' }
    Info "chuyển $src ($gb GB, $($before.Files) file) → $dst  [$how]"

    if ($DryRun) { continue }

    # Copy trước, xoá sau: đứt giữa chừng thì nguồn vẫn nguyên vẹn.
    $null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dst)
    robocopy $src $dst /E /COPY:DAT /DCOPY:DAT /R:2 /W:2 /NFL /NDL /NJH /NJS /NP | Out-Null
    # robocopy: mã thoát < 8 là thành công (0 = không có gì để chép, 1 = đã chép…)
    if ($LASTEXITCODE -ge 8) { Die "robocopy lỗi (mã $LASTEXITCODE) — nguồn chưa bị đụng tới" }

    $after = Get-TreeSize $dst
    if ($after.Bytes -ne $before.Bytes -or $after.Files -ne $before.Files) {
        Die ("copy không khớp: nguồn $($before.Files) file/$($before.Bytes) B, " +
             "đích $($after.Files) file/$($after.Bytes) B — nguồn vẫn còn, không xoá gì cả")
    }
    Ok "đã copy khớp $($after.Files) file"

    Remove-Item -LiteralPath $src -Recurse -Force
    $null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $src)
    $null = cmd /c mklink /J "$src" "$dst"
    if ($LASTEXITCODE -ne 0) {
        Die "ĐÃ CHUYỂN DỮ LIỆU nhưng không tạo được junction $src → $dst. Tạo tay ngay!"
    }
    Ok "xong: $src → hub"
}

# ── 4. Các thư mục store còn lại ─────────────────────────────────────────────
if (-not $DryRun) {
    foreach ($d in 'ct2', 'custom', 'links', 'run') {
        $null = New-Item -ItemType Directory -Force -Path (Join-Path $STORE $d)
    }
}

# ── 5. Biến môi trường mức người dùng ────────────────────────────────────────
# App khởi động từ Start Menu (Ollama.exe, Electron) không đọc biến đặt tạm trong
# phiên PowerShell — chúng đọc HKCU\Environment. Đây là thay đổi cấu hình lâu dài
# nên chỉ làm khi được yêu cầu rõ ràng bằng -SetUserEnv.
if ($SetUserEnv) {
    $envFile = Join-Path $HUB 'env\aihub.env'
    foreach ($line in Get-Content -LiteralPath $envFile -Encoding UTF8) {
        $t = $line.Trim()
        if (-not $t -or $t.StartsWith('#')) { continue }
        $i = $t.IndexOf('='); if ($i -lt 1) { continue }
        $name  = $t.Substring(0, $i).Trim()
        $value = [Environment]::ExpandEnvironmentVariables($t.Substring($i + 1).Trim())
        if ($DryRun) { Info "sẽ đặt biến người dùng $name=$value"; continue }
        [Environment]::SetEnvironmentVariable($name, $value, 'User')
    }
    if (-not $DryRun) { Ok 'đã ghi biến môi trường mức người dùng (đăng xuất/đăng nhập để app GUI nhận)' }
} else {
    Warn 'chưa ghi biến môi trường mức người dùng — chạy lại với -SetUserEnv nếu muốn'
}

# ── 6. Loại kho khỏi Windows Defender ────────────────────────────────────────
Warn 'Nên loại kho khỏi quét virus (cần PowerShell quyền admin):'
Write-Host "     Add-MpPreference -ExclusionPath `"$STORE`""

# ── 7. Ghi lại trạng thái để rollback ────────────────────────────────────────
if (-not $DryRun) {
    $stateData = [ordered]@{
        migrated_at = (Get-Date).ToString('s')
        hub         = $HUB
        # Chỉ ghi cặp thực sự chuyển lần này; rollback dựa vào đây.
        pairs       = @($pairs | ForEach-Object {
                          [ordered]@{ legacy = $_.Legacy; store = $_.Store } })
    }
    $stateData | ConvertTo-Json -Depth 4 |
        Set-Content -LiteralPath $statePath -Encoding UTF8
    Ok "đã ghi $statePath"
}

Write-Host ''
Ok 'MIGRATE XONG. Bước tiếp theo:'
Write-Host '   1. aihub doctor          # phải xanh hết'
Write-Host '   2. aihub serve           # rồi: ollama list  (phải đủ model như trước)'
Write-Host '   3. chỉ khi 2 bước trên OK mới bỏ OLLAMA_NOPRUNE'
