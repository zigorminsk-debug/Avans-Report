"""Автономная версия: без входа, PDF, сохранение файлов, много одновременных запусков."""

import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
SESSION_A = {"X-Session-Id": "session-aaaaaaaa-1111"}
SESSION_B = {"X-Session-Id": "session-bbbbbbbb-2222"}


@pytest.fixture()
def standalone_env(tmp_path, monkeypatch):
    data = tmp_path / "standalone"
    monkeypatch.setenv("AVANS_STANDALONE_DATA_DIR", str(data))
    monkeypatch.setenv("AVANS_DESKTOP", "1")
    return data


@pytest.fixture()
def client(standalone_env):
    from standalone.server import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def payload(**overrides):
    data = {
        "report_date": "2026-10-26",
        "person_name": "Кухаренко Юлия Владимировна",
        "person_position": "администратор отдела розничной сети",
        "purpose": "Командировочные расходы",
        "advances": [{"date": "2026-10-19", "amount": "99.00"}],
        "expenses": [
            {"date": "22.10.2026", "document": "Проездной билет",
             "document_number": "ЖЕ2110185790394", "purpose": "проезд ЖД", "amount": "28,45"},
            {"date": "23.10.2026", "document": "Платежный документ",
             "document_number": "14935", "purpose": "проезд автобусом", "amount": "35.00"},
        ],
    }
    data.update(overrides)
    return data


def test_no_login_required(client):
    """Никакой авторизации: интерфейс и API доступны сразу."""
    assert client.get("/").status_code == 200
    info = client.get("/api/info", headers=SESSION_A)
    assert info.status_code == 200
    data = info.json()
    assert data["login_required"] is False
    assert data["storage"]["writable"] is True
    assert data["session_id"] == SESSION_A["X-Session-Id"]

    health = client.get("/api/health").json()
    assert health["mode"] == "standalone"
    assert health["app"].startswith("Авансовые отчёты")


def test_save_report_creates_pdf_and_json(client, standalone_env):
    response = client.post("/api/reports", headers=SESSION_A, json=payload())
    assert response.status_code == 201, response.text
    result = response.json()
    number = result["number"]
    assert re.match(r"^АО-2026-\d{4}$", number)
    assert result["report"]["totals"]["spent_cents"] == 6345
    assert result["report"]["amount_words"].startswith("Шестьдесят три рубля")

    folder = standalone_env / "reports" / SESSION_A["X-Session-Id"]
    pdf_path = folder / f"{number}.pdf"
    json_path = folder / f"{number}.json"
    assert pdf_path.exists() and pdf_path.stat().st_size > 5000
    assert json_path.exists()

    stored = json.loads(json_path.read_text(encoding="utf-8"))
    assert stored["number"] == number
    assert stored["totals"]["approved_cents"] == 6345

    pdf_bytes = pdf_path.read_bytes()
    assert pdf_bytes.startswith(b"%PDF")

    listing = client.get("/api/reports", headers=SESSION_A).json()
    assert listing["count"] == 1
    assert listing["items"][0]["has_pdf"] is True
    assert listing["total_cents"] == 6345


def test_pdf_endpoints(client):
    number = client.post("/api/reports", headers=SESSION_A, json=payload()).json()["number"]

    pdf = client.get(f"/api/reports/{number}/pdf", headers=SESSION_A)
    assert pdf.status_code == 200
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")

    download = client.get(f"/api/reports/{number}/pdf?download=1", headers=SESSION_A)
    assert "attachment" in download.headers["content-disposition"]

    prepared = client.post("/api/prepare", headers=SESSION_A, json={"payload": payload()})
    assert prepared.status_code == 200
    assert prepared.json()["report"]["number"]
    generated = client.post("/api/pdf", json=prepared.json()["report"])
    assert generated.status_code == 200
    assert generated.content.startswith(b"%PDF")


