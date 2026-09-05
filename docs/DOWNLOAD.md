# Tải model từ nguồn online về AI Hub

Mọi model tải về đều nằm trong `~/.aihub/models/` — **không bao giờ** vào thư mục dự án.

Dùng CLI (`aihub pull …`) hoặc tab **Thêm model** trên dashboard (`aihub web`).

## Cú pháp theo nguồn

| Nguồn | Lệnh | Rơi vào |
|---|---|---|
| Ollama registry | `aihub pull ollama:qwen3.5:9b` | `models/ollama/` |
| HuggingFace (cả repo) | `aihub pull hf:mlx-community/whisper-large-v3-turbo` | `models/hf/hub/` |
| HuggingFace (lọc file) | `aihub pull hf:org/repo --include '*.safetensors' '*.json'` | `models/hf/hub/` |
| HF — đúng 1 file GGUF | `aihub pull gguf:bartowski/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf` | `models/custom/gguf/` |
| GitHub release | `aihub pull gh:owner/repo@v1.0/model.onnx` | `models/custom/` |
| URL trực tiếp | `aihub pull url:https://…/model.bin --sha256 <hash>` | `models/custom/` |
| Git repo (cần git-lfs) | `aihub pull git:https://github.com/…` | `models/custom/` |
| Đã khai trong registry | `aihub pull whisper-medium-ct2` | theo `store` của nó |

Thêm `--dry-run` vào bất kỳ lệnh nào để **xem danh sách file và tổng dung lượng mà
không tải gì**.

## Không nhớ tên chính xác? Tìm trước

```bash
aihub search VoxCPM
```
```
 ★ mlx-community/VoxCPM2-4bit          2.30 GB  ⬇389      ← ★ tối ưu Apple Silicon
 ◆ DennisHuang648/VoxCPM2-GGUF         6.80 GB  ⬇6,623    ← ◆ dùng được với Ollama
   openbmb/VoxCPM2                     4.96 GB  ⬇318,971
```

Trên dashboard: gõ từ khoá rồi bấm **Tìm**, bấm một dòng là tự điền và xem trước.

## Dán gì cũng được

Không cần nhớ cú pháp — dán nguyên lệnh chép từ trang web, hoặc dán URL:

| Bạn dán | AI Hub hiểu thành |
|---|---|
| `ollama run gemma4:e4b` | `ollama:gemma4:e4b` |
| `hf download openbmb/VoxCPM2` | `hf:openbmb/VoxCPM2` |
| `https://huggingface.co/mlx-community/VoxCPM2-4bit` | `hf:mlx-community/VoxCPM2-4bit` |
| `https://github.com/o/r/releases/download/v1/m.onnx` | `gh:o/r@v1/m.onnx` |

## ⚠️ GitHub thường KHÔNG chứa trọng số model

Đây là nhầm lẫn hay gặp nhất. `gh repo clone OpenBMB/VoxCPM` tải về **mã nguồn** —
code để chạy model, không phải bản thân model. Trọng số hầu như luôn nằm trên
HuggingFace.

```
GitHub  OpenBMB/VoxCPM        → code suy luận   → git clone vào thư mục DỰ ÁN
HF      openbmb/VoxCPM2       → trọng số 4.96GB → aihub pull vào AI HUB
```

AI Hub là kho **trọng số**, nên nó từ chối `gh repo clone` và chỉ bạn sang `aihub search`.
`gh:` trong AI Hub chỉ dùng cho **file đính kèm trong GitHub Release** (`.onnx`, `.bin`…),
không phải clone repo.

## 5 điều phải nhớ

### 1. Luôn `--dry-run` trước, và luôn `--include` với repo GGUF

Nhiều repo GGUF chứa 8–12 bản lượng tử hoá của cùng một model. Ví dụ thật:

```bash
aihub pull hf:bartowski/Qwen2.5-7B-Instruct-GGUF --dry-run
#  → 27 file, 121.06 GB          ← tải cả repo

aihub pull hf:bartowski/Qwen2.5-7B-Instruct-GGUF --include '*Q4_K_M.gguf' --dry-run
#  → 1 file, 4.68 GB             ← thứ bạn thực sự cần
```

Chênh **26 lần**.

### 2. Kiểm tra dung lượng trống

`aihub pull` tự từ chối nếu sau khi tải còn dưới 20 GB. Xem hiện trạng: `aihub du`.

### 3. Model gated cần token

Llama và vài bản Gemma yêu cầu đăng nhập HuggingFace. Token lưu ở
`~/.aihub/models/hf/token` (chmod 0600). **Không bao giờ** ghi token vào `registry.toml`.

```bash
~/.aihub/.venv/bin/python -c "from huggingface_hub import login; login()"
```

### 4. Chọn đúng định dạng cho M1 Pro

Nhanh nhất → chậm nhất:

| Định dạng | Chạy bằng | Ghi chú |
|---|---|---|
| **MLX** | `mlx_whisper`, `mlx_lm` | Native Apple Silicon, dùng GPU Metal |
| **GGUF** | Ollama | Tiện nhất cho LLM, có sẵn hạ tầng |
| **CTranslate2** | `faster-whisper` | Tốt cho CPU với `int8` |
| **PyTorch `.pt`** | `openai-whisper`, `transformers` | Chậm nhất trên máy này |

Cùng một model ở 3 định dạng là **3 bản sao đĩa** — không dedupe được. Chọn một.

### 5. Model tải xong tự vào thư viện

`aihub pull` tự ghi entry vào `registry.toml` ngay sau khi tải, nên model xuất hiện
trên dashboard mà bạn không phải làm gì. Tác vụ và thẻ lấy từ model card HuggingFace.

**Model tải bằng đường khác** — dự án tự tải, `ollama pull` gõ thẳng, hay có từ trước
khi dựng AI Hub — vẫn hiện trên dashboard với nhãn *chưa khai báo* kèm nút **Thêm vào
thư viện**. Từ terminal:

```bash
aihub adopt              # xem có gì chưa khai báo
aihub adopt --apply      # ghi hết vào registry
```

`aihub doctor` cũng cảnh báo khi thấy model trên đĩa chưa vào registry.

Entry tự sinh có mô tả tạm — mở `registry.toml` sửa lại cho rõ nghĩa:

```toml
[models.ten-goi-ngan]
title   = "Tên hiển thị"
runtime = "mlx"              # mlx | ollama | faster-whisper | hf-transformers | onnx | gguf
store   = "hf"               # hf | ollama | whisper | custom | ct2
access  = ["path"]           # path | endpoint
task    = "asr"              # chat | code | vision | asr | tts | image
size_gb = 1.5
ram_gb  = 2.0
tags    = ["nhanh", "tiếng Việt"]
desc    = "Một câu mô tả model làm được gì."
strengths = ["việc A", "việc B"]
owners  = []                 # dự án nào đang dùng
[models.ten-goi-ngan.source]
kind = "hf"
repo = "org/repo"
```

Rồi chạy `aihub link` để tạo tên ổn định trong `models/links/`.

> **Vì sao cần `links/`:** đường dẫn snapshot HuggingFace chứa commit SHA và đổi mỗi
> lần tải lại. `models/links/<tên>` cho bạn một đường dẫn không bao giờ đổi.

## Xoá model

```bash
aihub gc --dry-run      # liệt kê ứng viên (model bị đánh dấu archive_candidate)
aihub gc --apply        # xoá, có hỏi xác nhận
```

Hoặc bấm nút "Xoá" trên dashboard (hỏi xác nhận 2 lần).
