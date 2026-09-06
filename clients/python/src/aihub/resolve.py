"""Phân giải model từ registry.toml ra đường dẫn thật trên đĩa."""
from __future__ import annotations

import json
import re
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import plat

HUB_HOME = plat.hub_root()
REGISTRY = HUB_HOME / "registry.toml"


class ModelNotFound(KeyError):
    """Tên model không có trong registry."""


class ModelNotAvailable(FileNotFoundError):
    """Model có trong registry nhưng chưa tải về đĩa."""


@dataclass
class ModelInfo:
    name: str
    title: str
    runtime: str
    task: str
    store: str
    access: list[str]
    size_gb: float
    ram_gb: float
    tags: list[str]
    desc: str
    strengths: list[str]
    owners: list[str]
    quant: str | None = None
    ref: str | None = None
    file: str | None = None
    aliases: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)   # rỗng = chạy mọi nơi
    source: dict = field(default_factory=dict)
    expose: dict = field(default_factory=dict)
    local: bool = True
    recommended: bool = False
    archive_candidate: bool = False
    # tính lúc chạy
    status: str = "unknown"        # present | missing | cloud | partial | unsupported
    path: str | None = None
    disk_gb: float | None = None
    undeclared: bool = False       # có trên đĩa nhưng chưa khai trong registry.toml


# ─────────────────────────── registry ───────────────────────────

_cache: dict | None = None


def load_registry(refresh: bool = False) -> dict:
    global _cache
    if _cache is None or refresh:
        if not REGISTRY.exists():
            raise FileNotFoundError(f"Không thấy registry: {REGISTRY}")
        with REGISTRY.open("rb") as fh:
            _cache = tomllib.load(fh)
    return _cache


def store_root() -> Path:
    return Path(os.environ.get("AIHUB_STORE", str(HUB_HOME / "models")))


def store_dir(kind: str) -> Path:
    reg = load_registry()
    sub = reg.get("stores", {}).get(kind, {}).get("path", kind)
    return store_root() / sub


def hf_home() -> Path:
    """Thư mục HF_HOME mà hub muốn dùng."""
    return Path(os.environ.get("HF_HOME") or store_dir("hf"))


def hf_hub_cache() -> Path:
    """Nơi huggingface_hub cất repo đã tải (`<HF_HOME>/hub`).

    Mọi chỗ đọc VÀ ghi cache HF đều phải đi qua đây. Trước kia mỗi nơi tự ghép
    `HF_HOME/hub` một kiểu, còn `hf_pull` thì trông chờ vào việc đặt biến môi
    trường — mà huggingface_hub đã chốt đường dẫn cache ngay lúc import, nên đặt
    biến sau đó không có tác dụng: model tải về rơi vào cache mặc định của người
    dùng thay vì kho hub, và hub không nhìn thấy nó.
    """
    env = os.environ.get("HF_HUB_CACHE")
    return Path(env) if env else hf_home() / "hub"


def _lookup(name: str) -> tuple[str, dict]:
    """Tra theo tên chính hoặc alias."""
    models = load_registry().get("models", {})
    if name in models:
        return name, models[name]
    for key, spec in models.items():
        if name in spec.get("aliases", []) or name == spec.get("ref"):
            return key, spec
    # Chuỗi dạng "org/repo" gần như chắc chắn là repo HuggingFace người dùng
    # muốn tải, chứ không phải tên trong registry — nói thẳng thay vì báo cụt.
    if name.count("/") == 1 and " " not in name:
        raise ModelNotFound(
            f"'{name}' không có trong registry.\n"
            f"Nếu đây là repo HuggingFace, thêm tiền tố hf: →  aihub pull hf:{name}\n"
            f"Không chắc tên đúng?  aihub search {name.split('/')[-1]}"
        )
    raise ModelNotFound(
        f"Không có model '{name}' trong registry.\n"
        f"Xem đang có gì:  aihub list\n"
        f"Tìm trên HuggingFace:  aihub search <tên>"
    )


# ─────────────────────── phân giải đường dẫn ───────────────────────

def _hf_snapshot(repo: str, revision: str = "main") -> Path | None:
    """$HF_HOME/hub/models--org--repo/refs/<rev> → sha → snapshots/<sha>.

    Đường dẫn snapshot chứa commit SHA và đổi mỗi lần tải lại, nên phải đi qua
    refs/ chứ không hardcode. Thiếu refs thì lấy snapshot mới nhất.
    """
    hub = hf_hub_cache()
    base = hub / ("models--" + repo.replace("/", "--"))
    snaps = base / "snapshots"
    if not snaps.is_dir():
        return None
    ref = base / "refs" / revision
    if ref.is_file():
        sha = ref.read_text(encoding="utf-8").strip()
        cand = snaps / sha
        if cand.is_dir():
            return cand
    subs = [p for p in snaps.iterdir() if p.is_dir()]
    if not subs:
        return None
    return max(subs, key=lambda p: p.stat().st_mtime)


