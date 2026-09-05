# Dùng AI Hub từ dự án khác

## Lệnh CLI

```
aihub list [--task asr] [--status present|missing|cloud|unsupported] [--json]
aihub info <tên>                 chi tiết một model
aihub path <tên>                 in đường dẫn (KHÔNG tải)
aihub ensure <tên>               tải nếu thiếu rồi in đường dẫn
aihub endpoint <tên> [--json]    in endpoint HTTP
aihub search <từ khoá>           tìm model trên HuggingFace
aihub adopt [--apply]            ghi model đã có trên đĩa vào registry
aihub pull <nguồn> [--dry-run] [--include ...]
aihub env [--ps|--sh|--cmd|--json]   biến môi trường của hub
aihub serve | stop | ps          quản lý Ollama
aihub doctor [--deep]            kiểm tra sức khoẻ
aihub du | gc [--apply]          dung lượng & dọn dẹp
aihub link [--projects]          tạo liên kết tên ổn định
aihub install --python <venv>    cài client vào venv dự án
aihub web [--port 7860]          dashboard
aihub migrate | rollback
```

`aihub env` mặc định in theo shell của hệ điều hành — PowerShell trên Windows,
POSIX ở nơi khác. Dán thẳng vào terminal được:

```powershell
aihub env | Invoke-Expression
```

## Thêm AI Hub vào một dự án Python mới

```powershell
aihub install --python E:\duong-dan\du-an\.venv
```

Đây là **editable install** — trỏ vào source trong hub, không copy. Sửa client một
lần là mọi dự án nhận ngay. Lệnh này tự tìm `Scripts\python.exe` (Windows) hoặc
`bin/python` (POSIX) trong venv bạn đưa vào.

```python
import aihub

# Model nạp in-process (Whisper, TTS, ASR)
model_dir = aihub.path("whisper-large-v3-ct2")
from faster_whisper import WhisperModel
model = WhisperModel(str(model_dir), device="cuda", compute_type="float16")

# Model chạy qua service (LLM, VLM)
url, model = aihub.endpoint("qwen3-5")
client = OpenAI(base_url=url, api_key="ollama")
resp = client.chat.completions.create(model=model, messages=[...])

# Tải nếu thiếu
aihub.ensure("wav2vec2-vi")

# Duyệt
for m in aihub.list(task="asr"):
    print(m.name, m.status, m.size_gb, m.tags)
```

`aihub.path()` **cố tình không tự tải** — tránh việc một vòng lặp nóng bất ngờ
block vài GB download. Muốn tải thì gọi `ensure()`.

Model khai `platforms` không chứa hệ điều hành hiện tại sẽ có `status ==
"unsupported"`; `aihub.path()` vẫn báo lỗi như bình thường, còn `aihub list` thì
đánh dấu rõ để bạn không mất công tải.

## Dự án Node / Electron

```js
const aihub = require(require('os').homedir() + '/.aihub/clients/node');
const p = aihub.path('whisper-large-v3-ct2');
const { openai, model } = aihub.endpoint('qwen3-5');
```

Đặt `AIHUB_HOME` nếu hub không nằm ở `~\.aihub`. Trên Windows client gọi thẳng
Python của hub, không đi qua `cmd.exe` — nhờ vậy tham số không bị shell diễn giải
lại.

**Với Electron, bắt buộc trải `aihub.env()` vào tiến trình con:**

```js
const child = spawn(cmd, args, { env: { ...process.env, ...aihub.env() } });
```

App mở từ Start Menu kế thừa môi trường lúc đăng nhập, **không** đọc biến bạn đặt
trong một phiên PowerShell. Thiếu dòng này thì backend sẽ tải model về
`%USERPROFILE%\.cache` thay vì dùng kho hub. (Chạy `aihub migrate -SetUserEnv` một
lần cũng giải quyết được, ở mức toàn hệ thống.)

## Dự án bằng ngôn ngữ khác

```powershell
$modelDir = aihub path whisper-large-v3-ct2
aihub env | Invoke-Expression
```

```bash
MODEL_DIR=$(aihub path whisper-large-v3-ct2)
eval "$(aihub env --sh)"
```

## Quản lý bộ nhớ — 32 GB RAM, GTX 1060 6 GB VRAM

