# AI Hub — biến môi trường dùng chung.
# Nạp bằng: . "$HOME/.aihub/env/aihub.sh"
# Mọi giá trị dùng /Users/mac/.aihub (không dấu cách) — an toàn cho PATH, launchctl, JSON.

export AIHUB_HOME=/Users/mac/.aihub
export AIHUB_STORE=/Users/mac/.aihub/models

# ── Vị trí kho ───────────────────────────────────────────────────────────────
export OLLAMA_MODELS=/Users/mac/.aihub/models/ollama
export HF_HOME=/Users/mac/.aihub/models/hf          # dời cả hub/ xet/ assets/ token
export TORCH_HOME=/Users/mac/.aihub/models/torch
export AIHUB_WHISPER_DIR=/Users/mac/.aihub/models/whisper
export AIHUB_CT2_DIR=/Users/mac/.aihub/models/ct2
export AIHUB_CUSTOM_DIR=/Users/mac/.aihub/models/custom
export AIHUB_MLX_WHISPER=/Users/mac/.aihub/models/links/whisper-large-v3-turbo-mlx

# KHÔNG đặt HF_HUB_CACHE (sẽ bỏ lại xet/ ở chỗ cũ)
# KHÔNG đặt TRANSFORMERS_CACHE (đã deprecated)
# KHÔNG đặt XDG_CACHE_HOME (kéo theo pip/uv/npm — phạm vi quá rộng)
# KHÔNG đặt WINDOWS_ASR_MODEL_DIR toàn cục (bật /api/asr-models/setup trên macOS)

# ── Endpoint ─────────────────────────────────────────────────────────────────
export AIHUB_OLLAMA_URL=http://127.0.0.1:11434

# ── Điều phối RAM 16 GB (M1 Pro) ─────────────────────────────────────────────
export OLLAMA_MAX_LOADED_MODELS=1   # quan trọng nhất: 1 model lớn tại một thời điểm
export OLLAMA_NUM_PARALLEL=1        # mỗi slot song song cấp KV cache riêng
export OLLAMA_KEEP_ALIVE=5m         # nhả RAM sau 5 phút rảnh
export OLLAMA_MAX_QUEUED=8          # dự án thứ hai xếp hàng thay vì báo lỗi
export OLLAMA_CONTEXT_LENGTH=8192   # context là thứ ngốn RAM ẩn
export OLLAMA_FLASH_ATTENTION=1
export OLLAMA_KV_CACHE_TYPE=q8_0    # giảm ~½ RAM cho KV cache

case ":$PATH:" in
  *":/Users/mac/.aihub/bin:"*) ;;
  *) export PATH="/Users/mac/.aihub/bin:$PATH" ;;
esac
