"""تحميل إعدادات RouterGuard من config.yaml مع دعم متغيرات البيئة."""
from __future__ import annotations

import copy
import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml

log = logging.getLogger("routerguard.config")

ENV_REF = re.compile(r"^env:([A-Za-z_][A-Za-z0-9_]*)$")
ENV_OVERRIDE_PREFIX = "ROUTERGUARD__"

# مفاتيح حساسة تُخفى عند الطباعة في الـ logs
SENSITIVE_KEYS = {"password", "bot_token", "chat_id", "username"}


def _resolve_env_refs(node: Any) -> Any:
    """يستبدل القيم بصيغة env:VAR_NAME بقيمة متغير البيئة."""
    if isinstance(node, dict):
        return {k: _resolve_env_refs(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_env_refs(v) for v in node]
    if isinstance(node, str):
        m = ENV_REF.match(node.strip())
        if m:
            return os.environ.get(m.group(1), "")
    return node


def _apply_env_overrides(cfg: dict) -> dict:
    """متغيرات بصيغة ROUTERGUARD__SECTION__KEY تتجاوز قيم الملف."""
    for env_key, value in os.environ.items():
        if not env_key.startswith(ENV_OVERRIDE_PREFIX):
            continue
        path = env_key[len(ENV_OVERRIDE_PREFIX):].lower().split("__")
        node = cfg
        for part in path[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                break
        else:
            node[path[-1]] = value
    return cfg


def load_config(path: str | Path | None = None) -> dict:
    """يحمّل الإعدادات. إن لم يوجد config.yaml يستخدم config.example.yaml."""
    if path is None:
        here = Path(__file__).resolve().parent.parent
        path = here / "config.yaml"
        if not path.exists():
            path = here / "config.example.yaml"
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"ملف الإعدادات غير موجود: {path}")

    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    cfg = _resolve_env_refs(cfg)
    cfg = _apply_env_overrides(cfg)
    log.info("تم تحميل الإعدادات من %s", path)
    return cfg


def masked_config(cfg: dict) -> dict:
    """نسخة من الإعدادات مع إخفاء القيم الحساسة (للعرض الآمن)."""
    cfg = copy.deepcopy(cfg)

    def _mask(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: ("***" if k.lower() in SENSITIVE_KEYS and v else _mask(v))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [_mask(v) for v in node]
        return node

    return _mask(cfg)


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent
