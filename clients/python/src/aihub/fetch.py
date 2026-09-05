"""Tải model từ nguồn online về kho hub.

Cú pháp nguồn:
    ollama:qwen3.5:9b                          → models/ollama/
    hf:mlx-community/whisper-large-v3-turbo    → models/hf/hub/
    gguf:bartowski/Qwen3-8B-GGUF/xxx-Q4.gguf   → models/custom/gguf/
    gh:owner/repo@v1.0/model.onnx              → models/custom/
    url:https://…                              → models/custom/
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from .resolve import HUB_HOME, load_registry, store_dir, store_root

MIN_FREE_GB = 20.0


class PullError(RuntimeError):
    pass


def free_gb() -> float:
    st = os.statvfs(store_root())
    return st.f_bavail * st.f_frsize / 1e9


def _check_space(need_gb: float) -> None:
    free = free_gb()
    if free - need_gb < MIN_FREE_GB:
        raise PullError(
            f"Không đủ chỗ: cần {need_gb:.1f} GB, còn trống {free:.1f} GB, "
            f"ngưỡng an toàn {MIN_FREE_GB:.0f} GB. Chạy `aihub gc` để dọn."
        )


# ───────────────────────────── HuggingFace ─────────────────────────────

def _hf_api():
    try:
        from huggingface_hub import HfApi
    except ImportError:
        raise PullError(
            "Thiếu huggingface_hub. Cài: "
            f"{HUB_HOME}/.venv/bin/pip install huggingface_hub"
        )
    return HfApi()


def hf_preview(repo: str, revision: str = "main",
               include: list[str] | None = None,
               exclude: list[str] | None = None) -> dict:
    """Liệt kê file + tổng dung lượng TRƯỚC khi tải."""
    import fnmatch
    api = _hf_api()
    info = api.repo_info(repo, revision=revision, files_metadata=True)
    files = []
    for sib in info.siblings or []:
        name = sib.rfilename
        if include and not any(fnmatch.fnmatch(name, p) for p in include):
            continue
        if exclude and any(fnmatch.fnmatch(name, p) for p in exclude):
            continue
        files.append({"name": name, "size": sib.size or 0})
    total = sum(f["size"] for f in files)
    return {"repo": repo, "revision": revision, "files": files,
            "count": len(files), "total_gb": total / 1e9}


def hf_pull(repo: str, revision: str = "main",
            include: list[str] | None = None,
            exclude: list[str] | None = None,
            dry_run: bool = False) -> Path | dict:
    prev = hf_preview(repo, revision, include, exclude)
    if dry_run:
        return prev
    _check_space(prev["total_gb"])
    from huggingface_hub import snapshot_download
    os.environ.setdefault("HF_HOME", str(store_dir("hf")))
    p = snapshot_download(
        repo_id=repo, revision=revision,
        allow_patterns=include, ignore_patterns=exclude,
    )
    return Path(p)


def gguf_pull(repo: str, filename: str, dry_run: bool = False) -> Path | dict:
    """Tải đúng MỘT file .gguf — tránh kéo cả repo nhiều bản lượng tử hoá."""
    prev = hf_preview(repo, include=[filename])
    if not prev["files"]:
        raise PullError(f"Không thấy '{filename}' trong {repo}")
    if dry_run:
        return prev
    _check_space(prev["total_gb"])
    from huggingface_hub import hf_hub_download
    dest = store_dir("custom") / "gguf"
    dest.mkdir(parents=True, exist_ok=True)
    p = hf_hub_download(repo_id=repo, filename=filename, local_dir=str(dest))
    return Path(p)


# ─────────────────────────────── Ollama ────────────────────────────────

def ollama_pull(ref: str, dry_run: bool = False):
    url = os.environ.get("AIHUB_OLLAMA_URL", "http://127.0.0.1:11434")
    if dry_run:
        return {"repo": ref, "files": [], "count": 1, "total_gb": 0.0,
                "note": "Ollama không báo dung lượng trước khi tải"}
    req = urllib.request.Request(
        url + "/api/pull",
        data=json.dumps({"model": ref, "stream": True}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req) as resp:
            for raw in resp:
                if not raw.strip():
                    continue
                msg = json.loads(raw)
                if msg.get("error"):
                    raise PullError(msg["error"])
                yield msg
    except urllib.error.URLError as e:
        raise PullError(
            f"Không kết nối được Ollama ở {url}. Chạy `aihub serve` trước. ({e})"
        )


# ──────────────────────────── URL / GitHub ─────────────────────────────

def url_pull(url: str, dest_name: str | None = None,
             sha256: str | None = None, dry_run: bool = False):
    dest_dir = store_dir("custom")
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = dest_name or url.rstrip("/").split("/")[-1]
    dest = dest_dir / name

    req = urllib.request.Request(url, method="HEAD")
    try:
        with urllib.request.urlopen(req) as r:
            size = int(r.headers.get("Content-Length") or 0)
    except Exception:
        size = 0
    if dry_run:
        return {"repo": url, "files": [{"name": name, "size": size}],
                "count": 1, "total_gb": size / 1e9}
    _check_space(size / 1e9)

    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, tmp.open("wb") as fh:
        shutil.copyfileobj(r, fh)

    if sha256:
        h = hashlib.sha256()
        with tmp.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() != sha256:
            tmp.unlink()
            raise PullError(f"sha256 không khớp: {h.hexdigest()} != {sha256}")
    tmp.rename(dest)
    return dest


def gh_pull(spec: str, dry_run: bool = False):
    """owner/repo@tag/asset.bin → release asset."""
    m = re.match(r"^([^/]+)/([^@]+)@([^/]+)/(.+)$", spec)
    if not m:
        raise PullError("Cú pháp: gh:owner/repo@tag/tên-file")
    owner, repo, tag, asset = m.groups()
    url = f"https://github.com/{owner}/{repo}/releases/download/{tag}/{asset}"
    return url_pull(url, dest_name=asset, dry_run=dry_run)


# ─────────────────────────── điều phối chung ───────────────────────────

SHELL_PREFIXES = {
    "gh repo clone ": "gh-clone", "git clone ": "git-clone",
    "hf download ": "hf", "huggingface-cli download ": "hf",
    "ollama pull ": "ollama", "ollama run ": "ollama",
    "aihub pull ": "recurse",
}


def normalize_source(spec: str) -> str:
    """Chuẩn hoá thứ người dùng dán vào thành một source spec hợp lệ.

    Người ta hay dán nguyên lệnh shell chép từ trang GitHub/HuggingFace, hoặc dán
    URL. Chấp nhận hết, và báo lỗi cụ thể khi thứ họ dán về bản chất không phải
    trọng số model.
    """
    s = " ".join(spec.strip().split())
    low = s.lower()

    for pref, kind in SHELL_PREFIXES.items():
        if low.startswith(pref):
            arg = s[len(pref):].strip().strip("\"'")
            if kind in ("gh-clone", "git-clone"):
                raise PullError(_code_repo_msg(arg))
            if kind == "recurse":
                return normalize_source(arg)
            return f"{kind}:{arg}"

    # URL dán thẳng
    for host, scheme in (("huggingface.co/", "hf"), ("hf.co/", "hf")):
        if host in low:
            path = s.split(host, 1)[1].strip("/")
            path = path.split("?")[0].split("#")[0]
            parts = path.split("/")
            if len(parts) >= 2 and parts[0] in ("models", "datasets"):
                parts = parts[1:]
            if len(parts) >= 4 and parts[2] in ("blob", "resolve"):
                return f"gguf:{parts[0]}/{parts[1]}/{'/'.join(parts[4:])}" \
                       if parts[-1].endswith(".gguf") else f"{scheme}:{parts[0]}/{parts[1]}"
            if len(parts) >= 2:
                return f"{scheme}:{parts[0]}/{parts[1]}"

    if "github.com/" in low:
        path = s.split("github.com/", 1)[1].strip("/")
        if "/releases/download/" in path:
            owner_repo, rest = path.split("/releases/download/", 1)
            tag, _, asset = rest.partition("/")
            return f"gh:{owner_repo}@{tag}/{asset}"
        raise PullError(_code_repo_msg("/".join(path.split("/")[:2])))

    return s


def _code_repo_msg(repo: str) -> str:
    repo = repo.rstrip("/").removesuffix(".git")
    if "github.com/" in repo:
        repo = repo.split("github.com/", 1)[1]
    name = repo.split("/")[-1]
    return (
        f"'{repo}' trên GitHub là MÃ NGUỒN, không phải trọng số model.\n"
        f"AI Hub là kho trọng số — clone code về đây không dùng được.\n\n"
        f"Trọng số hầu như luôn nằm trên HuggingFace. Tìm bằng:\n"
        f"    aihub search {name}\n\n"
        f"Rồi tải bản phù hợp, ví dụ:  aihub pull hf:<org>/<repo>\n"
        f"Còn mã nguồn thì cứ `git clone` vào thư mục dự án như bình thường."
    )


def parse_source(spec: str) -> tuple[str, str]:
    spec = normalize_source(spec)
    if ":" not in spec:
        return "registry", spec
    scheme, rest = spec.split(":", 1)
    if scheme not in ("ollama", "hf", "gguf", "gh", "url", "git"):
        return "registry", spec
    return scheme, rest


def search(query: str, limit: int = 12) -> list[dict]:
    """Tìm trọng số model trên HuggingFace theo tên."""
    api = _hf_api()
    out = []
    for m in api.list_models(search=query, limit=limit, sort="downloads"):
        try:
            info = api.model_info(m.id, files_metadata=True)
            size = sum(s.size or 0 for s in (info.siblings or []))
        except Exception:
            size = 0
        mid = m.id.lower()
        out.append({
            "id": m.id,
            "gb": round(size / 1e9, 2),
            "downloads": getattr(m, "downloads", 0) or 0,
            "mlx": "mlx" in mid,          # tối ưu Apple Silicon
            "gguf": "gguf" in mid,
            "spec": f"hf:{m.id}",
        })
    return out


def pull(spec: str, include=None, exclude=None, dry_run=False, sha256=None):
    """Điểm vào chính. Trả về Path, dict (dry-run), hoặc generator (ollama)."""
    scheme, rest = parse_source(spec)

    if scheme == "registry":
        return pull_registered(rest, dry_run=dry_run)
    if scheme == "ollama":
        return ollama_pull(rest, dry_run=dry_run)
    if scheme == "hf":
        return hf_pull(rest, include=include, exclude=exclude, dry_run=dry_run)
    if scheme == "gguf":
        parts = rest.split("/")
        if len(parts) < 3:
            raise PullError("Cú pháp: gguf:org/repo/tên-file.gguf")
        return gguf_pull("/".join(parts[:2]), "/".join(parts[2:]), dry_run=dry_run)
    if scheme == "gh":
        return gh_pull(rest, dry_run=dry_run)
    if scheme == "url":
        return url_pull(rest, sha256=sha256, dry_run=dry_run)
    if scheme == "git":
        if not shutil.which("git-lfs"):
            raise PullError("Cần git-lfs. Cài: brew install git-lfs && git lfs install")
        dest = store_dir("custom") / rest.rstrip("/").split("/")[-1].replace(".git", "")
        if dry_run:
            return {"repo": rest, "files": [], "count": 0, "total_gb": 0.0}
        subprocess.run(["git", "clone", "--depth", "1", rest, str(dest)], check=True)
        return dest
    raise PullError(f"Nguồn không hỗ trợ: {scheme}")


def pull_registered(name: str, dry_run: bool = False):
    """Tải một model đã khai báo trong registry."""
    from .resolve import _lookup
    key, spec = _lookup(name)
    st, src = spec.get("store"), spec.get("source", {})

    if spec.get("runtime") == "ollama":
        return ollama_pull(spec["ref"], dry_run=dry_run)
    if st == "hf" and src.get("repo"):
        return hf_pull(src["repo"], src.get("revision", "main"), dry_run=dry_run)
    if st == "whisper":
        try:
            import whisper as _w
            url = _w._MODELS[spec["file"].removesuffix(".pt")]
        except Exception:
            raise PullError(
                f"'{key}' cần openai-whisper để tải. "
                f"Hoặc tải tay vào {store_dir('whisper')}"
            )
        return url_pull(url, dest_name=spec["file"], dry_run=dry_run)
    raise PullError(f"Không biết cách tải '{key}' (store={st})")


# ─────────────────── ghi entry mới vào registry.toml ───────────────────

def _toml_str(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def append_registry(name: str, **fields) -> bool:
    """Thêm một [models.<name>] vào cuối registry.toml. Bỏ qua nếu đã có."""
    reg_path = HUB_HOME / "registry.toml"
    if name in load_registry(refresh=True).get("models", {}):
        return False
    lines = ["", f"[models.{name}]"]
    nested = {}
    for k, v in fields.items():
        if isinstance(v, dict):
            nested[k] = v
        elif isinstance(v, bool):
            lines.append(f"{k} = {str(v).lower()}")
        elif isinstance(v, (int, float)):
            lines.append(f"{k} = {v}")
        elif isinstance(v, list):
            lines.append(f"{k} = [" + ", ".join(_toml_str(x) for x in v) + "]")
        else:
            lines.append(f"{k} = {_toml_str(v)}")
    for section, body in nested.items():
        lines.append(f"[models.{name}.{section}]")
        for k, v in body.items():
            lines.append(f"{k} = {_toml_str(v)}")
    with reg_path.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    load_registry(refresh=True)
    return True


# ═════════════ ghi model đã có trên đĩa vào registry.toml ═════════════

_TASK_VI = {
    "tts": "tổng hợp giọng nói", "asr": "nhận dạng giọng nói",
    "chat": "trò chuyện / sinh văn bản", "code": "lập trình",
    "vision": "hiểu hình ảnh", "image": "sinh ảnh", "embed": "vector hoá văn bản",
}


def _est_ram_gb(disk_gb: float, runtime: str) -> float:
    """Ước tính RAM cần từ dung lượng đĩa. Chỉ là ước tính — `aihub ps` mới là số thật."""
    if not disk_gb:
        return 0.0
    overhead = 1.15 if runtime in ("gguf", "ollama", "mlx") else 1.3
    return round(disk_gb * overhead + 0.4, 1)


def register_discovered(mi, **overrides) -> bool:
    """Đưa một model đã có trên đĩa vào registry.toml.

    Metadata lấy từ README đã cache (offline); nếu có mạng thì bổ sung thêm từ
    HuggingFace. Người dùng sửa lại title/desc sau cũng được — registry là file
    text bình thường.
    """
    from .resolve import _PIPELINE_TASK

    task = mi.task if mi.task != "khác" else "khác"
    tags = list(mi.tags)
    desc = mi.desc

    if mi.source.get("repo"):
        try:                                  # bổ sung từ HF nếu online
            info = _hf_api().model_info(mi.source["repo"])
            if info.pipeline_tag:
                task = _PIPELINE_TASK.get(info.pipeline_tag, task)
            for t in (info.tags or []):
                if t not in tags and ":" not in t and len(tags) < 6 \
                        and t not in ("safetensors", "transformers", "region"):
                    tags.append(t)
        except Exception:
            pass                              # offline vẫn ghi được

    if not desc:
        what = _TASK_VI.get(task, "chưa rõ tác vụ")
        src = mi.source.get("repo") or mi.ref or mi.file or ""
        desc = f"Tự nhận diện từ đĩa ({what}). Nguồn: {src}. Sửa mô tả này trong registry.toml."

    fields = dict(
        title=mi.title, runtime=mi.runtime, store=mi.store,
        access=mi.access, task=task,
        size_gb=round(mi.disk_gb or 0.0, 2),
        ram_gb=_est_ram_gb(mi.disk_gb or 0.0, mi.runtime),
        tags=tags[:6], desc=desc, owners=[],
    )
    if mi.ref:
        fields["ref"] = mi.ref
    if mi.file:
        fields["file"] = mi.file
    if mi.source:
        fields["source"] = mi.source
    fields.update(overrides)
    return append_registry(mi.name, **fields)


def adopt_all() -> list[str]:
    """Ghi mọi model chưa khai báo vào registry. Trả về tên đã thêm."""
    from .resolve import discover
    added = []
    for mi in discover():
        if register_discovered(mi):
            added.append(mi.name)
    return added
