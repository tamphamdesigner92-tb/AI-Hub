"""AI Hub — kho model AI local dùng chung.

    import aihub
    aihub.path("whisper-turbo-mlx")    # đường dẫn file (không tải)
    aihub.ensure("whisper-turbo-mlx")  # tải nếu thiếu rồi trả đường dẫn
    aihub.endpoint("qwen3.5")          # (url_openai, tên_model)
    aihub.list(task="asr")             # liệt kê
    aihub.env()                        # env để truyền cho subprocess
"""
from __future__ import annotations

from pathlib import Path

from .resolve import (
    Endpoint,
    ModelInfo,
    ModelNotAvailable,
    ModelNotFound,
    env_dict,
    get,
    list_models,
    load_registry,
    resolve_endpoint,
    resolve_path,
    store_dir,
    store_root,
    whisper_root,
)

__version__ = "1.0.0"
__all__ = [
    "path", "ensure", "endpoint", "list", "info", "env",
    "store", "whisper_root", "Endpoint", "ModelInfo",
    "ModelNotAvailable", "ModelNotFound",
]


def path(name: str) -> Path:
    """Đường dẫn model trên đĩa. Ném ModelNotAvailable nếu chưa tải.

    Cố tình KHÔNG tự tải: tránh việc một hot path bất ngờ block 3 GB download.
    """
    return resolve_path(name)


def ensure(name: str) -> Path:
    """Như path() nhưng tải về nếu thiếu."""
    try:
        return resolve_path(name)
    except ModelNotAvailable:
        from .fetch import pull_registered
        pull_registered(name)
        return resolve_path(name)


def endpoint(name: str) -> Endpoint:
    """Endpoint HTTP cho model chạy qua service. Unpack được: url, model = ..."""
    return resolve_endpoint(name)


def list(**kw) -> "builtins.list[ModelInfo]":  # noqa: A001
    return list_models(**kw)


def info(name: str, with_disk: bool = False) -> ModelInfo:
    return get(name, with_disk=with_disk)


def env() -> dict:
    return env_dict()


def store() -> Path:
    return store_root()
