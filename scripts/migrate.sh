#!/bin/zsh
# AI Hub — di chuyển cache model mặc định vào kho hub, rồi symlink ngược.
# An toàn để chạy lại nhiều lần (idempotent).
#
# ⚠️  OLLAMA_NOPRUNE=1 là bắt buộc: `ollama serve` prune blob vô chủ khi khởi động.
#     Nếu nó chạy giữa lúc manifest đã dời mà blob chưa, ~46 GB sẽ bị xoá.
set -euo pipefail

HUB="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
STORE="$HUB/models"
STATE="$HUB/.migration-state.json"
export OLLAMA_NOPRUNE=1

info() { print -P "%F{cyan}▸%f $*"; }
ok()   { print -P "%F{green}✓%f $*"; }
warn() { print -P "%F{yellow}!%f $*"; }
die()  { print -P "%F{red}✗%f $*" >&2; exit 1; }

# ── 1. Ollama phải tắt ────────────────────────────────────────────────────────
info "Kiểm tra Ollama đã tắt chưa…"
osascript -e 'quit app "Ollama"' 2>/dev/null || true
pkill -x ollama 2>/dev/null || true
sleep 2
if lsof -nP -iTCP:11434 -sTCP:LISTEN >/dev/null 2>&1; then
  die "Cổng 11434 vẫn mở — Ollama còn chạy. Tắt thủ công rồi chạy lại."
fi
ok "Ollama đã tắt, cổng 11434 đóng"

# ── 2. ~/.aihub ───────────────────────────────────────────────────────────────
if [[ -L "$HOME/.aihub" ]]; then
  [[ "$(readlink "$HOME/.aihub")" == "$HUB" ]] || die "~/.aihub trỏ sai chỗ: $(readlink "$HOME/.aihub")"
  ok "~/.aihub đã đúng"
elif [[ -e "$HOME/.aihub" ]]; then
  die "~/.aihub tồn tại nhưng không phải symlink"
else
  ln -s "$HUB" "$HOME/.aihub"; ok "đã tạo ~/.aihub"
fi

# ── 3. Di chuyển từng cache ───────────────────────────────────────────────────
# Cặp: <đường dẫn cũ>|<tên thư mục con trong store>
PAIRS=(
  "$HOME/.ollama/models|ollama"
  "$HOME/.cache/huggingface|hf"
  "$HOME/.cache/whisper|whisper"
  "$HOME/.cache/torch|torch"
)

MOVED=()
for pair in "${PAIRS[@]}"; do
  SRC="${pair%%|*}"
  DST="$STORE/${pair##*|}"

  if [[ -L "$SRC" ]]; then
    LINK="$(readlink "$SRC")"
    if [[ "$LINK" == "$DST" || "$LINK" == "$HOME/.aihub/models/${pair##*|}" ]]; then
      ok "$SRC → đã trỏ về hub, bỏ qua"; continue
    fi
    die "$SRC là symlink nhưng trỏ tới $LINK — xử lý thủ công"
  fi

  if [[ ! -e "$SRC" ]]; then
    warn "$SRC không tồn tại — chỉ tạo symlink"
    mkdir -p "$DST" "$(dirname "$SRC")"
    ln -s "$DST" "$SRC"
    continue
  fi

  # Đích do bước dựng khung tạo sẵn và đang rỗng → phải xoá, nếu không `mv` sẽ
  # lồng nguồn vào trong nó. `rmdir` chỉ thành công khi rỗng ⇒ vừa là chốt an toàn.
  if [[ -d "$DST" ]]; then
    rmdir "$DST" 2>/dev/null || die "$DST đã có dữ liệu — dừng để tránh ghi đè"
  fi

  SZ="$(du -sh "$SRC" 2>/dev/null | cut -f1)"
  info "chuyển $SRC ($SZ) → $DST"
  mv "$SRC" "$DST"                                   # cùng volume APFS ⇒ rename tức thì
  mkdir -p "$(dirname "$SRC")"
  ln -s "$DST" "$SRC"
  MOVED+=("$SRC")
  ok "xong: $SRC → hub"
done

# ── 4. Các thư mục store còn lại ──────────────────────────────────────────────
mkdir -p "$STORE"/{ct2,custom,links,run}

# ── 5. Loại kho khỏi Time Machine ─────────────────────────────────────────────
if tmutil isexcluded "$STORE" 2>/dev/null | grep -q '\[Excluded\]'; then
  ok "kho đã được loại khỏi Time Machine"
else
  warn "chưa loại khỏi Time Machine. Chạy (cần mật khẩu):"
  print "     sudo tmutil addexclusion -p \"$STORE\""
fi

# ── 6. Ghi lại trạng thái để rollback ─────────────────────────────────────────
AIHUB_HUB="$HUB" "$HUB/.venv/bin/python" - "$STATE" <<'PY'
import json, os, sys, datetime
state = {
    "migrated_at": datetime.datetime.now().isoformat(timespec="seconds"),
    "hub": os.environ["AIHUB_HUB"],
    "pairs": [
        {"legacy": os.path.expanduser("~/.ollama/models"),     "store": "ollama"},
        {"legacy": os.path.expanduser("~/.cache/huggingface"), "store": "hf"},
        {"legacy": os.path.expanduser("~/.cache/whisper"),     "store": "whisper"},
        {"legacy": os.path.expanduser("~/.cache/torch"),       "store": "torch"},
    ],
}
json.dump(state, open(sys.argv[1], "w"), indent=2)
PY
ok "đã ghi $STATE"

print ""
ok "MIGRATE XONG. Bước tiếp theo:"
print "   1. aihub doctor          # phải xanh hết"
print "   2. aihub serve           # rồi: ollama list  (phải đủ 8 model)"
print "   3. chỉ khi 2 bước trên OK mới bỏ OLLAMA_NOPRUNE"
