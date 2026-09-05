# AI Hub

Kho model AI local dùng chung cho mọi dự án trên máy này. Bản Windows.

> ⚠️ **`models/` chứa DỮ LIỆU THẬT, không phải cache.**
> Sau khi chạy `aihub migrate`, `%USERPROFILE%\.ollama\models` và
> `%USERPROFILE%\.cache\huggingface` chỉ còn là liên kết trỏ vào đây.
> Xoá `models\` = mất toàn bộ model.
> Ngược lại, xoá `%USERPROFILE%\.cache` bằng lệnh đi xuyên liên kết cũng sẽ xoá
> kho thật — cẩn thận.

## Dùng nhanh

```powershell
.\bin\aihubdashboard.cmd    # mở dashboard (tự bật server nếu chưa chạy)
aihub list                  # xem có model gì
aihub doctor                # kiểm tra sức khoẻ
aihub serve                 # bật Ollama với cấu hình của hub
```

Để gõ `aihub` ở bất kỳ đâu, nạp biến môi trường một lần cho mỗi terminal:

```powershell
. "E:\AI Hub\env\aihub.ps1"
```

Muốn tự động ở mọi terminal thì thêm đúng dòng đó vào `$PROFILE`
(`notepad $PROFILE`).

## Cài lần đầu

```powershell
# 1. venv riêng của hub — để `aihub pull` không phụ thuộc venv dự án
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install huggingface_hub

# 2. xem migrate sẽ làm gì (không đụng vào đĩa)
.\scripts\migrate.ps1 -DryRun

# 3. làm thật — thoát Ollama từ khay hệ thống trước
.\scripts\migrate.ps1 -SetUserEnv

# 4. kiểm tra
aihub doctor
```

> **`migrate` trên Windows là copy thật, không phải rename.** Trên máy Mac gốc,
> cache và hub nằm cùng một volume APFS nên `mv` xong tức thì. Ở đây cache thường
> ở `C:` còn hub ở ổ khác, nên vài chục GB phải chép qua thật — mất nhiều phút.
> Script chép xong, đối chiếu số file và tổng byte, **rồi mới** xoá nguồn: đứt
> điện giữa chừng thì dữ liệu gốc vẫn nguyên vẹn.

`-SetUserEnv` ghi biến môi trường ở mức người dùng (`HKCU\Environment`). Cần bước
này để app khởi động từ Start Menu — Ollama, Electron — tìm đúng kho; chúng không
đọc biến bạn đặt tạm trong một phiên PowerShell. Đăng xuất/đăng nhập lại để chúng
nhận.

## Mở dashboard

| Cách | Làm gì |
|---|---|
| Chạy `.\bin\aihubdashboard.cmd` | Tự bật server nếu đang tắt rồi mở trình duyệt |
| Vào thẳng `http://127.0.0.1:7860` | Cần server đang chạy |
| `aihub web` | Chạy server ở tiền cảnh, Ctrl-C để dừng |

Để dashboard luôn sẵn sàng, đăng ký nó chạy lúc đăng nhập:

```powershell
.\services\dashboard-autostart.ps1 -Install
```

Server rất nhẹ (~20 MB RAM, không nạp model nào) — khác hẳn Ollama vốn có thể giữ
nhiều GB, nên chạy nền là hợp lý. Xem [services/README.md](services/README.md) để
biết vì sao Ollama thì **không** nên thêm autostart.

## Dữ liệu dashboard có chính xác không?

Có. Mỗi lần gọi API (và trang tự gọi lại **mỗi 15 giây**):

| Số liệu | Nguồn |
|---|---|
| Trạng thái có sẵn / chưa tải | Kiểm tra file thật trên đĩa |
| Dung lượng đĩa của từng model | **Đo thật** — cộng byte trong thư mục / blob theo manifest |
| Dung lượng kho, đĩa trống | `os.walk` và `shutil.disk_usage` gọi lúc đó |
| RAM tổng và RAM rảnh | `GlobalMemoryStatusEx` của Win32 |
| Ollama bật/tắt, model đang nạp RAM | Hỏi `/api/tags` và `/api/ps` của Ollama |
| Tên, thẻ, mô tả, dự án dùng | Đọc lại `registry.toml` mỗi lần |

