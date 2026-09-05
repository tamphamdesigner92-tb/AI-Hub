# AI Hub

Kho model AI local dùng chung cho mọi dự án trên máy này.

> ⚠️ **`models/` chứa DỮ LIỆU THẬT (~78 GB), không phải cache.**
> `~/.ollama/models`, `~/.cache/huggingface`, `~/.cache/whisper`, `~/.cache/torch`
> giờ chỉ là symlink trỏ vào đây. Xoá `models/` = mất toàn bộ model.
> Ngược lại, `rm -rf ~/.cache` cũng sẽ xoá kho thật qua symlink — cẩn thận.

## Dùng nhanh

```bash
aihubdashboard              # mở dashboard (tự bật server nếu chưa chạy)
aihub list                  # xem có model gì
aihub doctor                # kiểm tra sức khoẻ
aihub serve                 # bật Ollama với cấu hình hợp RAM 16 GB
```

## Mở dashboard

Ba cách, chọn cái tiện nhất:

| Cách | Làm gì |
|---|---|
| Gõ `aihubdashboard` trong terminal | Tự bật server nếu đang tắt rồi mở trình duyệt |
| Bấm đúp **AI Hub Dashboard** trên Desktop | Cần server đang chạy |
| Gõ `aihubdashboard:7860` vào trình duyệt | Cần thêm 1 dòng vào `/etc/hosts` (xem dưới) |

**Để gõ thẳng tên vào trình duyệt** — thêm bí danh và cho dashboard tự chạy nền:

```bash
echo "127.0.0.1  aihubdashboard" | sudo tee -a /etc/hosts
cp ~/.aihub/services/com.aihub.dashboard.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.aihub.dashboard.plist
```

Sau đó `http://aihubdashboard:7860` luôn vào được. Server rất nhẹ (~20 MB RAM, không
nạp model nào) — khác hẳn Ollama vốn có thể giữ tới 10 GB, nên chạy nền là hợp lý.

## Dữ liệu dashboard có chính xác không?

Có. Mỗi lần gọi API (và trang tự gọi lại **mỗi 15 giây**):

| Số liệu | Nguồn |
|---|---|
| Trạng thái có sẵn / chưa tải | Kiểm tra file thật trên đĩa |
| Dung lượng đĩa của từng model | **Đo thật** — cộng byte trong thư mục / blob theo manifest |
| Dung lượng kho, đĩa trống, RAM rảnh | `du`, `statvfs`, `vm_stat` gọi lúc đó |
| Ollama bật/tắt, model đang nạp RAM | Hỏi `/api/tags` và `/api/ps` của Ollama |
| Tên, thẻ, mô tả, dự án dùng | Đọc lại `registry.toml` mỗi lần |

**Một ngoại lệ:** cột **RAM cần** là con số ước tính người viết điền vào `registry.toml`,
không đo được trước khi chạy. Muốn biết số thật thì nạp model rồi xem `aihub ps` — hoặc
nhìn dòng "đang nạp" trên thanh trên cùng của dashboard.

Model **chưa tải** hiện dung lượng khai báo kèm nhãn *(ước tính)* vì chưa có gì trên đĩa để đo.

Trong Python (bất kỳ dự án nào):
```python
import aihub
p        = aihub.path("whisper-turbo-mlx")   # đường dẫn file, không tải
url, mdl = aihub.endpoint("qwen3-5")         # endpoint chuẩn OpenAI
```

Trong Node:
```js
const aihub = require(require('os').homedir() + '/.aihub/clients/node');
const p = aihub.path('whisper-turbo-mlx');
```

Từ shell / ngôn ngữ khác:
```bash
MODEL=$(aihub path whisper-turbo-mlx)
```

## Cách hoạt động

**Symlink là nền, biến môi trường là hợp đồng.**

Dữ liệu nằm thật trong `models/`. Bốn đường dẫn cache mặc định được symlink trỏ về
đây, nên mọi công cụ tìm model ở chỗ cũ vẫn thấy đúng file — kể cả app khởi động từ
GUI (Ollama.app, Electron) vốn **không** đọc `~/.zprofile`.

Biến môi trường trong `env/aihub.sh` làm ý đồ tường minh và cho phép dời kho về sau,
nhưng hệ thống chạy được mà không cần chúng.

## Cấu trúc

| Thư mục | Nội dung |
|---|---|
| `registry.toml` | Nguồn sự thật duy nhất — mọi model, thẻ mô tả, RAM cần |
| `models/` | Toàn bộ trọng số. Đã loại khỏi Time Machine |
| `bin/aihub` | CLI, đã symlink vào `~/.local/bin` |
| `web/` | Dashboard (stdlib Python, 0 dependency, chạy offline) |
| `clients/python`, `clients/node` | Thư viện cho dự án |
| `env/aihub.sh` | Biến môi trường dùng chung |
| `scripts/` | `migrate.sh`, `rollback.sh` |
| `.venv/` | venv riêng của hub — để `aihub pull` không phụ thuộc venv dự án |

## Quy tắc bảo mật

`registry.toml` và `env/aihub.env` **không bao giờ** chứa API key / token.
`aihub doctor` tự lint điều này. Token HuggingFace (nếu cần model gated) nằm ở
`models/hf/token`, chmod 0600.

## Hoàn tác

```bash
aihub rollback
```
Đưa toàn bộ dữ liệu về `~/.ollama` và `~/.cache` như trước. Các sửa đổi trong code dự
án đều dạng `os.environ.get(...) or <giá trị gốc>` nên không cần revert.

Xem thêm: [docs/USAGE.md](docs/USAGE.md) · [docs/DOWNLOAD.md](docs/DOWNLOAD.md)
