#!/bin/zsh
# AI Hub — hoàn tác migrate.sh. Đưa dữ liệu về đúng cache mặc định ban đầu.
set -euo pipefail

HUB="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
STORE="$HUB/models"
export OLLAMA_NOPRUNE=1

info() { print -P "%F{cyan}▸%f $*"; }
ok()   { print -P "%F{green}✓%f $*"; }
warn() { print -P "%F{yellow}!%f $*"; }
die()  { print -P "%F{red}✗%f $*" >&2; exit 1; }

print -P "%F{yellow}Sẽ đưa toàn bộ model về ~/.ollama và ~/.cache. Gõ ROLLBACK để xác nhận:%f"
read -r ans
[[ "$ans" == "ROLLBACK" ]] || die "đã huỷ"

osascript -e 'quit app "Ollama"' 2>/dev/null || true
pkill -x ollama 2>/dev/null || true
sleep 2

PAIRS=(
  "$HOME/.ollama/models|ollama"
  "$HOME/.cache/huggingface|hf"
  "$HOME/.cache/whisper|whisper"
  "$HOME/.cache/torch|torch"
)

for pair in "${PAIRS[@]}"; do
  SRC="${pair%%|*}"; NAME="${pair##*|}"; DST="$STORE/$NAME"
  if [[ ! -L "$SRC" ]]; then warn "$SRC không phải symlink — bỏ qua"; continue; fi
  [[ -d "$DST" ]] || { warn "$DST không có dữ liệu — chỉ gỡ symlink"; rm "$SRC"; continue; }
  rm "$SRC"                      # rm, KHÔNG rm -rf: chỉ gỡ symlink
  mv "$DST" "$SRC"
  ok "trả về $SRC"
done

[[ -L "$HOME/.aihub" ]] && rm "$HOME/.aihub" && ok "gỡ ~/.aihub"

launchctl unsetenv OLLAMA_MODELS 2>/dev/null || true
launchctl unsetenv HF_HOME 2>/dev/null || true

if grep -q 'aihub/env/aihub.sh' "$HOME/.zprofile" 2>/dev/null; then
  cp "$HOME/.zprofile" "$HOME/.zprofile.aihub-backup"
  grep -v 'aihub/env/aihub.sh' "$HOME/.zprofile.aihub-backup" > "$HOME/.zprofile"
  ok "gỡ dòng source khỏi ~/.zprofile (backup: ~/.zprofile.aihub-backup)"
fi

warn "Còn 1 việc cần mật khẩu:  sudo tmutil removeexclusion -p \"$STORE\""
ok "ROLLBACK XONG. Mở terminal mới rồi chạy: ollama list"
