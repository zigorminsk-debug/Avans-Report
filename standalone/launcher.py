"""Запуск автономной версии: сервер + открытие интерфейса.

Одновременные запуски:
  * первый запуск поднимает локальный сервер и запоминает порт в instance.json;
  * повторный запуск (ярлык нажали ещё раз) видит работающий экземпляр и просто
    открывает интерфейс в браузере — второй сервер не поднимается;
  * блокировка файлом не даёт двум процессам одновременно стартовать.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import Any, Dict, Optional

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.version import __version__  # noqa: E402
from standalone import config  # noqa: E402

try:  # блокировка экземпляра
    import fcntl
except ImportError:  # pragma: no cover - Windows
    fcntl = None
    try:
        import msvcrt
    except ImportError:
        msvcrt = None


def ensure_std_streams() -> None:
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


# ---------------------------------------------------------------------------
# Блокировка единственного сервера (сколько угодно окон браузера — это норма)
# ---------------------------------------------------------------------------
class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = open(self.path, "a+b")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt is not None:  # pragma: no cover - Windows
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            self._handle = handle
            return True
        except OSError:
            handle.close()
            return False

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:  # pragma: no cover - Windows
                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        finally:
            self._handle.close()
            self._handle = None


# ---------------------------------------------------------------------------
# Определение уже работающего экземпляра
# ---------------------------------------------------------------------------
def server_info(port: int, timeout: float = 1.2) -> Optional[Dict[str, Any]]:
    """Ответ /api/health программы на этом порту (или None, если это не она)."""
    for host in ("127.0.0.1", "localhost"):
        try:
            with urllib.request.urlopen(  # noqa: S310
                f"http://{host}:{port}/api/health", timeout=timeout
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError):
            continue
        if payload.get("mode") == "standalone" and payload.get("app") == config.APP_NAME:
            return payload
    return None


def is_our_server(port: int, timeout: float = 1.2) -> bool:
    return server_info(port, timeout) is not None


def instance_problem(payload: Dict[str, Any], data_dir: Optional[str] = None) -> Optional[str]:
    """Почему экземпляр нельзя переиспользовать (None — можно)."""
    if not payload:
        return "не отвечает"
    if str(payload.get("version") or "") != __version__:
        return f"другая версия программы ({payload.get('version') or '?'})"
    if data_dir is not None and str(payload.get("data_dir") or "") != str(data_dir):
        return "другой каталог данных"
    if not payload.get("ui", True):
        return "нет файлов интерфейса"
    return None


def is_usable_instance(payload: Dict[str, Any], data_dir: Optional[str] = None) -> bool:
    """Этот экземпляр можно переиспользовать (та же версия, данные и интерфейс).

    Процесс старой версии после обновления остаётся жить: его файлы уже
    заменены, интерфейс не отдаётся, а старый instance.json указывает на него.
    Открывать такой порт нельзя — иначе браузер показывает «Интерфейс не найден».
    Экземпляр с другим каталогом данных — тоже не наш (иначе одно окно
    программы открывало бы отчёты другого пользователя/каталога).
    """
    return instance_problem(payload, data_dir) is None


def running_instance() -> Optional[Dict[str, Any]]:
    """Работающий экземпляр этой же версии (по instance.json или порту по умолчанию)."""
    candidates = []
    path = config.instance_path()
    if path.exists():
        try:
            candidates.append(int(json.loads(path.read_text(encoding="utf-8")).get("port") or 0))
        except (OSError, ValueError, TypeError, AttributeError):
            pass
    try:
        candidates.append(int(config.read_config().get("port") or config.DEFAULT_PORT))
    except (OSError, ValueError, TypeError):
        pass
    candidates.append(config.DEFAULT_PORT)

    seen = set()
    for port in candidates:
        if not port or port in seen:
            continue
        seen.add(port)
        payload = server_info(port)
        if payload is None:
            continue
        problem = instance_problem(payload, str(config.data_dir()))
        if problem:
            logging.getLogger("avans.standalone.launcher").warning(
                "Порт %s: %s — этот экземпляр не используем", port, problem
            )
            continue
        payload["port"] = port
        payload["url"] = f"http://127.0.0.1:{port}/"
        return payload
    return None


def port_answers(port: int, timeout: float = 0.35) -> bool:
    """Кто-то уже слушает порт (в том числе чужая программа или старая копия)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            return sock.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def port_available(port: int) -> bool:
    if port_answers(port):
        return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if not sys.platform.startswith("win"):
            # На Windows SO_REUSEADDR позволяет занять уже используемый порт
            # (браузер потом открывал чужой порт), на Linux/macOS он нужен,
            # чтобы не мешали «повисшие» соединения после остановки программы.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def choose_port(preferred: int, attempts: int = config.PORT_SCAN) -> int:
    for offset in range(attempts):
        candidate = preferred + offset
        if port_available(candidate):
            return candidate
    # последняя попытка: свободный порт от системы
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def write_instance(port: int) -> None:
    payload = {
        "port": port,
        "pid": os.getpid(),
        "version": __version__,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "url": f"http://127.0.0.1:{port}/",
    }
    path = config.instance_path()
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def clear_instance() -> None:
    try:
        config.instance_path().unlink()
    except OSError:
        pass


