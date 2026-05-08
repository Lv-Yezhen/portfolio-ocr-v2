import json
import os
from typing import Any, Dict


def project_root() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def resolve_path(config: Dict[str, Any], key: str, *, required: bool = True) -> str:
    value = str(config.get(key, "")).strip()
    if not value:
        if required:
            raise ValueError(f"缺少配置项: {key}")
        return ""
    return value if os.path.isabs(value) else os.path.join(project_root(), value)


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        ensure_dir(parent)


def load_json_object(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def write_json(path: str, payload: Dict[str, Any]) -> None:
    ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