def resolve_path(name: str) -> Path:
    """Đường dẫn thật của model. KHÔNG tải — dùng ensure() nếu muốn tải."""
    key, spec = _lookup(name)
    if "path" not in spec.get("access", []):
        raise ModelNotAvailable(
            f"'{key}' chỉ dùng qua endpoint (runtime={spec.get('runtime')}). "
            f"Dùng aihub.endpoint('{key}')."
        )

    st = spec.get("store")
    if st == "hf":
        repo = spec.get("source", {}).get("repo")
        if not repo:
            raise ModelNotAvailable(f"'{key}' thiếu source.repo trong registry")
        p = _hf_snapshot(repo, spec.get("source", {}).get("revision", "main"))
        if p is None:
            raise ModelNotAvailable(f"'{key}' chưa tải. Chạy: aihub pull {key}")
        return p

    if st == "whisper":
        p = Path(os.environ.get("AIHUB_WHISPER_DIR", str(store_dir("whisper"))))
        p = p / spec["file"]
        if not p.is_file():
            raise ModelNotAvailable(f"'{key}' chưa tải. Chạy: aihub pull {key}")
        return p

    if st in ("custom", "ct2"):
        p = store_dir(st) / (spec.get("file") or key)
        if not p.exists():
            raise ModelNotAvailable(f"'{key}' chưa tải. Chạy: aihub pull {key}")
        return p

    raise ModelNotAvailable(f"Không biết cách phân giải store '{st}' cho '{key}'")


def whisper_root() -> Path:
    """Thư mục cho openai-whisper download_root=."""
    return Path(os.environ.get("AIHUB_WHISPER_DIR", str(store_dir("whisper"))))


# ─────────────────────────── endpoint ───────────────────────────

@dataclass
class Endpoint:
    base: str
    openai: str
    model: str
    api_key: str = "ollama"

    def __iter__(self):
        return iter((self.openai, self.model))


def resolve_endpoint(name: str) -> Endpoint:
    key, spec = _lookup(name)
    if "endpoint" not in spec.get("access", []):
        raise ModelNotAvailable(
            f"'{key}' chỉ dùng qua đường dẫn file. Dùng aihub.path('{key}')."
        )
    eps = load_registry().get("endpoints", {})
    ep = eps.get("ollama" if spec.get("runtime") == "ollama" else spec["runtime"], {})
    base = os.environ.get("AIHUB_OLLAMA_URL", ep.get("base", "http://127.0.0.1:11434"))
    return Endpoint(
        base=base,
        openai=ep.get("openai", base.rstrip("/") + "/v1"),
        model=spec.get("ref", key),
        api_key=ep.get("api_key", "ollama"),
    )


# ─────────────────────── trạng thái & liệt kê ───────────────────────

def _du_gb(p: Path) -> float:
    return plat.dir_size_bytes(p) / 1e9


def _ollama_manifest(ref: str) -> Path:
    root = Path(os.environ.get("OLLAMA_MODELS", str(store_dir("ollama"))))
    repo, tag = ref.rsplit(":", 1) if ":" in ref else (ref, "latest")
    if "/" not in repo:
        repo = "library/" + repo
    return root / "manifests" / "registry.ollama.ai" / repo / tag


def _ollama_present(ref: str) -> bool:
    return _ollama_manifest(ref).is_file()


def _ollama_du_gb(ref: str) -> float | None:
    """Dung lượng thật: cộng kích thước blob thực có trên đĩa theo manifest.

    Blob dùng chung giữa các model được tính vào cả hai — giống cách `ollama list`
    báo, vì đó là dung lượng model cần chứ không phải phần riêng của nó.
    """
    man = _ollama_manifest(ref)
    if not man.is_file():
        return None
    try:
        d = json.loads(man.read_text(encoding="utf-8"))
    except Exception:
        return None
    blobs = Path(os.environ.get("OLLAMA_MODELS", str(store_dir("ollama")))) / "blobs"
    total = 0
    for layer in (d.get("layers") or []) + [d.get("config") or {}]:
        if not isinstance(layer, dict) or not layer.get("digest"):
            continue
        bp = blobs / layer["digest"].replace(":", "-")
        if bp.is_file():
            total += bp.stat().st_size
    return total / 1e9


