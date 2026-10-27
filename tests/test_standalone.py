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
    content = client.get(f"/api/reports/{number}/pdf", headers=SESSION_A).content
    text = pypdf.PdfReader(io.BytesIO(content)).pages[0].extract_text()
    assert "Отчет об израсходованных средствах" in text or "Отчет об израсходованных суммах" in text
    assert number in text
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
    assert len(re.findall(r"href: '#/", js)) == 2  # «Новый отчёт» и «Настройки»


def test_standalone_ui_shows_developer_contacts():
    js = (ROOT / "standalone" / "static" / "app.js").read_text(encoding="utf-8")
    assert "Zakharevuch Igor" in js
    assert "ziv@csl.by" in js
    assert "+375293371412" in js


def test_standalone_ui_uses_company_site_style():
    css = (ROOT / "standalone" / "static" / "extra.css").read_text(encoding="utf-8").lower()
    assert "#ca1616" in css        # красный акцент sm-group.by
    assert "tahoma" in css         # шрифт сайта
    assert "site-head" in css and "site-foot" in css
