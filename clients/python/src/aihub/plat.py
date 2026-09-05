"""Lớp phụ thuộc hệ điều hành.

Mọi chỗ trong AI Hub cần gọi xuống hệ điều hành đều đi qua đây, để phần còn lại
của code không phải rải `if sys.platform`. Bản gốc viết cho macOS dùng thẳng
`statvfs`, `du`, `vm_stat`, `pkill`, `ln -s` — không có cái nào chạy trên Windows.

Khác biệt đáng kể nhất là **liên kết thư mục**. Windows chỉ cho tạo symlink khi
bật Developer Mode hoặc chạy quyền admin; máy thường không có cả hai. Junction
(`mklink /J`) thì không cần quyền gì, hoạt động với thư mục trên ổ đĩa cục bộ, và
mọi công cụ đọc file đều đi qua nó trong suốt — nên nó là lựa chọn mặc định ở đây.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

WINDOWS = os.name == "nt"

#: Tên nền tảng dùng trong registry.toml (`platforms = [...]`).
PLATFORM = "windows" if WINDOWS else ("macos" if sys.platform == "darwin" else "linux")

# Junction chỉ dùng được cho thư mục cục bộ; symlink thì đa năng hơn nhưng cần
# quyền. Hai hằng này để thông điệp lỗi nói đúng thứ người dùng cần làm.
LINK_SYMLINK = "symlink"
LINK_JUNCTION = "junction"


def expand(path) -> Path:
    """Mở %USERPROFILE% / $HOME / ~ trong đường dẫn đọc từ file cấu hình.

    registry.toml phải chép được giữa các máy, nên nó ghi biến thay vì tên người
    dùng cụ thể.
    """
    return Path(os.path.expandvars(str(path))).expanduser()


# ─────────────────────────── đường dẫn gốc ───────────────────────────

def hub_root() -> Path:
    """Thư mục gốc của hub — nơi có registry.toml.

    Suy ra từ vị trí file này (`<hub>/clients/python/src/aihub/plat.py`) thay vì
    hardcode. Nhờ vậy hub chạy được ở bất kỳ ổ đĩa nào, và bản cài editable vẫn
    trỏ đúng chỗ. Biến môi trường AIHUB_HOME đè lên khi cần.
    """
    env = os.environ.get("AIHUB_HOME")
    if env:
        return Path(env)

    here = Path(__file__).resolve()
    # aihub/ → src/ → python/ → clients/ → <hub>
    cand = here.parents[4]
    if (cand / "registry.toml").is_file():
        return cand

    # Bản cài đã copy vào site-packages: không suy ra được, dùng quy ước.
    return Path.home() / ".aihub"


# ─────────────────────────────── đĩa ───────────────────────────────

def free_bytes(path) -> int:
    """Dung lượng trống trên volume chứa `path`. Thay cho os.statvfs."""
    p = Path(path)
    while not p.exists() and p != p.parent:
        p = p.parent
    return shutil.disk_usage(p).free


def dir_size_bytes(path) -> int:
    """Tổng byte trong một cây thư mục. Thay cho `du -sk`.

    Không đi theo symlink/junction: nếu không, kho trỏ vòng về chính nó sẽ khiến
    số liệu nhân đôi hoặc lặp vô hạn.
    """
    p = Path(path)
    if p.is_file():
        try:
            return p.stat().st_size
        except OSError:
            return 0
    total = 0
    for root, dirs, files in os.walk(p, followlinks=False):
        # os.walk không tự bỏ qua junction trên Windows như với symlink.
        dirs[:] = [d for d in dirs if not is_link(Path(root) / d)]
        for f in files:
            try:
                total += (Path(root) / f).stat().st_size
            except OSError:
                pass
    return total


# ─────────────────────────────── RAM ───────────────────────────────

def _ram_windows() -> tuple[float, float]:
    import ctypes
    from ctypes import wintypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    st = MEMORYSTATUSEX()
    st.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        return 0.0, 0.0
    return st.ullTotalPhys / 1e9, st.ullAvailPhys / 1e9


def _ram_macos() -> tuple[float, float]:
    total = subprocess.run(["sysctl", "-n", "hw.memsize"],
                           capture_output=True, text=True).stdout.strip()
    total_gb = int(total) / 1e9 if total.isdigit() else 0.0

    out = subprocess.run(["vm_stat"], capture_output=True, text=True).stdout
    pg, vals = 16384, {}
    for line in out.splitlines():
        if "page size of" in line:
            pg = int(line.split("page size of")[1].split()[0])
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip().rstrip(".")
            if v.isdigit():
                vals[k.strip()] = int(v)
    free = (vals.get("Pages free", 0) + vals.get("Pages inactive", 0)
            + vals.get("Pages speculative", 0))
    return total_gb, free * pg / 1e9


def _ram_linux() -> tuple[float, float]:
    total = avail = 0
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                total = int(line.split()[1]) * 1024
            elif line.startswith("MemAvailable:"):
                avail = int(line.split()[1]) * 1024
    except OSError:
        pass
    return total / 1e9, avail / 1e9


def ram_gb() -> tuple[float, float]:
    """(tổng RAM, RAM còn dùng được) theo GB."""
    try:
        if WINDOWS:
            return _ram_windows()
        if sys.platform == "darwin":
            return _ram_macos()
        return _ram_linux()
    except Exception:
        return 0.0, 0.0


# ───────────────────────────── liên kết ─────────────────────────────

def is_link(path) -> bool:
    """True nếu là symlink HOẶC junction (Windows). is_symlink() bỏ sót junction."""
    p = Path(path)
    if p.is_symlink():
        return True
    if not WINDOWS:
        return False
    try:
        # FILE_ATTRIBUTE_REPARSE_POINT = 0x400. Junction có bit này, thư mục thường không.
        return bool(p.lstat().st_file_attributes & 0x400)
    except (OSError, AttributeError):
        return False


def link_target(path) -> str | None:
    """Đích của symlink/junction, hoặc None nếu không phải liên kết."""
    p = Path(path)
    try:
        return os.readlink(p)          # Python 3.8+ đọc được cả junction trên Windows
    except OSError:
        return None


def unlink_link(path) -> None:
    """Gỡ một liên kết mà KHÔNG đụng tới dữ liệu nó trỏ tới.

    Junction là thư mục dưới con mắt của os.unlink → phải rmdir. Nhầm sang
    shutil.rmtree ở đây sẽ xoá sạch kho thật.
    """
    p = Path(path)
    if not is_link(p):
        raise OSError(f"{p} không phải liên kết — từ chối gỡ")
    try:
        p.unlink()
    except (OSError, PermissionError):
        os.rmdir(p)


def link_dir(target, link, force: bool = True) -> str:
    """Tạo liên kết thư mục `link` → `target`. Trả về loại đã dùng.

    Thử symlink trước (đi được xuyên ổ đĩa và qua mạng), tụt xuống junction khi
    Windows từ chối vì thiếu quyền.
    """
    target, link = Path(target), Path(link)
    if not target.is_dir():
        raise OSError(f"đích không tồn tại hoặc không phải thư mục: {target}")
    if link.exists() or link.is_symlink():
        if not force:
            raise OSError(f"{link} đã tồn tại")
        if is_link(link):
            unlink_link(link)
        else:
            raise OSError(f"{link} là thư mục thật, không phải liên kết — "
                          f"xử lý thủ công để tránh mất dữ liệu")
    link.parent.mkdir(parents=True, exist_ok=True)

    try:
        os.symlink(target, link, target_is_directory=True)
        return LINK_SYMLINK
    except OSError:
        if not WINDOWS:
            raise

    # Junction: không cần quyền, nhưng chỉ cho thư mục trên ổ cục bộ.
    out = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise OSError(
            f"không tạo được liên kết {link} → {target}.\n"
            f"symlink cần Developer Mode hoặc quyền admin; junction báo: "
            f"{(out.stderr or out.stdout).strip()}"
        )
    return LINK_JUNCTION


def link_file(target, link, force: bool = True) -> str:
    """Liên kết file. Symlink → hardlink → copy, theo thứ tự ưu tiên."""
    target, link = Path(target), Path(link)
    if link.exists() or link.is_symlink():
        if not force:
            raise OSError(f"{link} đã tồn tại")
        link.unlink()
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link)
        return LINK_SYMLINK
    except OSError:
        pass
    try:
        os.link(target, link)          # hardlink: cùng volume, không cần quyền
        return "hardlink"
    except OSError:
        shutil.copy2(target, link)
        return "copy"


def can_symlink() -> bool:
    """Máy này có tạo được symlink không (Developer Mode / admin)."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "src"
        src.mkdir()
        try:
            os.symlink(src, Path(d) / "lnk", target_is_directory=True)
            return True
        except OSError:
            return False