**Một ngoại lệ:** cột **RAM cần** là con số ước tính người viết điền vào
`registry.toml`, không đo được trước khi chạy. Muốn biết số thật thì nạp model rồi
xem `aihub ps`.

Model **chưa tải** hiện dung lượng khai báo kèm nhãn *(ước tính)* vì chưa có gì
trên đĩa để đo.

## Dùng từ dự án khác

Trong Python:
```python
import aihub
p        = aihub.path("whisper-large-v3-ct2")   # đường dẫn file, không tải
url, mdl = aihub.endpoint("qwen3-5")            # endpoint chuẩn OpenAI
```

Trong Node:
```js
const aihub = require(require('os').homedir() + '/.aihub/clients/node');
const p = aihub.path('whisper-large-v3-ct2');
```

Từ shell / ngôn ngữ khác:
```powershell
$model = aihub path whisper-large-v3-ct2
```

## Cách hoạt động

**Liên kết thư mục là nền, biến môi trường là hợp đồng.**

Dữ liệu nằm thật trong `models\`. Các đường dẫn cache mặc định được liên kết trỏ về
đây, nên mọi công cụ tìm model ở chỗ cũ vẫn thấy đúng file — kể cả app khởi động từ
GUI vốn **không** đọc biến môi trường của phiên PowerShell.

Windows có hai kiểu liên kết thư mục và hub dùng cả hai:

| Kiểu | Cần quyền gì | Dùng khi |
|---|---|---|
| Symlink | Developer Mode hoặc admin | Có quyền — đi được xuyên ổ và qua mạng |
| Junction | Không cần gì | Không có quyền symlink; chỉ cho thư mục trên ổ cục bộ |

`aihub link` thử symlink trước, tự tụt xuống junction khi bị từ chối, và với file
đơn lẻ thì dùng hardlink. Cả ba đều trong suốt với công cụ đọc model. `aihub doctor`
báo máy này đang ở trường hợp nào.

Biến môi trường trong `env\aihub.env` làm ý đồ tường minh và cho phép dời kho về
sau, nhưng hệ thống chạy được mà không cần chúng.

## Cấu trúc

| Thư mục | Nội dung |
|---|---|
| `registry.toml` | Nguồn sự thật duy nhất — mọi model, thẻ mô tả, RAM cần |
| `models/` | Toàn bộ trọng số |
| `bin/` | `aihub.cmd`, `aihubdashboard.cmd` (bản `.sh` cho Git Bash/WSL/macOS) |
| `web/` | Dashboard (stdlib Python, 0 dependency, chạy offline) |
| `clients/python`, `clients/node` | Thư viện cho dự án |
| `env/aihub.env` | Biến môi trường — nguồn duy nhất |
| `env/aihub.ps1`, `env/aihub.sh` | Nạp biến đó vào shell tương ứng |
| `scripts/` | `migrate.ps1`, `rollback.ps1` (bản `.sh` cho macOS) |
| `services/` | Đăng ký dashboard chạy lúc đăng nhập |
| `.venv/` | venv riêng của hub — để `aihub pull` không phụ thuộc venv dự án |

## Model không chạy được trên Windows

`registry.toml` có trường `platforms`. Model MLX (`whisper-turbo-mlx`,
`whisper-large-v3-mlx`) khai `platforms = ["macos"]` vì MLX chỉ có trên Apple
Silicon. Chúng hiện trạng thái **⊘ khác nền tảng** và không có nút tải — tải về
cũng không chạy được. Đường ASR mặc định ở đây là `whisper-large-v3-ct2`
(CTranslate2, chạy CPU với int8 hoặc CUDA nếu có GPU NVIDIA).

## Quy tắc bảo mật

`registry.toml` và `env\aihub.env` **không bao giờ** chứa API key / token.
`aihub doctor` tự lint điều này. Token HuggingFace (nếu cần model gated) do
`huggingface_hub` quản lý trong `models\hf\token`.

## Hoàn tác

```powershell
.\scripts\rollback.ps1
```

Đưa toàn bộ dữ liệu về `%USERPROFILE%\.ollama` và `%USERPROFILE%\.cache` như trước,
gỡ biến môi trường mức người dùng. Cũng chép thật rồi mới xoá, như migrate.

Xem thêm: [docs/USAGE.md](docs/USAGE.md) · [docs/DOWNLOAD.md](docs/DOWNLOAD.md)
