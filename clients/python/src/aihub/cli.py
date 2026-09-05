"""CLI của AI Hub — dùng được từ mọi ngôn ngữ và từ terminal."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import plat
from . import resolve as R
from .resolve import HUB_HOME, get, list_models, load_registry, store_dir, store_root

G, Y, RD, C, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[1m", "\033[0m"
if not plat.init_console():
    G = Y = RD = C = B = X = ""

BADGE = {"present": f"{G}●{X} có sẵn", "missing": f"{Y}○{X} chưa tải",
         "cloud": f"{C}☁{X} cloud", "partial": f"{Y}◐{X} thiếu file",
         "unsupported": f"{RD}⊘{X} khác nền tảng"}


def die(msg: str, code: int = 1):
    print(f"{RD}✗{X} {msg}", file=sys.stderr)
    raise SystemExit(code)


# ───────────────────────────── lệnh ─────────────────────────────

def cmd_path(a):
    try:
        print(R.resolve_path(a.name))
    except (R.ModelNotAvailable, R.ModelNotFound) as e:
        die(str(e))


def cmd_ensure(a):
    from . import ensure
    try:
        print(ensure(a.name))
    except Exception as e:
        die(str(e))


def cmd_endpoint(a):
    try:
        ep = R.resolve_endpoint(a.name)
    except (R.ModelNotAvailable, R.ModelNotFound) as e:
        die(str(e))
    if a.json:
        print(json.dumps(ep.__dict__))
    else:
        print(f"{ep.openai}\t{ep.model}")


def cmd_list(a):
    rows = list_models(task=a.task, runtime=a.runtime, status=a.status, with_disk=True)
    if a.json:
        print(json.dumps([m.__dict__ for m in rows], ensure_ascii=False, indent=2))
        return
    if not rows:
        print("(không có model nào khớp bộ lọc)"); return
    w = max(len(m.name) for m in rows)
    cur = None
    for m in rows:
        if m.task != cur:
            cur = m.task
            print(f"\n{B}{cur.upper()}{X}")
        star = f"{G}★{X}" if m.recommended else " "
        gc = f" {Y}[có thể dọn]{X}" if m.archive_candidate else ""
        print(f" {star} {m.name:<{w}}  {BADGE[m.status]}  "
              f"{(m.disk_gb if m.disk_gb is not None else m.size_gb):>5.1f} GB  RAM {m.ram_gb:>4.1f} GB  "
              f"{C}{m.runtime}{X}{gc}")
        if m.tags:
            print(f"   {' '.join('·'+t for t in m.tags)}")
    tot = sum((m.disk_gb if m.disk_gb is not None else m.size_gb) for m in rows)
    rec = sum((m.disk_gb if m.disk_gb is not None else m.size_gb) for m in rows if m.archive_candidate)
    print(f"\n{len(rows)} model · {tot:.1f} GB" +
          (f" · {Y}{rec:.1f} GB có thể dọn{X}" if rec else ""))


def cmd_info(a):
    try:
        m = get(a.name, with_disk=True)
    except R.ModelNotFound as e:
        die(str(e))
    if a.json:
        print(json.dumps(m.__dict__, ensure_ascii=False, indent=2)); return
    print(f"\n{B}{m.title}{X}   {BADGE[m.status]}")
    print(f"  tên gọi     {m.name}" + (f"  (alias: {', '.join(m.aliases)})" if m.aliases else ""))
    if m.desc:
        print(f"  mô tả       {m.desc}")
    if m.tags:
        print(f"  thẻ         {' '.join('·'+t for t in m.tags)}")
    if m.strengths:
        print(f"  làm tốt     {', '.join(m.strengths)}")
    print(f"  tác vụ      {m.task}      runtime {m.runtime}"
          + (f"      lượng tử {m.quant}" if m.quant else ""))
    print(f"  đĩa         {m.size_gb:.1f} GB (khai báo)"
          + (f" (thực đo {m.disk_gb:.2f} GB)" if m.disk_gb else ""))
    print(f"  RAM cần     {m.ram_gb:.1f} GB")
    print(f"  truy cập    {', '.join(m.access)}")
    if m.owners:
        print(f"  dùng bởi    {', '.join(m.owners)}")
    if m.path:
        print(f"  đường dẫn   {m.path}")
    if "endpoint" in m.access:
        ep = R.resolve_endpoint(m.name)
        print(f"  endpoint    {ep.openai}   model={ep.model}")
    print()


def _fmt_preview(p: dict) -> str:
    lines = [f"{B}{p['repo']}{X} — {p['count']} file, {p['total_gb']:.2f} GB"]
    for f in sorted(p["files"], key=lambda x: -x["size"])[:15]:
        lines.append(f"   {f['size']/1e6:>9.1f} MB  {f['name']}")
    if p["count"] > 15:
        lines.append(f"   … còn {p['count']-15} file")
    return "\n".join(lines)


def cmd_pull(a):
    from . import fetch
    try:
        res = fetch.pull(a.source, include=a.include, exclude=a.exclude,
                         dry_run=a.dry_run, sha256=a.sha256)
    except fetch.PullError as e:
        die(str(e))

    if a.dry_run:
        print(_fmt_preview(res) if isinstance(res, dict) else res)
        print(f"\n{Y}(dry-run — chưa tải gì){X}")
        return

    if hasattr(res, "__iter__") and not isinstance(res, (str, Path, dict)):
        last = ""
        for msg in res:                      # stream tiến trình của Ollama
            s = msg.get("status", "")
            if msg.get("total"):
                pct = 100 * msg.get("completed", 0) / msg["total"]
                bar = "█" * int(pct / 4) + "░" * (25 - int(pct / 4))
                print(f"\r  {bar} {pct:5.1f}%  {s[:40]:<40}", end="", flush=True)
            elif s != last:
                print(f"\r  {s:<70}", flush=True); last = s
        print(f"\n{G}✓{X} xong")
        _autoregister()
        return

    print(f"{G}✓{X} {res}")
    _autoregister()


def _autoregister():
    """Sau khi tải, ghi ngay vào registry.toml — nếu không model sẽ vô hình."""
    from . import fetch
    try:
        added = fetch.adopt_all()
    except Exception as e:
        print(f"{Y}!{X} chưa ghi được vào registry: {e}"); return
    for n in added:
        print(f"{G}✓{X} đã thêm vào registry: {B}{n}{X}  (sửa mô tả: aihub info {n})")


def cmd_search(a):
    from . import fetch
    try:
        rows = fetch.search(" ".join(a.query), limit=a.limit)
    except fetch.PullError as e:
        die(str(e))
    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2)); return
    if not rows:
        print(f"Không tìm thấy gì cho '{' '.join(a.query)}'."); return
    from .fetch import preferred_format
    pref = preferred_format()
    print(f"\n{B}Kết quả trên HuggingFace{X}   (★ = hợp với máy này)\n")
    for r in rows:
        mark = f"{G}★{X}" if r.get("preferred") else (f"{C}◆{X}" if r["gguf"] or r["mlx"] else " ")
        sz = f'{r["gb"]:.2f} GB' if r["gb"] else "   ?   "
        print(f" {mark} {r['id']:<44} {sz:>9}  ⬇{r['downloads']:,}")
    print(f"\nTải:  aihub pull hf:<id>            Xem trước:  … --dry-run")
    if pref == "gguf":
        print(f"★ GGUF nạp được bằng Ollama · MLX chỉ chạy trên Apple Silicon\n")
    else:
        print(f"★ MLX chạy nhanh nhất trên Apple Silicon · ◆ GGUF dùng với Ollama\n")


def cmd_adopt(a):
    from . import fetch
    from .resolve import discover
    found = discover()
    if not found:
        print(f"{G}✓{X} không có model nào chưa khai báo."); return
    print(f"\n{B}Model có trên đĩa nhưng chưa trong registry{X}\n")
    for m in found:
        print(f"  {m.disk_gb or 0:>6.2f} GB  {B}{m.name}{X}  ({m.runtime} · {m.task})")
    if not a.apply:
        print(f"\n{Y}(xem trước){X}  Thêm vào registry: aihub adopt --apply\n"); return
    added = fetch.adopt_all()
    print()
    for n in added:
        print(f"{G}✓{X} đã thêm {n}")
    print(f"\nSửa tên/mô tả cho đẹp trong {HUB_HOME}/registry.toml\n")


def cmd_env(a):
    """In biến môi trường của hub, dán thẳng vào shell được.

    Mặc định theo shell của hệ điều hành đang chạy: in `export FOO=bar` trên
    Windows là vô dụng, mà đây chính là lệnh người ta hay copy-paste nhất.
    """
    e = R.env_dict()
    if a.json:
        print(json.dumps(e)); return

    fmt = a.format
    if not fmt:
        fmt = "ps" if plat.WINDOWS else "sh"
    for k, v in e.items():
        if fmt == "ps":
            print(f'$env:{k} = "{v}"')
        elif fmt == "cmd":
            print(f"set {k}={v}")
        else:
            print(f'export {k}="{v}"')


def cmd_serve(a):
    base = os.environ.get("AIHUB_OLLAMA_URL", "http://127.0.0.1:11434")
    import urllib.request
    try:
        urllib.request.urlopen(base + "/api/tags", timeout=2)
        print(f"{G}✓{X} Ollama đã chạy ở {base}"); return
    except Exception:
        pass
    ollama = plat.ollama_bin()
    if not ollama:
        die("không tìm thấy lệnh ollama — cài từ https://ollama.com/download")
    env = {**os.environ, **R.env_dict()}
    log = store_root() / "run" / "ollama.log"
    p = plat.spawn_detached([ollama, "serve"], env, log)
    (store_root() / "run" / "ollama.pid").write_text(str(p.pid), encoding="utf-8")
    print(f"{G}✓{X} đã bật Ollama (pid {p.pid}) · log: {log}")
    print(f"   OLLAMA_MODELS={env.get('OLLAMA_MODELS')}")


def cmd_stop(a):
    pidf = store_root() / "run" / "ollama.pid"
    pid = None
    if pidf.exists():
        try:
            pid = int(pidf.read_text(encoding="utf-8").strip())
        except ValueError:
            pass
    ok = plat.kill_ollama(pid)
    pidf.unlink(missing_ok=True)
    # Trên Windows, app Ollama chạy nền ngoài `ollama serve` cũng giữ cổng 11434;
    # taskkill /T trong plat.kill_ollama đã bao gồm nó.
    print(f"{G}✓{X} đã tắt Ollama" if ok else "Ollama không còn chạy")


def cmd_ps(a):
    import urllib.request
    base = os.environ.get("AIHUB_OLLAMA_URL", "http://127.0.0.1:11434")
    try:
        with urllib.request.urlopen(base + "/api/ps", timeout=3) as r:
            ms = json.load(r).get("models", [])
    except Exception:
        die(f"Ollama không chạy ở {base}")
    if not ms:
        print("Không model nào đang nạp — RAM trống."); return
    for m in ms:
        print(f"  {m['name']:<28} {m.get('size',0)/1e9:>5.1f} GB   "
              f"hết hạn {m.get('expires_at','?')[:19]}")


def cmd_doctor(a):
    from . import doctor
    rep = doctor.run(deep=a.deep)
    col = {"PASS": G, "WARN": Y, "FAIL": RD}
    mark = {"PASS": "✓", "WARN": "!", "FAIL": "✗"}
    print(f"\n{B}AI Hub — kiểm tra sức khoẻ{X}\n")
    for lv, name, detail in rep.rows:
        print(f" {col[lv]}{mark[lv]}{X} {name:<32} {detail}")
    print()
    if rep.failed:
        print(f"{RD}{rep.failed} LỖI{X}" + (f" · {Y}{rep.warned} cảnh báo{X}" if rep.warned else ""))
        raise SystemExit(1)
    print(f"{G}Không có lỗi{X}" + (f" · {Y}{rep.warned} cảnh báo{X}" if rep.warned else ""))


def cmd_du(a):
    store = store_root()
    print(f"\n{B}Dung lượng kho{X}  {store}\n")
    tot = 0
    for d in sorted(p for p in store.iterdir() if p.is_dir()):
        gb = plat.dir_size_bytes(d) / 1e9
        tot += gb
        if gb >= 0.01:
            print(f"  {d.name:<12} {gb:>8.2f} GB")
    print(f"  {'—'*12} {'—'*11}")
    print(f"  {'tổng':<12} {tot:>8.2f} GB")
    print(f"\n  đĩa trống    {plat.free_bytes(store)/1e9:>8.0f} GB")
    # chỉ tính model CÒN TRÊN ĐĨA — model đã xoá vẫn nằm trong registry ở
    # trạng thái "chưa tải" để tải lại được, nhưng không chiếm chỗ nữa.
    rec = [m for m in list_models(with_disk=True) if m.archive_candidate and m.status == "present"]
    if rec:
        print(f"\n{Y}Có thể dọn ({sum((m.disk_gb if m.disk_gb is not None else m.size_gb) for m in rec):.1f} GB):{X}")
        for m in rec:
            print(f"  {(m.disk_gb if m.disk_gb is not None else m.size_gb):>6.1f} GB  {m.name:<26} {m.desc[:52]}")
        print(f"\n  → xem chi tiết: aihub gc --dry-run")
    print()


def cmd_gc(a):
    rec = [m for m in list_models(with_disk=True) if m.archive_candidate and m.status == "present"]
    if a.only:
        want = set(a.only)
        unknown = want - {m.name for m in rec}
        if unknown:
            die(f"không phải ứng viên dọn dẹp: {', '.join(sorted(unknown))}")
        rec = [m for m in rec if m.name in want]
    if not rec:
        print(f"{G}✓{X} không có gì để dọn."); return
    print(f"\n{B}Ứng viên dọn dẹp{X} — tổng {sum((m.disk_gb if m.disk_gb is not None else m.size_gb) for m in rec):.1f} GB\n")
    for m in rec:
        how = (f"ollama rm {m.ref}" if m.runtime == "ollama"
               else f"xoá {m.path or '(chưa phân giải)'}")
        print(f"  {Y}{(m.disk_gb if m.disk_gb is not None else m.size_gb):>6.1f} GB{X}  {B}{m.name}{X}")
        print(f"            {m.desc}")
        print(f"            → {how}\n")
    if a.dry_run or not a.apply:
        print(f"{Y}(dry-run){X}  Muốn xoá thật: aihub gc --apply")
        return
    print(f"{RD}Sẽ xoá {len(rec)} mục.{X} Gõ XOA để xác nhận: ", end="")
    if input().strip() != "XOA":
        print("đã huỷ"); return
    for m in rec:
        if m.runtime == "ollama":
            subprocess.run([plat.ollama_bin() or "ollama", "rm", m.ref],
                           env={**os.environ, **R.env_dict()})
        elif m.path:
            p = Path(m.path)
            target = p if m.store == "whisper" else p.parents[1]  # repo dir của HF
            shutil.rmtree(target, ignore_errors=True) if target.is_dir() else p.unlink(missing_ok=True)
        print(f"{G}✓{X} đã xoá {m.name}")


def _make_link(src: str, dst: Path) -> str:
    """Liên kết dst → src, chọn loại phù hợp với hệ điều hành và với đích."""
    return (plat.link_dir(src, dst) if Path(src).is_dir()
            else plat.link_file(src, dst))


def cmd_link(a):
    """Tạo liên kết tên ổn định trong models/links/ và liên kết cho dự án.

    Trên Windows không bật Developer Mode thì symlink bị từ chối; plat tự tụt
    xuống junction (thư mục) hoặc hardlink (file). Cả hai đều trong suốt với
    công cụ đọc model, nên phía dùng không cần biết khác biệt.
    """
    links = store_dir("links"); links.mkdir(parents=True, exist_ok=True)
    n = 0
    for m in list_models(status="present"):
        exp = m.expose or {}
        if not m.path:
            continue
        targets = []
        if exp.get("link"):
            targets.append((links / exp["link"], f"links/{exp['link']}"))
        if exp.get("ct2"):
            ct2 = store_dir("ct2"); ct2.mkdir(parents=True, exist_ok=True)
            targets.append((ct2 / exp["ct2"], f"ct2/{exp['ct2']}"))
        if a.projects and exp.get("project_link"):
            targets.append((Path(exp["project_link"]), exp["project_link"]))

        for dst, label in targets:
            if dst.exists() and not plat.is_link(dst):
                print(f"{Y}!{X} bỏ qua {label} (đã tồn tại, không phải liên kết)")
                continue
            try:
                kind = _make_link(m.path, dst)
            except OSError as e:
                print(f"{RD}✗{X} {label}: {e}"); continue
            print(f"{G}✓{X} {label} → {m.path}  ({kind})"); n += 1
    print(f"\n{n} liên kết.")


def cmd_install(a):
    py = plat.venv_python(Path(a.python))
    if not py.exists():
        die(f"không thấy interpreter: {py}")
    pkg = HUB_HOME / "clients" / "python"
    print(f"Cài aihub (editable) vào {py} …")
    out = subprocess.run([str(py), "-m", "pip", "install", "-e", str(pkg)],
                         capture_output=True, text=True)
    if out.returncode:
        die(out.stderr[-800:])
    v = subprocess.run([str(py), "-c", "import aihub;print(aihub.__version__)"],
                       capture_output=True, text=True).stdout.strip()
    print(f"{G}✓{X} xong — aihub {v}")


def cmd_web(a):
    sys.path.insert(0, str(HUB_HOME / "web"))
    import server as websrv
    websrv.serve(a.port, open_browser=not a.no_open)


def _run_script(stem: str):
    """Chạy script migrate/rollback bằng shell của hệ điều hành."""
    if plat.WINDOWS:
        script = HUB_HOME / "scripts" / f"{stem}.ps1"
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
               "-File", str(script)]
    else:
        script = HUB_HOME / "scripts" / f"{stem}.sh"
        cmd = ["/bin/zsh", str(script)]
    if not script.is_file():
        die(f"không thấy {script}")
    subprocess.run(cmd, check=False)


def cmd_migrate(a):
    _run_script("migrate")


def cmd_rollback(a):
    _run_script("rollback")


# ───────────────────────────── parser ─────────────────────────────

def main(argv=None):
    p = argparse.ArgumentParser(prog="aihub", description="AI Hub — kho model AI local dùng chung")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help_):
        s = sub.add_parser(name, help=help_)
        s.set_defaults(fn=fn)
        return s

    s = add("path", cmd_path, "in đường dẫn model (không tải)");      s.add_argument("name")
    s = add("ensure", cmd_ensure, "tải nếu thiếu rồi in đường dẫn");  s.add_argument("name")
    s = add("endpoint", cmd_endpoint, "in endpoint HTTP")
    s.add_argument("name"); s.add_argument("--json", action="store_true")

    s = add("list", cmd_list, "liệt kê model")
    s.add_argument("--task"); s.add_argument("--runtime")
    s.add_argument("--status",
                   choices=["present", "missing", "cloud", "unsupported"])
    s.add_argument("--json", action="store_true")

    s = add("info", cmd_info, "chi tiết một model")
    s.add_argument("name"); s.add_argument("--json", action="store_true")

    s = add("pull", cmd_pull, "tải model từ nguồn online")
    s.add_argument("source", help="hf:org/repo · ollama:tên · gguf:org/repo/file · gh:… · url:… · hoặc tên trong registry")
    s.add_argument("--include", nargs="*"); s.add_argument("--exclude", nargs="*")
    s.add_argument("--sha256"); s.add_argument("--dry-run", action="store_true")

    s = add("adopt", cmd_adopt, "ghi model đã có trên đĩa vào registry")
    s.add_argument("--apply", action="store_true")

    s = add("search", cmd_search, "tìm model trên HuggingFace")
    s.add_argument("query", nargs="+"); s.add_argument("--limit", type=int, default=12)
    s.add_argument("--json", action="store_true")

    s = add("env", cmd_env, "in biến môi trường của hub")
    s.add_argument("--json", action="store_true")
    s.add_argument("--sh", dest="format", action="store_const", const="sh",
                   help="cú pháp POSIX (export FOO=bar)")
    s.add_argument("--ps", dest="format", action="store_const", const="ps",
                   help="cú pháp PowerShell ($env:FOO = \"bar\")")
    s.add_argument("--cmd", dest="format", action="store_const", const="cmd",
                   help="cú pháp cmd.exe (set FOO=bar)")
    s.set_defaults(format=None)

    add("serve", cmd_serve, "bật Ollama với cấu hình hub")
    add("stop", cmd_stop, "tắt Ollama")
    add("ps", cmd_ps, "model nào đang nạp RAM")

    s = add("doctor", cmd_doctor, "kiểm tra sức khoẻ"); s.add_argument("--deep", action="store_true")
    add("du", cmd_du, "báo cáo dung lượng")
    s = add("gc", cmd_gc, "dọn model thừa")
    s.add_argument("--dry-run", action="store_true"); s.add_argument("--apply", action="store_true")
    s.add_argument("--only", nargs="*", metavar="TÊN",
                   help="chỉ dọn đúng những model này (mặc định: tất cả ứng viên)")

    s = add("link", cmd_link, "tạo symlink tên ổn định")
    s.add_argument("--projects", action="store_true", help="tạo cả symlink trong thư mục dự án")

    s = add("install", cmd_install, "cài client aihub vào venv dự án")
    s.add_argument("--python", required=True, help="đường dẫn venv hoặc interpreter")

    s = add("web", cmd_web, "mở dashboard web")
    s.add_argument("--port", type=int, default=7860); s.add_argument("--no-open", action="store_true")

    add("migrate", cmd_migrate, "chuyển cache mặc định vào hub")
    add("rollback", cmd_rollback, "hoàn tác migrate")

    a = p.parse_args(argv)
    try:
        a.fn(a)
    except KeyboardInterrupt:
        print("\nđã huỷ", file=sys.stderr); raise SystemExit(130)
    return 0


if __name__ == "__main__":
    main()