def test_pdf_contains_report_text(client):
    pypdf = pytest.importorskip("pypdf")
    import io

    number = client.post("/api/reports", headers=SESSION_A, json=payload()).json()["number"]
    response = client.get(f"/api/reports/{number}/pdf", headers=SESSION_A)
    content = response.content
    text = pypdf.PdfReader(io.BytesIO(content)).pages[0].extract_text()
    assert "Отчет об израсходованных средствах" in text or "Отчет об израсходованных суммах" in text
    # Номер в бланке не печатается (как в форме Excel) — он остаётся только в имени файла.
    assert number not in text
    from urllib.parse import unquote

    assert number in unquote(response.headers["content-disposition"])
    assert "Кухаренко Юлия Владимировна" in text
    assert "28,45" in text
    assert "63,45" in text


def test_numbering_is_per_session_and_sequential(client):
    first = client.post("/api/reports", headers=SESSION_A, json=payload()).json()["number"]
    second = client.post("/api/reports", headers=SESSION_A, json=payload()).json()["number"]
    other = client.post("/api/reports", headers=SESSION_B, json=payload()).json()["number"]

    assert int(first.rsplit("-", 1)[1]) + 1 == int(second.rsplit("-", 1)[1])
    # Другая сессия (другое окно/пользователь) не мешает нумерации
    assert other.endswith("-0001")

    client.delete(f"/api/reports/{second}", headers=SESSION_A)
    third = client.post("/api/reports", headers=SESSION_A, json=payload()).json()["number"]
    assert int(third.rsplit("-", 1)[1]) == int(second.rsplit("-", 1)[1]) + 1


def test_sessions_are_isolated(client):
    client.post("/api/reports", headers=SESSION_A, json=payload())
    client.post("/api/reports", headers=SESSION_A, json=payload())
    listing_b = client.get("/api/reports", headers=SESSION_B).json()
    assert listing_b["count"] == 0
    listing_a = client.get("/api/reports", headers=SESSION_A).json()
    assert listing_a["count"] == 2


def test_delete_report(client, standalone_env):
    number = client.post("/api/reports", headers=SESSION_A, json=payload()).json()["number"]
    folder = standalone_env / "reports" / SESSION_A["X-Session-Id"]
    assert (folder / f"{number}.pdf").exists()

    assert client.delete(f"/api/reports/{number}", headers=SESSION_A).status_code == 200
    assert not (folder / f"{number}.pdf").exists()
    assert not (folder / f"{number}.json").exists()
    assert client.delete(f"/api/reports/{number}", headers=SESSION_A).status_code == 404


def test_settings_roundtrip(client):
    settings = client.get("/api/settings").json()["settings"]
    assert settings["org_name"]
    updated = client.put("/api/settings", json={
        "org_name": 'ООО "Автоном"',
        "director_name": "И.И. Иванов",
        "purposes": ["Командировочные расходы", "Хозяйственные нужды"],
        "default_person_name": "Петров Пётр",
    })
    assert updated.status_code == 200
    assert updated.json()["settings"]["org_name"] == 'ООО "Автоном"'

    report = client.post("/api/reports", headers=SESSION_A, json=payload()).json()["report"]
    assert report["org_name"] == 'ООО "Автоном"'
    assert report["director_name"] == "И.И. Иванов"


def test_validation_errors(client):
    bad = client.post("/api/reports", headers=SESSION_A, json=payload(expenses=[]))
    assert bad.status_code == 422
    bad_advance = client.post("/api/reports", headers=SESSION_A,
                              json=payload(advances=[{"date": "2026-10-19", "amount": "-3"}]))
    assert bad_advance.status_code == 422


def test_concurrent_saves_from_many_windows(client):
    """Несколько одновременных запусков (вкладок) не конфликтуют между собой."""
    from concurrent.futures import ThreadPoolExecutor

    def save(index):
        return client.post("/api/reports", headers=SESSION_A, json=payload())

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(save, range(8)))

    assert all(response.status_code == 201 for response in results), [
        response.text for response in results if response.status_code != 201
    ]
    numbers = sorted(item.json()["number"] for item in results)
    assert len(set(numbers)) == 8, numbers

    listing = client.get("/api/reports", headers=SESSION_A).json()
    assert listing["count"] == 8


