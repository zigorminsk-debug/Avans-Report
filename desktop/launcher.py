#!/usr/bin/env python3
"""Запуск приложения «Авансовые отчёты» как настольной программы или сервера.

Режимы работы:
  * обычный запуск      — поднимает локальный сервер и открывает интерфейс в браузере;
  * сервер              — --host 0.0.0.0 --port 8770 (доступ по локальной сети);
  * клиент              — --connect http://server:8770 (открывает интерфейс сервера).

Вся информация хранится в каталоге данных пользователя, поэтому обновление
программы не затрагивает базу данных.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config  # noqa: E402
from app.version import APP_NAME, __version__  # noqa: E402


def ensure_std_streams() -> None:
    """В оконной сборке Windows sys.stdout/stderr = None: направляем их в журнал."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    try:
        stream = open(config.log_path(), "a", encoding="utf-8", buffering=1)
    except OSError:
        stream = open(os.devnull, "w", encoding="utf-8")
    if sys.stdout is None:
        sys.stdout = stream
    if sys.stderr is None:
        sys.stderr = stream


def setup_logging() -> None:
    ensure_std_streams()
    handlers = [logging.StreamHandler(sys.stdout)] if sys.stdout else []
    try:
        handlers.append(
            logging.handlers.RotatingFileHandler(
                config.log_path(), maxBytes=1_000_000, backupCount=3, encoding="utf-8"
            )
        )
    except OSError:
        pass
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers or [logging.NullHandler()],
    )


def local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            return sock.getsockname()[0]
    except OSError:
        return ""


def port_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host if host not in ("0.0.0.0", "") else "0.0.0.0", port))
            return True
        except OSError:
            return False


def choose_port(host: str, preferred: int, attempts: int = 15) -> int:
    for offset in range(attempts):
        candidate = preferred + offset
        if port_available(host, candidate):
            return candidate
    raise SystemExit(f"Не удалось найти свободный порт, начиная с {preferred}")


def running_instance_url(host: str, port: int) -> str:
    """Если по адресу уже работает наша программа — вернуть её URL."""
    if host in ("0.0.0.0", ""):
        hosts = ["127.0.0.1"]
    else:
        hosts = [host, "127.0.0.1"]
    for candidate in dict.fromkeys(hosts):
        url = f"http://{candidate}:{port}"
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1.2) as response:  # noqa: S310
                payload = json.loads(response.read().decode("utf-8"))
                if payload.get("app") == APP_NAME:
                    return url
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return ""


def wait_for_server(url: str, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1.5) as response:  # noqa: S310
                if response.status == 200:
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.25)
    return False


def open_data_dir() -> None:
    path = str(config.data_dir())
    if sys.platform.startswith("win"):
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])  # noqa: S603,S607
    else:
        subprocess.Popen(["xdg-open", path])  # noqa: S603,S607


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="AvansReport",
        description=f"{APP_NAME} — формирование, печать и отправка авансовых отчётов",
    )
    parser.add_argument("--host", default=None, help="адрес сервера (по умолчанию из config.json)")
    parser.add_argument("--port", type=int, default=None, help="порт (по умолчанию из config.json)")
    parser.add_argument("--data-dir", default=None, help="каталог для базы данных")
    parser.add_argument("--connect", default=None, help="адрес уже запущенного сервера (режим клиента)")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--open-data-dir", action="store_true", help="открыть каталог с базой данных")
    parser.add_argument("--check-updates", action="store_true", help="проверить обновления и выйти")
    parser.add_argument("--version", action="store_true", help="показать версию")
    args = parser.parse_args(argv)

    if args.version:
        print(f"{APP_NAME} {__version__}")
        return 0

    if args.data_dir:
        os.environ[config.ENV_DATA_DIR] = str(Path(args.data_dir).expanduser())
    os.environ.setdefault(config.ENV_DESKTOP, "1")

    ensure_std_streams()
    setup_logging()
    log = logging.getLogger("avans.launcher")
    cfg = config.ensure_config()

    if args.open_data_dir:
        open_data_dir()
        return 0

    if args.check_updates:
        from app.updates import check_for_updates

        info = check_for_updates(force=True)
        print(f"Установленная версия: {info['current_version']}")
        if info.get("error"):
            print(f"Ошибка проверки: {info['error']}")
        else:
            print(f"Последний релиз: {info.get('latest_version') or '—'}")
            print("Доступно обновление" if info.get("update_available")
                  else "Установлена последняя версия")
            if info.get("download_url"):
                print(f"Скачать: {info['download_url']}")
        return 0

    connect_url = args.connect or (cfg.get("remote_url") or "")
    if connect_url:
        url = connect_url.rstrip("/")
        log.info("Режим клиента: %s", url)
        if not args.no_browser:
            webbrowser.open(url)
        else:
            print(url)
        return 0

    host = args.host or cfg.get("host") or "127.0.0.1"
    preferred = int(args.port or cfg.get("port") or 8770)

    # Программа уже запущена (например, ярлык нажали второй раз) — просто
    # открываем окно браузера, второй сервер не поднимаем.
    existing = running_instance_url(host, preferred)
    if existing:
        log.info("Программа уже запущена: %s", existing)
        if not args.no_browser:
            webbrowser.open(existing)
        else:
            print(existing)
        return 0

    port = choose_port(host, preferred)
    scheme = "https" if cfg.get("tls_cert") and cfg.get("tls_key") else "http"
    local_url = f"{scheme}://127.0.0.1:{port}"
    lan_url = f"{scheme}://{local_ip()}:{port}" if host == "0.0.0.0" and local_ip() else ""

    import uvicorn  # импорт внутри функции — быстрее стартует --version

    from app.main import create_app

    application = create_app()
    uvicorn_config = uvicorn.Config(
        application,
        host=host,
        port=port,
        log_level="info",
        access_log=False,
        ssl_certfile=cfg.get("tls_cert") or None,
        ssl_keyfile=cfg.get("tls_key") or None,
        timeout_keep_alive=30,
    )
    server = uvicorn.Server(uvicorn_config)
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    if not wait_for_server(local_url):
        log.error("Сервер не запустился. Смотрите журнал: %s", config.log_path())
        return 1

    log.info("%s %s запущены", APP_NAME, __version__)
    log.info("Интерфейс: %s", local_url)
    log.info("Данные: %s", config.data_dir())
    if lan_url:
        log.info("Доступ по локальной сети: %s", lan_url)
        print(f"\n  Откройте у сотрудников: {lan_url}\n")

    if cfg.get("open_browser", True) and not args.no_browser:
        webbrowser.open(local_url)

    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.info("Остановка сервера…")
        server.should_exit = True
        thread.join(timeout=10)
    return 0


if __name__ == "__main__":
    sys.exit(main())
