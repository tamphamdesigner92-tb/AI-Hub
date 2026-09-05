# AI Hub — nạp biến môi trường vào shell POSIX (macOS, Linux, Git Bash, WSL).
#
#   . "/duong/dan/AI Hub/env/aihub.sh"
#
# Trên Windows PowerShell dùng env/aihub.ps1 — cùng nội dung, cùng nguồn dữ liệu.
#
# Script đọc lại aihub.env chứ không chép giá trị vào đây: một nguồn sự thật duy
# nhất, sửa một chỗ là mọi shell nhận cùng lúc.

_aihub_env_file() {
  # ${BASH_SOURCE[0]} với bash, $0 khi được `.` từ sh thuần.
  _src="${BASH_SOURCE[0]:-$0}"
  ( CDPATH= cd -- "$(dirname -- "$_src")" && pwd )
}

_AIHUB_ENV_DIR="$(_aihub_env_file)"
_AIHUB_HUB="$(CDPATH= cd -- "$_AIHUB_ENV_DIR/.." && pwd)"
_AIHUB_FILE="$_AIHUB_ENV_DIR/aihub.env"

if [ ! -f "$_AIHUB_FILE" ]; then
  echo "AI Hub: không thấy $_AIHUB_FILE" >&2
else
  while IFS= read -r _line || [ -n "$_line" ]; do
    case "$_line" in
      ''|'#'*) continue ;;
    esac
    _name="${_line%%=*}"
    _value="${_line#*=}"
    [ "$_name" = "$_line" ] && continue
    # Đường dẫn có thể ghi $HOME để chép được sang máy khác.
    eval "_value=\"$_value\"" 2>/dev/null || :
    export "$_name=$_value"
  done < "$_AIHUB_FILE"
fi

# Vị trí thật của script là giá trị chắc chắn đúng — đè lên giá trị trong file.
export AIHUB_HOME="$_AIHUB_HUB"

case ":$PATH:" in
  *":$_AIHUB_HUB/bin:"*) ;;
  *) export PATH="$_AIHUB_HUB/bin:$PATH" ;;
esac

unset _AIHUB_ENV_DIR _AIHUB_HUB _AIHUB_FILE _line _name _value _src
unset -f _aihub_env_file