def test_client_files_served(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "автономный режим" in index.text.lower()
    assert "/static/app.js" in index.text

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "showDirectoryPicker" in script.text

    shared_css = client.get("/shared/styles.css")
    assert shared_css.status_code == 200
    assert "@page" in shared_css.text

    extra_css = client.get("/static/extra.css")
    assert extra_css.status_code == 200

    favicon = client.get("/favicon.svg")
    assert favicon.status_code == 200


def test_assets_are_cache_busted(client):
    """После обновления программы браузер не должен показывать старый интерфейс."""
    index = client.get("/")
    assert index.status_code == 200
    assert "no-store" in index.headers.get("cache-control", "")
    for asset in ("/static/app.js", "/static/extra.css", "/shared/styles.css"):
        assert f'{asset}?v=' in index.text, f"нет метки версии у {asset}"

    script = client.get("/static/app.js")
    assert "no-cache" in script.headers.get("cache-control", "")
    styles = client.get("/static/extra.css")
    assert "no-cache" in styles.headers.get("cache-control", "")


# ---------------------------------------------------------------------------
# Запуск процесса: один сервер на несколько «запусков» программы
# ---------------------------------------------------------------------------
def _free_port(start=8910, attempts=40):
    for port in range(start, start + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("нет свободного порта")


def _wait_health(url, timeout=25.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/api/health", timeout=1) as response:  # noqa: S310
                payload_json = json.loads(response.read().decode())
                if payload_json.get("mode") == "standalone":
                    return True
        except (urllib.error.URLError, OSError, ValueError):
            time.sleep(0.25)
    return False


@pytest.mark.timeout(120) if hasattr(pytest.mark, "timeout") else (lambda fn: fn)
def test_second_launch_reuses_running_instance(tmp_path):
    """Повторный запуск программы подключается к уже работающему серверу."""
    env = dict(os.environ)
    env["AVANS_STANDALONE_DATA_DIR"] = str(tmp_path / "data")
    env["PYTHONPATH"] = str(ROOT)
    port = _free_port()

    first = subprocess.Popen(
        [sys.executable, "-m", "standalone.launcher", "--port", str(port), "--no-browser",
         "--print-url"],
        cwd=str(ROOT), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    try:
        url = f"http://127.0.0.1:{port}"
        assert _wait_health(url), "первый запуск не поднял сервер"

        # Второй запуск (в том числе с другим портом) должен вернуть адрес работающего сервера
        second = subprocess.run(
            [sys.executable, "-m", "standalone.launcher", "--port", str(port + 1),
             "--no-browser", "--print-url"],
            cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60,
        )
        assert second.returncode == 0, second.stdout + second.stderr
        assert f"127.0.0.1:{port}" in second.stdout, second.stdout

        # Сервер отвечает и обслуживает оба «запуска» одинаково
        with urllib.request.urlopen(url + "/api/info", timeout=5) as response:  # noqa: S310
            info = json.loads(response.read().decode())
        assert info["login_required"] is False
    finally:
        first.terminate()
        try:
            first.wait(timeout=15)
        except subprocess.TimeoutExpired:  # pragma: no cover
            first.kill()


def test_packaging_assets_for_standalone():
    assert (ROOT / "desktop" / "AvansStandalone.spec").exists()
    assert (ROOT / "installer" / "windows" / "AvansStandalone.iss").exists()
    assert (ROOT / "standalone" / "static" / "index.html").exists()
    spec = (ROOT / "desktop" / "AvansStandalone.spec").read_text(encoding="utf-8")
    assert "launcher.py" in spec
    assert "fonts" in spec
    iss = (ROOT / "installer" / "windows" / "AvansStandalone.iss").read_text(encoding="utf-8")
    assert "APP_VERSION" in iss
    assert "AvansStandalone" in iss


def test_standalone_ui_has_no_saved_reports_section():
    """В автономной версии нет раздела «Сохранённые отчёты» — только форма и настройки."""
    js = (ROOT / "standalone" / "static" / "app.js").read_text(encoding="utf-8")

    assert "renderSaved" not in js
    assert "Сохранённые отчёты" not in js
    assert len(re.findall(r"href: '#/", js)) == 3  # отчёт, инструкция, настройки


def test_standalone_has_user_guide():
    """В программе есть раздел «Инструкция» с порядком работы и печатью."""
    js = (ROOT / "standalone" / "static" / "app.js").read_text(encoding="utf-8")

    assert "{ href: '#/help'" in js
    assert "renderHelp" in js
    assert "Инструкция по работе с программой" in js
    assert "printHelp" in js
    for step in ("Как заполнить отчёт", "Печать и PDF",
                 "Несколько окон одновременно", "Где лежат сохранённые отчёты",
                 "Если что-то не работает"):
        assert step in js, step


def test_standalone_ui_shows_developer_contacts():
    js = (ROOT / "standalone" / "static" / "app.js").read_text(encoding="utf-8")
    assert "Zakharevich Igor" in js
    assert "ziv@csl.by" in js
    assert "+375293371412" in js


def test_standalone_ui_uses_company_site_style():
    css = (ROOT / "standalone" / "static" / "extra.css").read_text(encoding="utf-8").lower()
    assert "#ca1616" in css        # красный акцент sm-group.by
    assert "tahoma" in css         # шрифт сайта
    assert "site-head" in css and "site-foot" in css


def test_ui_posts_when_request_has_body():
    """GET с телом браузер отклоняет — печать и предпросмотр из-за этого падали."""
    js = (ROOT / "standalone" / "static" / "app.js").read_text(encoding="utf-8")

    assert "opts.method || (body !== undefined && body !== null ? 'POST' : 'GET')" in js
    assert js.count("api('/api/prepare'") == js.count("api('/api/prepare', { method: 'POST'")
    for call in js.split("api('/api/prepare'")[1:]:
        assert call.lstrip().startswith(", { method: 'POST'"), call[:80]


def test_printed_form_has_no_report_number():
    """В шапке бланка номера нет, дата по центру — как в форме Excel."""
    for path in ("standalone/static/app.js", "app/static/app.js"):
        js = (ROOT / path).read_text(encoding="utf-8")
        assert "doc-no" not in js, path
        assert "Сформирован " in js, path

    css = (ROOT / "app" / "static" / "styles.css").read_text(encoding="utf-8")
    datebar = [line for line in css.splitlines() if line.startswith(".doc-datebar {")][0]
    assert "justify-content: center" in datebar

    pdf = (ROOT / "app" / "pdf_export.py").read_text(encoding="utf-8")
    assert 'f"№ {report.get(' not in pdf          # номер не в шапке
    assert 'f"Отчёт № {report.get(' not in pdf    # и не в подписи бланка


def test_ui_can_print_without_saving():
    """Печать бланка доступна без сохранения отчёта и подгоняется под лист A4."""
    js = (ROOT / "standalone" / "static" / "app.js").read_text(encoding="utf-8")

    assert "Печать без сохранения" in js
    assert "async function printDraft" in js
    assert "draftAsIs" in js
    assert "@page{size:A4" in js
    assert "sheet.style.zoom" in js          # подгонка под одну страницу
    assert "event.key.toLowerCase() === 'p'" in js  # Ctrl+P печатает бланк


def test_standalone_installer_has_no_reports_shortcut():
    """В автономной версии нет ярлыка «Каталог отчётов» и запуска папки отчётов."""
    iss = (ROOT / "installer" / "windows" / "AvansStandalone.iss").read_text(encoding="utf-8")

    assert 'Name: "{group}\\Каталог отчётов"' not in iss
    assert "--open-data-dir" not in iss
    assert 'Name: "{group}\\{#MyAppShortName}"' in iss  # ярлык самой программы остаётся


def test_reports_folder_is_created_only_on_save(tmp_path, monkeypatch):
    """Папка отчётов не появляется при запуске — только после сохранения."""
    from standalone import config, storage

    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path / "data"))
    config.data_dir()  # корень данных создаётся

    assert not config.sessions_dir().exists()
    assert not config.session_dir("20260101-000000-abc").exists()
    assert storage.list_reports(config.sessions_dir()) == []
    assert storage.cleanup_old_sessions(30) == 0
    assert not config.sessions_dir().exists()

    from app.reports import ReportIn

    folder = config.session_dir("20260101-000000-abc")
    data = ReportIn(
        report_date="2026-01-01",
        person_name="Тестов Тест Тестович",
        purpose="Командировочные расходы",
        advances=[{"date": "2026-01-01", "amount": "1000"}],
        expenses=[{"date": "01.01.2026", "document": "Чек", "purpose": "проезд",
                   "amount": "500"}],
    )
    storage.save_new_report(folder, data, dict(config.DEFAULT_SETTINGS), 2026)

    assert config.sessions_dir().is_dir()
    assert folder.is_dir()


def test_health_reports_ui_availability(client):
    """По /api/health видно, есть ли у процесса файлы интерфейса."""
    health = client.get("/api/health").json()
    assert health["ui"] is True
    assert health["version"]


def test_launcher_rejects_foreign_or_old_instance():
    """Старую копию после обновления нельзя переиспользовать."""
    from app.version import __version__
    from standalone import launcher

    ok = {"version": __version__, "ui": True, "mode": "standalone"}
    assert launcher.is_usable_instance(ok)
    assert not launcher.is_usable_instance({**ok, "version": "1.0.2"})
    assert not launcher.is_usable_instance({**ok, "ui": False})
    assert not launcher.is_usable_instance({})


def test_choosing_port_skips_busy_one():
    """Порт, на котором кто-то слушает, не выбирается."""
    import socket

    from standalone import launcher

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        busy = sock.getsockname()[1]
        assert launcher.port_answers(busy)
        assert not launcher.port_available(busy)
        chosen = launcher.choose_port(busy, attempts=5)
        assert chosen != busy


def test_missing_ui_page_is_explained(client, monkeypatch, tmp_path):
    """Если файлы интерфейса пропали, вместо JSON показывается объяснение."""
    from standalone import config, server

    monkeypatch.setattr(config, "standalone_static_dir", lambda: tmp_path / "нет")
    monkeypatch.setattr(server, "config", config)

    response = client.get("/")
    assert response.status_code == 500
    assert "Файлы интерфейса не найдены" in response.text
    assert "установите программу заново" in response.text.lower()


def json_loads(text):
    import json as _json
    return _json.loads(text)


def test_instance_file_is_written_atomically(tmp_path, monkeypatch):
    from standalone import config, launcher

    monkeypatch.setenv(config.ENV_DATA_DIR, str(tmp_path / "data"))
    launcher.write_instance(8899)
    payload = json_loads((config.instance_path()).read_text(encoding="utf-8"))
    assert payload["port"] == 8899
    assert payload["version"]
    assert not config.instance_path().with_suffix(".json.part").exists()


def test_instance_problem_explains_reason():
    from app.version import __version__
    from standalone import launcher

    base = {"version": __version__, "ui": True, "data_dir": "/data"}
    assert launcher.instance_problem(base, "/data") is None
    assert "версия" in launcher.instance_problem({**base, "version": "1.0.2"}, "/data")
    assert "каталог" in launcher.instance_problem(base, "/other")
    assert "интерфейс" in launcher.instance_problem({**base, "ui": False}, "/data")
