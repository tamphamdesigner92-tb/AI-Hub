"""Kiểm tra sức khoẻ AI Hub. Mọi mục PASS / WARN / FAIL."""
from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .resolve import HUB_HOME, load_registry, store_dir, store_root, get, load_registry

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
    try:
        return os.readlink(p)
    except OSError:
        return None


def run(deep: bool = False) -> Report:
    r = Report()
    reg = load_registry(refresh=True)
    store = store_root()

    # ── 1. hub & symlink khử dấu cách ────────────────────────────────────
    hub_real = Path(reg["hub"]["root"])
    if HUB_HOME.is_symlink() and Path(_readlink(HUB_HOME) or "") == hub_real:
        r.add(PASS, "~/.aihub", f"→ {hub_real}")
    elif HUB_HOME.exists():
        r.add(FAIL, "~/.aihub", "tồn tại nhưng không phải symlink tới hub")
    else:
        r.add(FAIL, "~/.aihub", "chưa tạo — chạy scripts/migrate.sh")

    # ── 2. kho & dung lượng ──────────────────────────────────────────────
    if store.is_dir():
        st = os.statvfs(store)
        free = st.f_bavail * st.f_frsize / 1e9
        lvl = PASS if free > 20 else (WARN if free > 10 else FAIL)
        r.add(lvl, "đĩa trống", f"{free:.0f} GB")
    else:
        r.add(FAIL, "kho model", f"không tồn tại: {store}")

    # ── 3. symlink ngược của 4 cache ─────────────────────────────────────
    for kind, sd in reg.get("stores", {}).items():
        legacy = sd.get("legacy")
        if not legacy:
            continue
        lp, want = Path(legacy), f"/Users/mac/.aihub/models/{sd['path']}"
        if lp.is_symlink():
            tgt = _readlink(lp)
            if Path(tgt or "").resolve() == (store / sd["path"]).resolve():
                r.add(PASS, f"symlink {legacy}", f"→ {tgt}")
            else:
                r.add(FAIL, f"symlink {legacy}", f"trỏ sai: {tgt}")
        elif lp.is_dir():
            r.add(FAIL, f"symlink {legacy}",
                  "là THƯ MỤC THẬT — kho bị tách đôi, model sẽ tải lại")
        else:
            r.add(WARN, f"symlink {legacy}", "chưa migrate")

    # ── 4. biến môi trường ───────────────────────────────────────────────
    envfile = HUB_HOME / "env" / "aihub.env"
    if envfile.is_file():
        want = dict(
            line.split("=", 1)
            for line in envfile.read_text().splitlines()
            if line.strip() and not line.startswith("#") and "=" in line
        )
        miss = [k for k, v in want.items() if os.environ.get(k) != v]
        if not miss:
            r.add(PASS, "biến môi trường", f"{len(want)} biến khớp registry")
        else:
            r.add(WARN, "biến môi trường",
                  f"{len(miss)} chưa nạp trong shell này: {', '.join(miss[:4])}"
                  + ("…" if len(miss) > 4 else "")
                  + "  → mở terminal mới hoặc: . ~/.aihub/env/aihub.sh")
        # lint secret
        bad = [k for k in want if any(s in k.lower()
               for s in ("key", "token", "secret", "password"))]
        r.add(FAIL if bad else PASS, "lint secret trong aihub.env",
              ", ".join(bad) if bad else "không có credential")
    else:
        r.add(FAIL, "env/aihub.env", "chưa có")

    # env của tiến trình GUI (launchctl) — khác với env của zsh
    try:
        gui = subprocess.run(["launchctl", "getenv", "OLLAMA_MODELS"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        r.add(PASS if gui else WARN, "launchctl OLLAMA_MODELS",
              gui or "chưa đặt (app GUI dựa vào symlink — vẫn OK)")
    except Exception:
        pass

    # ── 5. toàn vẹn cache HuggingFace ────────────────────────────────────
    hf_hub = Path(os.environ.get("HF_HOME", str(store_dir("hf")))) / "hub"
    if hf_hub.is_dir():
        dangling, total = [], 0
        for repo in hf_hub.glob("models--*"):
            for snap in (repo / "snapshots").glob("*/*"):
                if snap.is_symlink():
                    total += 1
                    if not snap.resolve().exists():
                        dangling.append(str(snap))
        if dangling:
            r.add(FAIL, "symlink snapshot HF",
                  f"{len(dangling)}/{total} đứt — dấu hiệu bị `cp -R`")
        else:
            r.add(PASS, "symlink snapshot HF", f"{total} symlink còn nguyên")
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
                d = json.loads(f.read_text())
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

    # ── 9. Time Machine ──────────────────────────────────────────────────
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
    venvs = [
        "/Users/mac/Documents/AI/MoneyPrinterTurbo/.venv/bin/python",
        "/Users/mac/Documents/AI/video editing/Test 1 - Whisper/.venv/bin/python",
        "/Users/mac/Documents/AI/video editing/Test 1 - Whisper/.venv/bin/python3.14",
    ]
    for py in venvs:
        if not Path(py).exists():
            continue
        label = Path(py).parents[2].name + "/" + Path(py).name
        try:
            out = subprocess.run([py, "-c", "import aihub;print(aihub.__version__)"],
                                 capture_output=True, text=True, timeout=20)
            if out.returncode == 0:
                r.add(PASS, f"import aihub · {label}", out.stdout.strip())
            else:
                r.add(WARN, f"import aihub · {label}",
                      f"chưa cài → aihub install --python '{Path(py).parents[1]}'")
        except Exception as e:
            r.add(WARN, f"import aihub · {label}", str(e)[:60])

    return r