def wait_for_server(port: int, timeout: float = 25.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if is_our_server(port, timeout=0.6):
            return True
        time.sleep(0.25)
    return False


def open_url(url: str) -> None:
    try:
        webbrowser.open(url)
    except Exception:  # pragma: no cover
        print(url)


def run(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="AvansStandalone",
        description=f"{config.APP_NAME} — заполнение, сохранение в PDF и печать без входа",
    )
    parser.add_argument("--port", type=int, default=None, help="порт (по умолчанию 8780)")
    parser.add_argument("--host", default=None,
                        help="адрес прослушивания (по умолчанию 127.0.0.1; "
                             "0.0.0.0 — доступ с других компьютеров сети)")
    parser.add_argument("--data-dir", default=None, help="каталог для отчётов и настроек")
    parser.add_argument("--no-browser", action="store_true", help="не открывать браузер")
    parser.add_argument("--open-data-dir", action="store_true", help="открыть папку с отчётами")
    parser.add_argument("--print-url", action="store_true", help="показать адрес и выйти")
    parser.add_argument("--check-updates", action="store_true", help="проверить обновления")
    parser.add_argument("--version", action="store_true", help="показать версию")
    args = parser.parse_args(argv)

    if args.version:
        print(f"{config.APP_NAME} {__version__}")
        return 0
    if args.data_dir:
        os.environ[config.ENV_DATA_DIR] = str(Path(args.data_dir).expanduser())
    os.environ.setdefault(config.ENV_DESKTOP, "1")

    ensure_std_streams()
    setup_logging()
    log = logging.getLogger("avans.standalone.launcher")
    cfg = config.read_config()

    if args.open_data_dir:
        folder = config.sessions_dir_for_save()
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))  # type: ignore[attr-defined]  # noqa: S606
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", str(folder)])  # noqa: S603,S607
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(folder)])  # noqa: S603,S607
        except OSError as exc:  # pragma: no cover
            log.error("Не удалось открыть папку: %s", exc)
        return 0

    if args.check_updates:
        from app.updates import check_for_updates

        info = check_for_updates(force=True, asset_prefix="AvansStandalone")
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

    existing = running_instance()
    if existing:
        url = existing["url"]
        log.info("Программа уже запущена: %s", url)
        if args.no_browser or args.print_url:
            print(url)
        else:
            open_url(url)
        return 0

    lock = InstanceLock(config.lock_path())
    acquired = lock.acquire()
    if not acquired:
        # Другой процесс стартует прямо сейчас — подождём его и откроем окно.
        # Если он так и не поднялся (например, это старая версия после
        # обновления), запускаем свой сервер, а не выходим с ошибкой.
        for _ in range(40):
            time.sleep(0.25)
            existing = running_instance()
            if existing:
                if args.no_browser or args.print_url:
                    print(existing["url"])
                else:
                    open_url(existing["url"])
                return 0
            if lock.acquire():
                acquired = True
                break
        if not acquired:
            log.warning("Найден другой запущенный экземпляр программы — запускаем свой")

    existing = running_instance()
    if existing:
        if acquired:
            lock.release()
        log.info("Программа уже запущена: %s", existing["url"])
        if args.no_browser or args.print_url:
            print(existing["url"])
        else:
            open_url(existing["url"])
        return 0

    requested = int(args.port or cfg.get("port") or config.DEFAULT_PORT)
    port = choose_port(requested)
    if port != requested:
        log.info("Порт %s занят — программа работает на порту %s", requested, port)
    write_instance(port)
    url = f"http://127.0.0.1:{port}/"

    import uvicorn

    from standalone.server import create_app

    application = create_app()
    uvicorn_config = uvicorn.Config(
        application,
        host=args.host or cfg.get("host") or "127.0.0.1",
        port=port,
        log_level="info",
        access_log=False,
        timeout_keep_alive=30,
    )
    server = uvicorn.Server(uvicorn_config)
    thread = threading.Thread(target=server.run, name="uvicorn", daemon=True)
    thread.start()

    if not wait_for_server(port):
        log.error("Сервер не запустился. Журнал: %s", config.log_path())
        clear_instance()
        if acquired:
            lock.release()
        return 1

    info = server_info(port) or {}
    if not info.get("ui", True):
        log.error(
            "На порту %s работает сервер без файлов интерфейса (%s). "
            "Установите программу заново или закройте старую копию.",
            port, config.standalone_static_dir(),
        )

    log.info("%s %s запущен", config.APP_NAME, __version__)
    log.info("Интерфейс: %s", url)
    log.info("Отчёты: %s", config.sessions_dir())

    if args.print_url:
        print(url)
    elif cfg.get("open_browser", True) and not args.no_browser:
        open_url(url)

    try:
        while thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        log.info("Остановка…")
        server.should_exit = True
        thread.join(timeout=10)
    finally:
        clear_instance()
        lock.release()
    return 0


if __name__ == "__main__":
    sys.exit(run())
