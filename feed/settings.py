"""Read local feed service settings without loading secrets into logs."""

import os
import re
from datetime import timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
RUNTIME = ROOT / ".runtime"
KST = timezone(timedelta(hours=9))
DOTENV_VALUE = re.compile(r'''^\s*(?:"([^"]*)"|'([^']*)'|([^#]*?))\s*(?:#.*)?$''')


def file_setting(path: Path, name: str) -> str:
    if not path.is_file():
        return ""
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        label, separator, value = line.partition("=")
        if separator and label.strip().removeprefix("export ").strip() == name:
            matched = DOTENV_VALUE.fullmatch(value)
            if not matched:
                raise ValueError(f"Invalid .env setting: {name}")
            return next(part for part in matched.groups() if part is not None).strip()
    return ""


def setting(name: str, default: str = "") -> str:
    return os.environ.get(name, "").strip() or file_setting(ROOT / ".env", name) or default


def vault_path() -> Path:
    configured = setting("OBSIDIAN_VAULT_PATH")
    if configured:
        return (ROOT / Path(configured).expanduser()).resolve()
    return ROOT.parent / "NVIDIA Feed Vault"


def runtime_path(name: str) -> Path:
    current = RUNTIME / name
    legacy = ROOT / name
    if not current.exists() and legacy.is_file():
        return legacy
    return current