Ràng buộc thật ở đây là **VRAM**, không phải RAM. Một model 9B lượng tử Q4_K_M
chiếm ~6,6 GB, đã vượt 6 GB VRAM của GTX 1060, nên Ollama đẩy bớt layer sang CPU.
Nạp hai model cùng lúc thì cả hai đều rơi xuống CPU và chậm hẳn — vì vậy cấu hình
vẫn giữ `OLLAMA_MAX_LOADED_MODELS=1` dù RAM rộng gấp đôi máy Mac gốc.

| Biến | Giá trị | Tác dụng |
|---|---|---|
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Quan trọng nhất — buộc unload-A-rồi-load-B |
| `OLLAMA_NUM_PARALLEL` | `1` | Mỗi slot song song cấp KV cache riêng |
| `OLLAMA_KEEP_ALIVE` | `5m` | Nhả bộ nhớ sau 5 phút rảnh |
| `OLLAMA_MAX_QUEUED` | `8` | Dự án thứ hai xếp hàng thay vì báo lỗi |
| `OLLAMA_CONTEXT_LENGTH` | `8192` | Context là thứ ngốn VRAM ẩn |
| `OLLAMA_FLASH_ATTENTION` | `1` | Giảm bộ nhớ attention |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Giảm ~½ bộ nhớ cho KV cache |

**Hai dự án xin hai model khác nhau:** A xong → A unload → B load (15–40 s) → B
chạy. Đúng nhưng chậm nếu xen kẽ. Cách tránh: cho cả hai dùng chung `qwen3-5` —
xem `default_llm` trong `registry.toml`.

Xem model nào đang chiếm bộ nhớ: `aihub ps`

## Nối một dự án vào hub

Nguyên tắc giữ nguyên từ bản gốc: mọi sửa đổi trong code dự án đều dạng

```python
model_dir = os.environ.get("AIHUB_CT2_WHISPER") or "<giá trị gốc>"
```

→ **không có AI Hub thì dự án chạy y như cũ.** Không fork, không phụ thuộc cứng.

Ba cách nối, chọn cái ít xâm lấn nhất mà dự án chịu được:

| Cách | Khi nào dùng | Sửa bao nhiêu |
|---|---|---|
| Liên kết thư mục | Dự án hardcode một đường dẫn model cố định | **0 dòng code** — khai `expose.project_link` trong `registry.toml` rồi `aihub link --projects` |
| Biến môi trường | Dự án đã đọc env cho đường dẫn model | 0–2 dòng |
| `import aihub` | Dự án Python và bạn sửa được | `aihub install --python <venv>` rồi gọi `aihub.path()` |

Khai dự án vào `[hub].projects` trong `registry.toml` để `aihub doctor` kiểm tra
client đã cài vào venv đó chưa:

```toml
[hub]
projects = ['E:\du-an\MoneyPrinterTurbo\.venv']
```

## Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `aihubdashboard` báo "is not recognized" | `bin\` của hub chưa vào PATH | Xem mục **Dùng nhanh** trong README, rồi mở terminal MỚI |
| Vừa thêm PATH mà vẫn không nhận | Terminal đang mở giữ PATH lúc nó khởi động | Mở cửa sổ mới |
| `ollama list` rỗng | `%USERPROFILE%\.ollama\models` bị tạo lại thành thư mục thật (thường sau khi Ollama tự update) | `aihub doctor` sẽ báo FAIL → chạy lại `aihub migrate` |
| Ollama vẫn tải model về `C:` | App khởi động từ Start Menu không thấy `OLLAMA_MODELS` | `.\scripts\migrate.ps1 -SetUserEnv` rồi đăng xuất/đăng nhập lại |
| Tiếng Việt trong terminal thành ký tự lạ | Output bị chuyển hướng ra file, Python rơi về bảng mã locale | Hub đã tự ép UTF-8; nếu vẫn lỗi thì đặt `PYTHONUTF8=1` |
| `aihub link` báo không tạo được liên kết | Không có quyền symlink và đích nằm trên ổ mạng/khác kiểu | Bật Developer Mode, hoặc để đích trên ổ cục bộ để dùng junction |
| Model tải lại dù đã có | Liên kết snapshot HF bị đứt (do copy sai cách) | `aihub doctor` kiểm mục "snapshot HF" |
| `import aihub` lỗi trong dự án | Chưa cài vào venv đó | `aihub install --python <venv>` |

> Trên Windows, `huggingface_hub` chép file thật vào `snapshots/` thay vì tạo
> symlink khi không có quyền. Tốn thêm đĩa nhưng hợp lệ — `aihub doctor` phân biệt
> trường hợp này với symlink đứt thật, và không báo lỗi giả.
