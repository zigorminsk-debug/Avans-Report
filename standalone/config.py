"""Пути и настройки автономной версии «Авансовые отчёты — автономный режим».

Автономная программа не использует базу данных и учётные записи: каждый запуск
создаёт отдельную сессию, отчёты сохраняются в личную папку сессии
(JSON + PDF). Один работающий сервер обслуживает сколько угодно окон браузера —
каждое окно может вести свою сессию.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

APP_NAME = "Авансовые отчёты — автономный режим"
ENV_DATA_DIR = "AVANS_STANDALONE_DATA_DIR"
ENV_DESKTOP = "AVANS_DESKTOP"

DEFAULT_PORT = 8780
PORT_SCAN = 40

DEFAULT_SETTINGS: Dict[str, Any] = {
    "org_name": 'ООО "Сэйлз Модерн групп"',
    "director_position": "Директор",
    "director_name": "Н.В. Сашко",
    "accountant_position": "Бухгалтер",
    "accountant_name": "",
    "purposes": ["Командировочные расходы", "Расходы на хозяйственные нужды"],
    "default_person_name": "",
    "default_person_position": "",
    "open_folder_available": True,
}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def resource_dir() -> Path:
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle)
    return Path(__file__).resolve().parent.parent


def standalone_static_dir() -> Path:
    return resource_dir() / "standalone" / "static"


def shared_static_dir() -> Path:
    return resource_dir() / "app" / "static"


def installed_fonts_dir() -> Path:
    return resource_dir() / "app" / "assets" / "fonts"


def data_dir() -> Path:
    """Корень данных автономной версии."""
    raw = os.environ.get(ENV_DATA_DIR)
    if raw:
        path = Path(raw).expanduser()
    elif sys.platform.startswith("win"):
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        path = Path(base) / "AvansReportStandalone"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "AvansReportStandalone"
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / "AvansReportStandalone"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sessions_dir() -> Path:
    """Папка отчётов. Создаётся только при первом сохранении отчёта."""
    return data_dir() / "reports"


def sessions_dir_for_save() -> Path:
    """Папка отчётов, готовая к записи (создаётся при необходимости)."""
    path = sessions_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def session_dir(session_id: str) -> Path:
    """Путь папки сессии. На диск ничего не создаёт — папка появляется
    только при сохранении отчёта."""
    safe = "".join(ch for ch in session_id if ch.isalnum() or ch in "-_")[:48]
    if not safe:
        raise ValueError("Некорректный идентификатор сессии")
    return sessions_dir() / safe


def ensure_session_dir(session_id: str) -> Path:
    """Папка сессии, готовая к записи (создаётся при необходимости)."""
    path = session_dir(session_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def config_path() -> Path:
    return data_dir() / "standalone.json"


def instance_path() -> Path:
    return data_dir() / "instance.json"


def lock_path() -> Path:
    return data_dir() / "instance.lock"


def log_path() -> Path:
    return data_dir() / "standalone.log"


def default_config() -> Dict[str, Any]:
    return {
        "port": DEFAULT_PORT,
        "host": "127.0.0.1",
        "open_browser": True,
        "auto_delete_empty_sessions_days": 30,
    }


def read_config() -> Dict[str, Any]:
    cfg = default_config()
    path = config_path()
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for key in cfg:
                    if key in loaded:
                        cfg[key] = loaded[key]
        except (OSError, ValueError):
            pass
    return cfg


def write_config(values: Dict[str, Any]) -> Dict[str, Any]:
    cfg = read_config()
    for key in cfg:
        if key in values:
            cfg[key] = values[key]
    config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def read_settings() -> Dict[str, Any]:
    path = data_dir() / "settings.json"
    settings = json.loads(json.dumps(DEFAULT_SETTINGS))
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                settings.update({k: v for k, v in loaded.items() if k in DEFAULT_SETTINGS})
        except (OSError, ValueError):
            pass
    return settings


def write_settings(values: Dict[str, Any]) -> Dict[str, Any]:
    settings = read_settings()
    settings.update({k: v for k, v in values.items() if k in DEFAULT_SETTINGS})
    (data_dir() / "settings.json").write_text(
        json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return settings


def new_session_id() -> str:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    import secrets

    return f"{stamp}-{secrets.token_hex(3)}"
