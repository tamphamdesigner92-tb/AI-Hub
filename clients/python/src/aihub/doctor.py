"""Kiểm tra sức khoẻ AI Hub. Mọi mục PASS / WARN / FAIL."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from . import plat
from .resolve import (HUB_HOME, get, hf_hub_cache, load_registry, store_dir,
                      store_root)

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


class Report:
    def __init__(self):
        self.rows: list[tuple[str, str, str]] = []

    def add(self, level, name, detail=""):
        self.rows.append((level, name, detail))

    @property
    def failed(self) -> int:
        return sum(1 for lv, _, _ in self.rows if lv == FAIL)

    @property
    def warned(self) -> int:
        return sum(1 for lv, _, _ in self.rows if lv == WARN)


def _readlink(p: Path) -> str | None:
    return plat.link_target(p)


def _same(a, b) -> bool:
    """So sánh hai đường dẫn, chịu được khác biệt hình thức của Windows.

    Junction trả về đích kèm tiền tố extended-length (vd
    "\\?\E:\AI Hub\models\ollama"). Path.resolve() KHÔNG bỏ tiền tố đó,
    nên so sánh thẳng sẽ báo "trỏ sai" cho một liên kết hoàn toàn đúng.
    """
    unc = '\\\\?\\UNC\\'
    dev = '\\\\?\\'

    def norm(x):
        t = str(x)
        if t.startswith(unc):
            t = '\\\\' + t[len(unc):]
        elif t.startswith(dev):
            t = t[len(dev):]
        return Path(t).resolve()

    try:
        return norm(a) == norm(b)
    except OSError:
        return False


def run(deep: bool = False) -> Report:
    r = Report()
    reg = load_registry(refresh=True)
    store = store_root()

    # ── 1. gốc hub ───────────────────────────────────────────────────────
    # registry.toml khai gốc hub; HUB_HOME thì suy ra từ vị trí file code. Hai
    # cái lệch nhau nghĩa là đang chạy code của hub này nhưng đọc registry của
    # hub khác — mọi số liệu bên dưới sẽ vô nghĩa, nên đây là FAIL.
    hub_real = Path(reg["hub"]["root"])
    if not HUB_HOME.exists():
        r.add(FAIL, "gốc hub", f"không tồn tại: {HUB_HOME}")
    elif _same(HUB_HOME, hub_real):
        r.add(PASS, "gốc hub", str(HUB_HOME))
    else:
        r.add(FAIL, "gốc hub",
              f"code chạy từ {HUB_HOME} nhưng registry.toml khai {hub_real}")

    # Bí danh không dấu cách. Bắt buộc trên macOS (launchctl/PATH); trên Windows
    # chỉ là tiện lợi cho client Node và script — thiếu thì chỉ WARN.
    alias = plat.expand(reg["hub"].get("home") or (Path.home() / ".aihub"))
    if plat.is_link(alias) and _same(_readlink(alias) or "", hub_real):
        r.add(PASS, f"bí danh {alias.name}", f"→ {hub_real}")
    elif alias.exists():
        r.add(WARN, f"bí danh {alias.name}",
              "tồn tại nhưng không phải liên kết tới hub")
    else:
        r.add(WARN, f"bí danh {alias.name}",
              "chưa tạo — chạy `aihub migrate` (client Node cần nó)")

    # Máy có tạo được symlink không: quyết định junction hay symlink ở mọi nơi.
    if plat.WINDOWS:
        if plat.can_symlink():
            r.add(PASS, "quyền tạo symlink", "có (Developer Mode hoặc admin)")
        else:
            r.add(WARN, "quyền tạo symlink",
                  "không có → hub dùng junction cho thư mục, hardlink cho file "
                  "(hoạt động bình thường)")

    # ── 2. kho & dung lượng ──────────────────────────────────────────────
    if store.is_dir():
        free = plat.free_bytes(store) / 1e9
        lvl = PASS if free > 20 else (WARN if free > 10 else FAIL)
        r.add(lvl, "đĩa trống", f"{free:.0f} GB")
    else:
        r.add(FAIL, "kho model", f"không tồn tại: {store}")

    # ── 3. symlink ngược của 4 cache ─────────────────────────────────────
    for kind, sd in reg.get("stores", {}).items():
        legacy = sd.get("legacy")
        if not legacy:
            continue
        lp = plat.expand(legacy)
        label = f"liên kết {kind}"
        if plat.is_link(lp):
            tgt = _readlink(lp)
            if _same(tgt or "", store / sd["path"]):
                r.add(PASS, label, f"{lp} → {tgt}")
            else:
                r.add(FAIL, label, f"trỏ sai: {tgt}")
        elif lp.is_dir():
            r.add(FAIL, label,
                  f"{lp} là THƯ MỤC THẬT — kho bị tách đôi, model sẽ tải lại")
        else:
            r.add(WARN, label, f"{lp} chưa migrate")

    # ── 4. biến môi trường ───────────────────────────────────────────────
    envfile = HUB_HOME / "env" / "aihub.env"
    if envfile.is_file():
        want = dict(
            line.split("=", 1)
            for line in envfile.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#") and "=" in line
        )
        miss = [k for k, v in want.items() if os.environ.get(k) != v]
        if not miss:
            r.add(PASS, "biến môi trường", f"{len(want)} biến khớp registry")
        else:
            r.add(WARN, "biến môi trường",
                  f"{len(miss)} chưa nạp trong shell này: {', '.join(miss[:4])}"
                  + ("…" if len(miss) > 4 else "")
                  + "  → mở terminal mới, hoặc nạp: "
                  + (r". $env:AIHUB_HOME\env\aihub.ps1" if plat.WINDOWS
                     else ". ~/.aihub/env/aihub.sh"))
        # lint secret
        bad = [k for k in want if any(s in k.lower()
               for s in ("key", "token", "secret", "password"))]
        r.add(FAIL if bad else PASS, "lint secret trong aihub.env",
              ", ".join(bad) if bad else "không có credential")
    else:
        r.add(FAIL, "env/aihub.env", "chưa có")

    # Env của app khởi động từ GUI. Trên macOS là launchctl; trên Windows là
    # biến người dùng trong registry — app bấm từ Start Menu đọc chỗ đó, không
    # đọc biến đặt tạm trong phiên terminal.
    if plat.WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
                try:
                    gui = winreg.QueryValueEx(k, "OLLAMA_MODELS")[0]
                except FileNotFoundError:
                    gui = ""
            r.add(PASS if gui else WARN, "biến người dùng OLLAMA_MODELS",
                  gui or "chưa đặt (app GUI dựa vào junction — vẫn OK)")
        except Exception:
            pass
    else:
        try:
            gui = subprocess.run(["launchctl", "getenv", "OLLAMA_MODELS"],
                                 capture_output=True, text=True, timeout=5).stdout.strip()
            r.add(PASS if gui else WARN, "launchctl OLLAMA_MODELS",
                  gui or "chưa đặt (app GUI dựa vào symlink — vẫn OK)")
        except Exception:
            pass

    # ── 5. toàn vẹn cache HuggingFace ────────────────────────────────────
    # huggingface_hub bình thường để snapshots/ là symlink trỏ vào blobs/. Trên
    # Windows không có quyền symlink thì nó copy file thật vào snapshot — hợp lệ,
    # chỉ tốn thêm đĩa. Vì vậy "0 symlink" không phải lỗi ở đây.
    # Model tải về sẽ rơi vào đâu. Nằm ngoài kho hub nghĩa là hub sẽ không thấy
    # nó — đúng triệu chứng "tải xong mà tab Model không hiện".
    hf_hub = hf_hub_cache()
    try:
        inside = store_root().resolve() in hf_hub.resolve().parents
    except OSError:
        inside = False
    r.add(PASS if inside else FAIL, "đích tải HF",
          str(hf_hub) + ("" if inside else "  — NGOÀI kho hub, tải xong sẽ không hiện"))

    if hf_hub.is_dir():
        dangling, total, plain = [], 0, 0
        for repo in hf_hub.glob("models--*"):
            for snap in (repo / "snapshots").glob("*/*"):
                if snap.is_symlink():
                    total += 1
                    if not snap.resolve().exists():
                        dangling.append(str(snap))
                elif snap.is_file():
                    plain += 1
        if dangling:
            r.add(FAIL, "snapshot HF",
                  f"{len(dangling)}/{total} symlink đứt — dấu hiệu bị copy sai cách")
        elif total:
            r.add(PASS, "snapshot HF", f"{total} symlink còn nguyên")
        elif plain:
            r.add(PASS, "snapshot HF",
                  f"{plain} file thật (Windows không symlink — bình thường)")
        else:
            r.add(WARN, "snapshot HF", "chưa có snapshot nào")
    else:
        r.add(WARN, "cache HF", "chưa có")

    # ── 6. manifest Ollama (gate cho prune) ──────────────────────────────
    om = Path(os.environ.get("OLLAMA_MODELS", str(store_dir("ollama"))))
    man_dir = om / "manifests"
    if man_dir.is_dir():
        bad, refs, n = [], set(), 0
        for f in man_dir.rglob("*"):
            if not f.is_file():
                continue
            n += 1
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                bad.append(str(f)); continue
            for layer in (d.get("layers") or []) + [d.get("config") or {}]:
                if isinstance(layer, dict) and layer.get("digest"):
                    refs.add(layer["digest"].replace(":", "-"))
        if bad:
            r.add(FAIL, "manifest Ollama",
                  f"{len(bad)} file hỏng → Ollama sẽ BỎ QUA prune hoàn toàn")
        else:
            r.add(PASS, "manifest Ollama", f"{n} manifest parse được")

        blobs = om / "blobs"
        if blobs.is_dir():
            names = {p.name for p in blobs.iterdir() if p.is_file()}
            orph = names - refs
            sz = sum((blobs / b).stat().st_size for b in orph) / 1e9
            r.add(PASS if not orph else WARN, "blob mồ côi",
                  "không có" if not orph else f"{len(orph)} blob, {sz:.2f} GB thu hồi được")
    else:
        r.add(WARN, "kho Ollama", "chưa có manifest")

    # ── 7. đối chiếu từng entry registry ─────────────────────────────────
    present = missing = cloud = 0
    miss_names = []
    for key in reg.get("models", {}):
        mi = get(key, with_disk=deep)
        if mi.status == "present":
            present += 1
        elif mi.status == "cloud":
            cloud += 1
        else:
            missing += 1; miss_names.append(key)
    r.add(PASS if not missing else WARN, "model trong registry",
          f"{present} có sẵn · {cloud} cloud · {missing} thiếu"
          + (f" ({', '.join(miss_names[:4])}…)" if missing else ""))

    # ── 7b. entry registry có đủ trường bắt buộc không ──
    # Sửa tay registry.toml dễ để lại bảng con mồ côi ([models.x.source] mà không
    # có [models.x]) — TOML vẫn hợp lệ nhưng entry thì vô dụng.
    REQUIRED = ("runtime", "store", "access", "task")
    broken = {k: [q for q in REQUIRED if q not in v]
              for k, v in reg.get("models", {}).items()
              if any(q not in v for q in REQUIRED)}
    if broken:
        r.add(FAIL, "entry registry khuyết trường",
              "; ".join(f"{k} thiếu {', '.join(v)}" for k, v in list(broken.items())[:3]))
    else:
        r.add(PASS, "entry registry", f"{len(reg.get('models', {}))} entry đủ trường")

    # ── 7c. model trên đĩa chưa khai báo ──
    from .resolve import discover
    und = discover()
    r.add(PASS if not und else WARN, "model chưa khai báo",
          "không có" if not und else
          f"{len(und)} model có trên đĩa chưa vào registry ({', '.join(m.name for m in und[:3])})"
          " → aihub adopt --apply")

    # ── 8. Ollama service ────────────────────────────────────────────────
    base = os.environ.get("AIHUB_OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        with urllib.request.urlopen(base + "/api/tags", timeout=3) as resp:
            tags = json.load(resp).get("models", [])
        r.add(PASS, "Ollama service", f"đang chạy · {len(tags)} model")
        try:
            with urllib.request.urlopen(base + "/api/ps", timeout=3) as resp:
                ps = json.load(resp).get("models", [])
            r.add(PASS, "model đang nạp RAM",
                  ", ".join(f"{m['name']} ({m.get('size',0)/1e9:.1f} GB)" for m in ps)
                  or "không có (RAM trống)")
        except Exception:
            pass
    except (urllib.error.URLError, OSError):
        r.add(WARN, "Ollama service", f"không chạy ở {base} — `aihub serve` để bật")

    # ── 9. loại kho khỏi backup / quét virus ─────────────────────────────
    # Trọng số model là file lớn, bất biến, tải lại được. Để công cụ backup hay
    # antivirus quét chúng là tốn IO thuần tuý.
    if plat.WINDOWS:
        try:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "(Get-MpPreference).ExclusionPath -join ';'"],
                capture_output=True, text=True, timeout=20).stdout.strip()
            paths = [x.strip().rstrip("\\").lower() for x in out.split(";") if x.strip()]
            if str(store).rstrip("\\").lower() in paths:
                r.add(PASS, "loại trừ Defender", "kho đã được loại trừ")
            else:
                r.add(WARN, "loại trừ Defender",
                      "chưa loại trừ → chạy PowerShell quyền admin: "
                      f'Add-MpPreference -ExclusionPath "{store}"')
        except Exception:
            pass
    else:
        try:
            out = subprocess.run(["tmutil", "isexcluded", str(store)],
                                 capture_output=True, text=True, timeout=5).stdout
            if "[Excluded]" in out:
                r.add(PASS, "Time Machine", "kho đã được loại trừ")
            else:
                r.add(WARN, "Time Machine",
                      f'chưa loại trừ → sudo tmutil addexclusion -p "{store}"')
        except Exception:
            pass

    # ── 10. client đã cài vào venv dự án chưa ────────────────────────────
    # Danh sách dự án nằm trong registry.toml ([hub].projects) chứ không hardcode
    # — mỗi máy có bố cục thư mục khác nhau.
    for entry in reg.get("hub", {}).get("projects", []):
        venv = Path(os.path.expandvars(entry)).expanduser()
        py = plat.venv_python(venv)
        if not py.exists():
            r.add(WARN, f"venv dự án · {venv.parent.name}", f"không thấy {py}")
            continue
        label = venv.parent.name
        try:
            out = subprocess.run([str(py), "-c", "import aihub;print(aihub.__version__)"],
                                 capture_output=True, text=True, timeout=30)
            if out.returncode == 0:
                r.add(PASS, f"import aihub · {label}", out.stdout.strip())
            else:
                r.add(WARN, f"import aihub · {label}",
                      f'chưa cài → aihub install --python "{venv}"')
        except Exception as e:
            r.add(WARN, f"import aihub · {label}", str(e)[:60])

    return r