# ─────────────────────────── tiến trình ───────────────────────────

def ollama_bin() -> str | None:
    """Đường dẫn ollama. PATH trước, rồi các vị trí cài mặc định."""
    found = shutil.which("ollama")
    if found:
        return found
    cands = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
    ] if WINDOWS else [
        Path("/usr/local/bin/ollama"), Path("/opt/homebrew/bin/ollama"),
    ]
    for c in cands:
        if c.is_file():
            return str(c)
    return None


def spawn_detached(cmd: list[str], env: dict, log_path: Path):
    """Chạy nền, sống sót khi terminal cha đóng."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = log_path.open("a", encoding="utf-8", errors="replace")
    kwargs: dict = {"stdout": fh, "stderr": fh, "stdin": subprocess.DEVNULL}
    if WINDOWS:
        # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = 0x00000008 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, env=env, **kwargs)


def kill_ollama(pid: int | None = None) -> bool:
    """Tắt Ollama. True nếu đã gửi được tín hiệu."""
    if pid:
        try:
            os.kill(pid, 15)           # Windows: TerminateProcess
            return True
        except (OSError, ProcessLookupError):
            pass
    if WINDOWS:
        out = subprocess.run(["taskkill", "/IM", "ollama.exe", "/F", "/T"],
                             capture_output=True, text=True)
        return out.returncode == 0
    return subprocess.run(["pkill", "-x", "ollama"]).returncode == 0


def venv_python(venv: Path) -> Path:
    """Interpreter bên trong một venv, đúng theo layout của hệ điều hành."""
    venv = Path(venv).expanduser()
    if venv.is_file():
        return venv
    return venv / ("Scripts/python.exe" if WINDOWS else "bin/python")


# ─────────────────────────── console ───────────────────────────

def init_console() -> bool:
    """Cho terminal in được màu ANSI và tiếng Việt. True nếu màu dùng được.

    Windows Terminal bật sẵn VT; conhost cũ thì phải bật bằng tay. Khi output bị
    chuyển hướng ra file, stdout dùng bảng mã locale (cp1258/cp1252) và tiếng
    Việt sẽ hỏng — nên ép UTF-8.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if stream is not None and stream.encoding \
                    and stream.encoding.lower() not in ("utf-8", "utf8"):
                stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass

    if not sys.stdout or not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return False
    if not WINDOWS:
        return True
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-11)        # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if not k.GetConsoleMode(h, ctypes.byref(mode)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(k.SetConsoleMode(h, mode.value | 0x0004))
    except Exception:
        return False
