"""Проверка обновлений на GitHub и (для Windows-сборки) установка обновления."""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import config, db
from .version import GITHUB_API_LATEST, GITHUB_RELEASES_URL, __version__

CACHE_SECONDS = 300
_cache: Dict[str, Any] = {"timestamp": 0.0, "payload": None}

VERSION_RE = re.compile(r"^v?(\d+(?:\.\d+)*)$")


class UpdateError(RuntimeError):
    pass


def platform_key() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def parse_version(value: str) -> tuple:
    text = (value or "").strip()
    match = VERSION_RE.match(text)
    if not match:
        digits = re.findall(r"\d+", text)
        return tuple(int(part) for part in digits[:3]) or (0,)
    parts = [int(part) for part in match.group(1).split(".")]
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def is_newer(candidate: str, current: str) -> bool:
    return parse_version(candidate) > parse_version(current)


def ssl_context() -> ssl.SSLContext:
    """Контекст проверки сертификатов для запросов к GitHub.

    В собранной программе системные сертификаты могут быть не видны
    (ошибка CERTIFICATE_VERIFY_FAILED), поэтому дополнительно подключаем
    набор из пакета certifi. Системные сертификаты тоже грузим — на рабочих
    компьютерах с антивирусом, проверяющим HTTPS, корневой сертификат
    хранится именно там.
    """
    context = ssl.create_default_context()
    try:
        import certifi

        context.load_verify_locations(cafile=certifi.where())
    except (ImportError, OSError, ssl.SSLError):
        pass
    try:
        context.load_default_certs()
    except (OSError, ssl.SSLError):
        pass
    return context


def _friendly_network_error(exc: BaseException) -> str:
    """Понятное объяснение вместо простыни из ssl-ошибок."""
    text = str(exc)
    ssl_problem = any(token in text for token in (
        "CERTIFICATE_VERIFY_FAILED", "certificate verify failed",
        "CERTIFICATE_VERIFY", "SSLError",
    ))
    if ssl_problem:
        return ("Не удалось проверить сертификат GitHub. Проверьте дату и время "
                "на компьютере и нажмите «Скачать файл» — обновление можно "
                "скачать в браузере через страницу релизов.")
    return f"Нет связи с GitHub: {text}"


def _request_json(url: str, timeout: int = 10) -> Dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": f"AvansReport/{__version__}",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(  # noqa: S310
        request, timeout=timeout, context=ssl_context()
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def _pick_assets(assets: List[Dict[str, Any]],
                 prefix: str = "AvansReport") -> Dict[str, Dict[str, Any]]:
    """Раскладывает файлы релиза по платформам.

    prefix позволяет отделить файлы серверной версии (AvansReport) от автономной
    (AvansStandalone): в одном релизе публикуются оба установщика.
    """
    picked: Dict[str, Dict[str, Any]] = {}
    prefix_lower = prefix.lower()
    for asset in assets:
        name = (asset.get("name") or "").lower()
        info = {
            "name": asset.get("name"),
            "size": asset.get("size"),
            "url": asset.get("browser_download_url"),
        }
        if name.endswith(".sha256"):
            picked.setdefault("checksums", info)
            continue
        if prefix_lower and prefix_lower not in name:
            continue
        if name.endswith(".exe") and ("setup" in name or "install" in name):
            picked.setdefault("windows_installer", info)
        elif name.endswith(".zip") and "portable" in name:
            picked.setdefault("windows_portable", info)
        elif name.endswith((".tar.gz", ".tgz")):
            picked.setdefault("linux_archive", info)
        elif name.endswith((".dmg", ".pkg")):
            picked.setdefault("macos_installer", info)
    return picked