def get(name: str, with_disk: bool = False) -> ModelInfo:
    key, spec = _lookup(name)
    mi = ModelInfo(
        name=key,
        title=spec.get("title", key),
        runtime=spec.get("runtime", "?"),
        task=spec.get("task", "?"),
        store=spec.get("store", "?"),
        access=spec.get("access", []),
        size_gb=float(spec.get("size_gb", 0.0)),
        ram_gb=float(spec.get("ram_gb", 0.0)),
        tags=spec.get("tags", []),
        desc=spec.get("desc", ""),
        strengths=spec.get("strengths", []),
        owners=spec.get("owners", []),
        quant=spec.get("quant"),
        ref=spec.get("ref"),
        file=spec.get("file"),
        aliases=spec.get("aliases", []),
        platforms=spec.get("platforms", []),
        source=spec.get("source", {}),
        expose=spec.get("expose", {}),
        local=spec.get("local", True),
        recommended=bool(spec.get("recommended", False)),
        archive_candidate=bool(spec.get("archive_candidate", False)),
    )

    if not mi.local:
        mi.status = "cloud"
        return mi

    # Runtime bó vào một hệ điều hành (MLX chỉ có trên Apple Silicon). Báo thẳng
    # thay vì để nó hiện "chưa tải" — tải về cũng không chạy được.
    if mi.platforms and plat.PLATFORM not in mi.platforms:
        mi.status = "unsupported"
        return mi

    if mi.runtime == "ollama":
        ref = mi.ref or key
        mi.status = "present" if _ollama_present(ref) else "missing"
        if mi.status == "present" and with_disk:
            g = _ollama_du_gb(ref)
            if g is not None:
                mi.disk_gb = round(g, 2)
        return mi

    try:
        p = resolve_path(key)
        mi.path = str(p)
        mi.status = "present"
        if with_disk:
            mi.disk_gb = round(_du_gb(p), 2)
    except (ModelNotAvailable, ModelNotFound):
        mi.status = "missing"
    return mi


def list_models(task: str | None = None, runtime: str | None = None,
                status: str | None = None, with_disk: bool = False,
                include_undeclared: bool = True) -> list[ModelInfo]:
    """Model trong registry, cộng thêm thứ có thật trên đĩa mà chưa khai báo.

    include_undeclared mặc định True: danh sách phải phản ánh ĐĨA, không chỉ
    phản ánh file cấu hình — nếu không, model tải bằng đường khác sẽ vô hình.
    """
    out = []
    entries = [(k, None) for k in load_registry().get("models", {})]
    if include_undeclared:
        entries += [(m.name, m) for m in discover()]
    for key, pre in entries:
        mi = pre if pre is not None else get(key, with_disk=with_disk)
        if task and mi.task != task:
            continue
        if runtime and mi.runtime != runtime:
            continue
        if status and mi.status != status:
            continue
        out.append(mi)
    out.sort(key=lambda m: (not m.recommended, m.undeclared, m.task, m.name))
    return out


def env_dict() -> dict[str, str]:
    """Biến môi trường của hub — để truyền cho subprocess / Electron."""
    envfile = HUB_HOME / "env" / "aihub.env"
    out: dict[str, str] = {}
    if envfile.is_file():
        for line in envfile.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                # Giá trị có thể ghi %USERPROFILE% / $HOME để file chép được
                # giữa các máy; mở ra trước khi truyền cho tiến trình con.
                out[k] = os.path.expandvars(v)
    return out


# ═══════════════ phát hiện model có trên đĩa nhưng chưa khai báo ═══════════════

_PIPELINE_TASK = {
    "text-to-speech": "tts", "text-to-audio": "tts",
    "automatic-speech-recognition": "asr",
    "text-generation": "chat", "text2text-generation": "chat",
    "image-text-to-text": "vision", "visual-question-answering": "vision",
    "text-to-image": "image", "feature-extraction": "embed",
    "sentence-similarity": "embed",
}


def _readme_meta(snap: Path) -> dict:
    """Đọc YAML front-matter trong README.md đã cache — offline, không cần mạng.

    Chỉ xử lý đúng phần cần: khoá scalar và danh sách `- item`. Thụt lề của mục
    danh sách trong README trên HuggingFace không thống nhất (0 hoặc 2 dấu cách),
    nên chấp nhận cả hai.
    """
    rd = snap / "README.md"
    if not rd.is_file():
        return {}
    try:
        txt = rd.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    if not txt.startswith("---"):
        return {}
    parts = txt.split("---", 2)
    if len(parts) < 3:
        return {}

    meta: dict = {}
    cur_key: str | None = None
    for line in parts[1].splitlines():
        if not line.strip():
            continue
        m = re.match(r"^\s*-\s+(.*)$", line)
        if m and cur_key:
            meta.setdefault(cur_key, []).append(m.group(1).strip().strip("'\""))
            continue
        m = re.match(r"^([A-Za-z_][\w-]*)\s*:\s*(.*)$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip().strip("'\"")
        if val:
            meta[key] = val
            cur_key = None
        else:
            cur_key = key          # khoá mở đầu một danh sách
    return meta


def _guess_runtime(snap: Path, repo: str) -> str:
    names = [p.name.lower() for p in snap.iterdir()] if snap.is_dir() else []
    if any(n.endswith(".gguf") for n in names):
        return "gguf"
    if repo.lower().startswith("mlx-community/") or "-mlx" in repo.lower():
        return "mlx"
    if "model.bin" in names and ("vocabulary.json" in names or "vocabulary.txt" in names):
        return "faster-whisper"
    if any(n.endswith(".onnx") for n in names):
        return "onnx"
    return "hf-transformers"


def _slug(text: str) -> str:
    out = "".join(c if c.isalnum() else "-" for c in text.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


def discover() -> list[ModelInfo]:
    """Quét đĩa tìm model CHƯA có trong registry.toml.

    Không có bước này thì bất cứ thứ gì tải bằng đường khác (dự án tự tải,
    `ollama pull` trực tiếp, `aihub pull` bản cũ) đều vô hình trên dashboard.
    """
    reg = load_registry(refresh=True)
    models = reg.get("models", {})
    claimed_repo = {m.get("source", {}).get("repo", "").lower()
                    for m in models.values() if m.get("source")}
    claimed_ref = {str(m.get("ref", "")).lower() for m in models.values()}
    claimed_file = {str(m.get("file", "")) for m in models.values()}
    known_names = set(models)

    found: list[ModelInfo] = []

    # ── HuggingFace ──
    hub = hf_hub_cache()
    if hub.is_dir():
        for d in sorted(hub.glob("models--*")):
            repo = d.name[len("models--"):].replace("--", "/")
            if repo.lower() in claimed_repo:
                continue
            snap = _hf_snapshot(repo)
            if snap is None:
                continue
            meta = _readme_meta(snap)
            rt = _guess_runtime(snap, repo)
            tags = [t for t in (meta.get("tags") or [])
                    if not t.startswith(("license", "region", "dataset", "base_model"))][:4]
            name = _slug(repo.split("/")[-1])
            if name in known_names:
                name = _slug(repo.replace("/", "-"))
            known_names.add(name)
            found.append(ModelInfo(
                name=name, title=repo.split("/")[-1], runtime=rt,
                task=_PIPELINE_TASK.get(meta.get("pipeline_tag", ""), "khác"),
                store="hf", access=["path"], size_gb=0.0, ram_gb=0.0,
                tags=tags, desc="", strengths=[], owners=[],
                source={"kind": "hf", "repo": repo},
                status="present", path=str(snap),
                disk_gb=round(_du_gb(snap), 2), undeclared=True,
            ))

    # ── Ollama ──
    om = Path(os.environ.get("OLLAMA_MODELS", str(store_dir("ollama"))))
    man = om / "manifests" / "registry.ollama.ai"
    if man.is_dir():
        for tag_file in sorted(man.rglob("*")):
            if not tag_file.is_file():
                continue
            rel = tag_file.relative_to(man).parts
            repo = "/".join(rel[:-1]); tag = rel[-1]
            ref = (repo[len("library/"):] if repo.startswith("library/") else repo) + ":" + tag
            if ref.lower() in claimed_ref:
                continue
            name = _slug(ref)
            if name in known_names:
                continue
            known_names.add(name)
            g = _ollama_du_gb(ref)
            found.append(ModelInfo(
                name=name, title=ref, runtime="ollama", task="khác",
                store="ollama", access=["endpoint"], size_gb=0.0, ram_gb=0.0,
                tags=[], desc="", strengths=[], owners=[], ref=ref,
                status="present", disk_gb=round(g, 2) if g else None,
                undeclared=True,
            ))

    # ── openai-whisper (.pt) ──
    wd = Path(os.environ.get("AIHUB_WHISPER_DIR", str(store_dir("whisper"))))
    if wd.is_dir():
        for p in sorted(wd.glob("*.pt")):
            if p.name in claimed_file:
                continue
            name = _slug("whisper-" + p.stem + "-pt")
            if name in known_names:
                continue
            known_names.add(name)
            found.append(ModelInfo(
                name=name, title=f"Whisper {p.stem} (PyTorch)", runtime="openai-whisper",
                task="asr", store="whisper", access=["path"], size_gb=0.0, ram_gb=0.0,
                tags=[], desc="", strengths=[], owners=[], file=p.name,
                status="present", path=str(p),
                disk_gb=round(p.stat().st_size / 1e9, 2), undeclared=True,
            ))

    return found
