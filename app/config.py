"""Пути, каталоги данных и локальная конфигурация приложения.

Все изменяемые данные (база, вложения, резервные копии) хранятся ВНЕ каталога
установки программы. Благодаря этому обновление приложения (в том числе
переустановка установщиком) никогда не затрагивает базу данных.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

APP_SLUG = "AvansReport"
ENV_DATA_DIR = "AVANS_DATA_DIR"
ENV_DESKTOP = "AVANS_DESKTOP"

DEFAULT_CONFIG: Dict[str, Any] = {
    # Локальный сервер (режим "сервер" или однопользовательский режим)
    "host": "127.0.0.1",
    "port": 8770,
    "open_browser": True,
    # Режим "клиент": если адрес указан, локальный сервер не запускается,
    # а открывается GUI уже работающего сервера в локальной сети.
    "remote_url": "",
    # Необязательный HTTPS для доступа через интернет
    "tls_cert": "",
    "tls_key": "",
    # Разрешить установку обновления из интерфейса программы (Windows)
    "allow_self_update": True,
}


def is_frozen() -> bool:
    """Запущено ли приложение как собранный исполняемый файл (PyInstaller)."""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def resource_dir() -> Path:
    """Каталог со статикой и шаблонами (работает и в собранном виде)."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "app"
    return Path(__file__).resolve().parent


def data_dir() -> Path:
    """Каталог данных пользователя. Переопределяется переменной AVANS_DATA_DIR."""
    raw = os.environ.get(ENV_DATA_DIR)
    if raw:
        path = Path(raw).expanduser()
    elif sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_SLUG
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_SLUG
    else:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        path = Path(base) / APP_SLUG
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return data_dir() / "avans.db"


def backups_dir() -> Path:
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def updates_dir() -> Path:
    path = data_dir() / "updates"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    return data_dir() / "avans-report.log"


def config_path() -> Path:
    return data_dir() / "config.json"


def read_config() -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONFIG)
    path = config_path()
    if path.exists():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                cfg.update({k: v for k, v in loaded.items() if k in DEFAULT_CONFIG})
        except (OSError, ValueError):
            pass
    return cfg


def write_config(values: Dict[str, Any]) -> Dict[str, Any]:
    cfg = read_config()
    cfg.update({k: v for k, v in values.items() if k in DEFAULT_CONFIG})
    config_path().write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return cfg


def ensure_config() -> Dict[str, Any]:
    path = config_path()
    if not path.exists():
        write_config(DEFAULT_CONFIG)
    return read_config()


def static_dir() -> Path:
    return resource_dir() / "static"


def template_path() -> Path:
    return resource_dir() / "assets" / "template.xlsm"
