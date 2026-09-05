# Dùng AI Hub từ dự án khác

## Lệnh CLI

```
aihub list [--task asr] [--status present|missing|cloud] [--json]
aihub info <tên>                 chi tiết một model
aihub path <tên>                 in đường dẫn (KHÔNG tải)
aihub ensure <tên>               tải nếu thiếu rồi in đường dẫn
aihub endpoint <tên> [--json]    in endpoint HTTP
aihub search <từ khoá>           tìm model trên HuggingFace
aihub adopt [--apply]            ghi model đã có trên đĩa vào registry
aihub pull <nguồn> [--dry-run] [--include ...]
aihub env [--sh|--json]          biến môi trường của hub
aihub serve | stop | ps          quản lý Ollama
aihub doctor [--deep]            kiểm tra sức khoẻ
aihub du | gc [--apply]          dung lượng & dọn dẹp
aihub link [--projects]          tạo symlink tên ổn định
aihub install --python <venv>    cài client vào venv dự án
aihub web [--port 7860]          dashboard
aihub migrate | rollback
```

## Thêm AI Hub vào một dự án Python mới

```bash
aihub install --python /duong/dan/du-an/.venv
```

Đây là **editable install** — trỏ vào source trong hub, không copy. Sửa client một
lần là mọi dự án nhận ngay.

```python
import aihub

# Model nạp in-process (Whisper, TTS, ASR)
model_dir = aihub.path("whisper-turbo-mlx")
result = mlx_whisper.transcribe(audio, path_or_hf_repo=str(model_dir))

# Model chạy qua service (LLM, VLM)
url, model = aihub.endpoint("qwen3-5")
client = OpenAI(base_url=url, api_key="ollama")
resp = client.chat.completions.create(model=model, messages=[...])

# Tải nếu thiếu
aihub.ensure("vieneu-tts")

# Duyệt
for m in aihub.list(task="asr"):
    print(m.name, m.status, m.size_gb, m.tags)
```

`aihub.path()` **cố tình không tự tải** — tránh việc một vòng lặp nóng bất ngờ block
3 GB download. Muốn tải thì gọi `ensure()`.

## Dự án Node / Electron

```js
const aihub = require(require('os').homedir() + '/.aihub/clients/node');
const p = aihub.path('whisper-turbo-mlx');
const { openai, model } = aihub.endpoint('qwen3-5');
```

**Với Electron, bắt buộc trải `aihub.env()` vào tiến trình con:**

```js
const child = spawn(cmd, args, { env: { ...process.env, ...aihub.env() } });
```

App mở từ Finder kế thừa môi trường của `launchd`, **không** đọc `~/.zprofile`. Thiếu
dòng này thì backend sẽ tải model về `~/.cache` thay vì dùng kho hub.

## Dự án bằng ngôn ngữ khác

```bash
MODEL_DIR=$(aihub path whisper-turbo-mlx)
eval "$(aihub env --sh)"
```

## Quản lý RAM — máy này chỉ có 16 GB

Model trong kho nặng 6–12 GB. Chỉ **một** model lớn nằm trong RAM tại một thời điểm.
Cấu hình trong `env/aihub.sh` đã lo việc này:

| Biến | Giá trị | Tác dụng |
|---|---|---|
| `OLLAMA_MAX_LOADED_MODELS` | `1` | Quan trọng nhất — buộc unload-A-rồi-load-B |
| `OLLAMA_NUM_PARALLEL` | `1` | Mỗi slot song song cấp KV cache riêng |
| `OLLAMA_KEEP_ALIVE` | `5m` | Nhả RAM sau 5 phút rảnh |
| `OLLAMA_MAX_QUEUED` | `8` | Dự án thứ hai xếp hàng thay vì báo lỗi |
| `OLLAMA_CONTEXT_LENGTH` | `8192` | Context là thứ ngốn RAM ẩn |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Giảm ~½ RAM cho KV cache |

**Hai dự án xin hai model khác nhau:** A xong → A unload → B load (15–40 s) → B chạy.
Đúng nhưng chậm nếu xen kẽ. Cách tránh: cho cả hai dùng chung `qwen3-5` (6.6 GB) —
xem `default_llm` trong `registry.toml`.

Xem model nào đang chiếm RAM: `aihub ps`

> `OLLAMA_FLASH_ATTENTION` và `OLLAMA_KV_CACHE_TYPE` vốn thuộc backend GGML. Ollama
> 0.32.4 có thêm backend MLX cho Apple Silicon; **chưa xác nhận** backend MLX có tôn
> trọng hai biến này không. Cứ đặt (vô hại nếu bị bỏ qua) rồi đo thật bằng `aihub ps`.

## Ba dự án hiện có đang nối thế nào

| Dự án | Cách nối |
|---|---|
| `MoneyPrinterTurbo` | **0 dòng code.** `models/whisper-large-v3` là symlink vào hub; `subtitle.py:29` tự dò thấy `model.bin` |
| `Test 1 - Whisper` | `core_logic.py` 2 chỗ đọc `AIHUB_MLX_WHISPER` / `AIHUB_WHISPER_DIR`; `electron/main.js` trải `aihub.env()` vào backend |
| `Editing-Video-Pipeline-4.0-gemma` | `run_app.sh` nạp `aihub.sh`; `auto_cut_v4.0.py` 3 chỗ đọc env |

Mọi sửa đổi đều dạng `os.environ.get(...) or <giá trị gốc>` → **không có AI Hub thì
chạy y như cũ**. File gốc được backup dạng `*.bak-aihub` cạnh file đã sửa.

## Sự cố thường gặp

| Triệu chứng | Nguyên nhân | Xử lý |
|---|---|---|
| `ollama list` rỗng | `~/.ollama/models` bị tạo lại thành thư mục thật (thường sau khi Ollama tự update) | `aihub doctor` sẽ báo FAIL → chạy `aihub link --system` |
| App GUI hỏi quyền truy cập Documents | Kho nằm trong `~/Documents`, macOS bảo vệ (TCC) | Bấm Cho phép. Nếu không muốn: đổi `AIHUB_STORE` sang `~/Library/Application Support/AIHub/models` |
| Model tải lại dù đã có | Symlink snapshot HF bị đứt (do ai đó `cp -R` thay vì `mv`) | `aihub doctor` kiểm mục "symlink snapshot HF" |
| `import aihub` lỗi trong dự án | Chưa cài vào venv đó | `aihub install --python <venv>` |
