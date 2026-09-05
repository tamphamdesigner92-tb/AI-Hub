"""CLI của AI Hub — dùng được từ mọi ngôn ngữ và từ terminal."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import resolve as R
from .resolve import HUB_HOME, get, list_models, load_registry, store_dir, store_root

G, Y, RD, C, B, X = "\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[1m", "\033[0m"
if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
    G = Y = RD = C = B = X = ""

BADGE = {"present": f"{G}●{X} có sẵn", "missing": f"{Y}○{X} chưa tải",
         "cloud": f"{C}☁{X} cloud", "partial": f"{Y}◐{X} thiếu file"}


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
    print(f"\n{B}Kết quả trên HuggingFace{X}   (★ = tối ưu Apple Silicon)\n")
    for r in rows:
        mark = f"{G}★{X}" if r["mlx"] else (f"{C}◆{X}" if r["gguf"] else " ")
        sz = f'{r["gb"]:.2f} GB' if r["gb"] else "   ?   "
        print(f" {mark} {r['id']:<44} {sz:>9}  ⬇{r['downloads']:,}")
    print(f"\nTải:  aihub pull hf:<id>            Xem trước:  … --dry-run")
    print(f"★ MLX chạy nhanh nhất trên M1 Pro · ◆ GGUF dùng được với Ollama\n")


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
    e = R.env_dict()
    if a.json:
        print(json.dumps(e))
    else:
        for k, v in e.items():
            print(f"export {k}={v}")


def cmd_serve(a):
    base = os.environ.get("AIHUB_OLLAMA_URL", "http://127.0.0.1:11434")
    import urllib.request
    try:
        urllib.request.urlopen(base + "/api/tags", timeout=2)
        print(f"{G}✓{X} Ollama đã chạy ở {base}"); return
    except Exception:
        pass
    ollama = shutil.which("ollama") or "/usr/local/bin/ollama"
    if not Path(ollama).exists():
        die("không tìm thấy lệnh ollama")
    env = {**os.environ, **R.env_dict()}
    log = store_root() / "run" / "ollama.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a") as fh:
        p = subprocess.Popen([ollama, "serve"], env=env, stdout=fh, stderr=fh,
                             start_new_session=True)
    (store_root() / "run" / "ollama.pid").write_text(str(p.pid))
    print(f"{G}✓{X} đã bật Ollama (pid {p.pid}) · log: {log}")
    print(f"   OLLAMA_MODELS={env.get('OLLAMA_MODELS')}")


def cmd_stop(a):
    pidf = store_root() / "run" / "ollama.pid"
    if pidf.exists():
        try:
            os.kill(int(pidf.read_text()), 15)
            print(f"{G}✓{X} đã tắt Ollama")
        except ProcessLookupError:
            print("Ollama không còn chạy")
        pidf.unlink(missing_ok=True)
    else:
        subprocess.run(["pkill", "-x", "ollama"])
        print("đã gửi tín hiệu tắt")


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
    for sub in sorted(p for p in store.iterdir() if p.is_dir()):
        out = subprocess.run(["du", "-sk", str(sub)], capture_output=True, text=True)
        kb = int(out.stdout.split()[0]) if out.stdout.strip() else 0
        gb = kb / 1e6
        tot += gb
        if gb >= 0.01:
            print(f"  {sub.name:<12} {gb:>8.2f} GB")
    print(f"  {'—'*12} {'—'*11}")
    print(f"  {'tổng':<12} {tot:>8.2f} GB")
    st = os.statvfs(store)
    print(f"\n  đĩa trống    {st.f_bavail*st.f_frsize/1e9:>8.0f} GB")
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
            subprocess.run([shutil.which("ollama") or "/usr/local/bin/ollama",
                            "rm", m.ref], env={**os.environ, **R.env_dict()})
        elif m.path:
            p = Path(m.path)
            target = p if m.store == "whisper" else p.parents[1]  # repo dir của HF
            shutil.rmtree(target, ignore_errors=True) if target.is_dir() else p.unlink(missing_ok=True)
        print(f"{G}✓{X} đã xoá {m.name}")


def cmd_link(a):
    """Tạo symlink tên ổn định trong models/links/ và symlink cho dự án."""
    links = store_dir("links"); links.mkdir(parents=True, exist_ok=True)
    n = 0
    for m in list_models(status="present"):
        exp = m.expose or {}
        if exp.get("link") and m.path:
            dst = links / exp["link"]
            if dst.is_symlink():
                dst.unlink()
            dst.symlink_to(m.path)
            print(f"{G}✓{X} links/{exp['link']} → {m.path}"); n += 1
        if exp.get("ct2") and m.path:
            ct2 = store_dir("ct2"); ct2.mkdir(parents=True, exist_ok=True)
            dst = ct2 / exp["ct2"]
            if dst.is_symlink():
                dst.unlink()
            dst.symlink_to(m.path)
            print(f"{G}✓{X} ct2/{exp['ct2']} → {m.path}"); n += 1
        if a.projects and exp.get("project_link") and m.path:
            dst = Path(exp["project_link"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            if dst.is_symlink():
                dst.unlink()
            elif dst.exists():
                print(f"{Y}!{X} bỏ qua {dst} (đã tồn tại, không phải symlink)"); continue
            dst.symlink_to(m.path)
            print(f"{G}✓{X} {dst} → {m.path}"); n += 1
    print(f"\n{n} symlink.")


def cmd_install(a):
    venv = Path(a.python).expanduser()
    py = venv if venv.name.startswith("python") else venv / "bin" / "python"
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


def cmd_migrate(a):
    subprocess.run(["/bin/zsh", str(HUB_HOME / "scripts" / "migrate.sh")], check=False)


def cmd_rollback(a):
    subprocess.run(["/bin/zsh", str(HUB_HOME / "scripts" / "rollback.sh")], check=False)


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
    s.add_argument("--status", choices=["present", "missing", "cloud"])
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

    s = add("env", cmd_env, "in biến môi trường của hub"); s.add_argument("--json", action="store_true")

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