def check_for_updates(force: bool = False,
                      asset_prefix: str = "AvansReport") -> Dict[str, Any]:
    now = time.time()
    if (
        not force
        and _cache["payload"] is not None
        and _cache.get("key") == f"{asset_prefix}:"
        and now - float(_cache["timestamp"]) < CACHE_SECONDS
    ):
        return dict(_cache["payload"])

    result: Dict[str, Any] = {
        "current_version": __version__,
        "latest_version": None,
        "update_available": False,
        "release_name": None,
        "release_notes": "",
        "release_url": GITHUB_RELEASES_URL,
        "published_at": None,
        "assets": {},
        "download_url": GITHUB_RELEASES_URL,
        "platform": platform_key(),
        "error": None,
        "checked_at": db.now_iso(),
        "self_update_supported": supports_self_update(),
    }
    try:
        payload = _request_json(GITHUB_API_LATEST)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            result["error"] = "Релизы на GitHub ещё не опубликованы."
        elif exc.code in (403, 429):
            result["error"] = "GitHub временно ограничил число запросов. Попробуйте позже."
        else:
            result["error"] = f"GitHub вернул ошибку {exc.code}."
        _cache.update(timestamp=now, payload=result, key=f"{asset_prefix}:")
        return dict(result)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        result["error"] = _friendly_network_error(exc)
        _cache.update(timestamp=now, payload=result, key=f"{asset_prefix}:")
        return dict(result)

    latest = (payload.get("tag_name") or payload.get("name") or "").strip()
    assets = _pick_assets(payload.get("assets") or [], asset_prefix)
    result.update(
        {
            "latest_version": latest.lstrip("v"),
            "release_name": payload.get("name") or latest,
            "release_notes": (payload.get("body") or "").strip()[:8000],
            "release_url": payload.get("html_url") or GITHUB_RELEASES_URL,
            "published_at": payload.get("published_at"),
            "assets": assets,
            "update_available": bool(latest) and is_newer(latest, __version__),
        }
    )
    platform_asset = assets.get(f"{platform_key()}_installer") or assets.get(
        f"{platform_key()}_archive"
    )
    if platform_asset and platform_asset.get("url"):
        result["download_url"] = platform_asset["url"]
    elif assets.get("windows_installer"):
        result["download_url"] = assets["windows_installer"]["url"]

    _cache.update(timestamp=now, payload=result, key=f"{asset_prefix}:")
    return dict(result)


def supports_self_update() -> bool:
    if not sys.platform.startswith("win"):
        return False
    if not config.is_frozen() and os.environ.get(config.ENV_DESKTOP) != "1":
        return False
    return bool(config.read_config().get("allow_self_update", True))


def _download(url: str, target: Path, timeout: int = 120) -> Path:
    headers = {"User-Agent": f"AvansReport/{__version__}", "Accept": "application/octet-stream"}
    request = urllib.request.Request(url, headers=headers)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + ".part")
    with urllib.request.urlopen(  # noqa: S310
        request, timeout=timeout, context=ssl_context()
    ) as response:
        with open(tmp, "wb") as handle:
            shutil.copyfileobj(response, handle)
    if tmp.stat().st_size < 1024 * 100:
        tmp.unlink(missing_ok=True)
        raise UpdateError("Скачанный файл обновления повреждён (слишком мал).")
    tmp.replace(target)
    return target


def download_update(info: Dict[str, Any]) -> Path:
    url = info.get("download_url") or ""
    assets = info.get("assets") or {}
    platform_asset = (
        assets.get(f"{platform_key()}_installer")
        or assets.get(f"{platform_key()}_archive")
        or assets.get("windows_installer")
    )
    if platform_asset and platform_asset.get("url"):
        url = platform_asset["url"]
    if not url or not url.startswith("https://"):
        raise UpdateError("В релизе не найден файл обновления для этой платформы.")
    filename = (platform_asset or {}).get("name") or Path(url).name
    target = config.updates_dir() / filename
    return _download(url, target)


def install_update(info: Dict[str, Any], make_backup: bool = True) -> Dict[str, Any]:
    """Скачивает установщик, (при необходимости) делает копию базы и запускает установку."""
    if not supports_self_update():
        raise UpdateError(
            "Автоматическая установка доступна только в Windows-сборке программы. "
            "Скачайте установщик по ссылке и запустите его вручную."
        )
    if not info.get("update_available"):
        raise UpdateError("Установленная версия уже актуальна.")

    # Самое важное: сохраняем данные до обновления (в автономном режиме БД нет).
    backup = db.backup_database(reason="before-update") if make_backup else None
    installer = download_update(info)
    if installer.suffix.lower() != ".exe":
        raise UpdateError("Файл обновления не является установщиком Windows.")
    try:
        subprocess.Popen(  # noqa: S603,S607
            [
                str(installer),
                "/VERYSILENT",
                "/SUPPRESSMSGBOXES",
                "/CLOSEAPPLICATIONS",
                "/RESTARTAPPLICATIONS",
                "/NORESTART",
            ],
            close_fds=True,
        )
    except OSError as exc:
        raise UpdateError(f"Не удалось запустить установщик: {exc}") from exc
    return {
        "ok": True,
        "backup": str(backup) if backup else None,
        "installer": str(installer),
        "message": "Установщик запущен. Программа перезапустится автоматически.",
    }
