import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ADMIN = {"username": "admin", "password": "Admin12345", "full_name": "Администратор Системы"}


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    path = tmp_path / "data"
    monkeypatch.setenv("AVANS_DATA_DIR", str(path))
    monkeypatch.setenv("AVANS_DESKTOP", "1")
    from app import db

    db.init_db()
    return path


@pytest.fixture()
def client(data_dir):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


def setup_admin(client):
    response = client.post("/api/setup", json=ADMIN)
    assert response.status_code == 200, response.text
    data = response.json()
    return data["token"], data["user"]


def login(client, username, password):
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def create_user(client, token, username, role="user", password="Passw0rd123",
                full_name="Тестовый Пользователь", position="", email=""):
    response = client.post(
        "/api/users",
        headers=auth(token),
        json={
            "username": username,
            "password": password,
            "full_name": full_name,
            "position": position,
            "email": email,
            "role": role,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["user"]


def report_payload(**overrides):
    payload = {
        "report_date": "2026-10-26",
        "person_name": "Кухаренко Юлия Владимировна",
        "person_position": "администратор отдела розничной сети",
        "purpose": "Командировочные расходы",
        "advances": [{"date": "2026-10-19", "amount": "99.00"}],
        "expenses": [
            {
                "date": "22.10.2026-23.10.2026",
                "document": "",
                "document_number": "",
                "purpose": "суточные, г. Минск, 2 сут.",
                "amount": "26,00",
            },
            {
                "date": "22.10.2026",
                "document": "Проездной билет",
                "document_number": "ЖЕ2110185790394",
                "purpose": "проезд ЖД, Витебск-Минск",
                "amount": "28.45",
            },
            {
                "date": "23.10.2026",
                "document": "Платёжный документ",
                "document_number": "14935",
                "purpose": "проезд, Минск-Витебск",
                "amount": 35,
            },
        ],
    }
    payload.update(overrides)
    return payload


def create_report(client, token, **overrides):
    response = client.post("/api/reports", headers=auth(token), json=report_payload(**overrides))
    assert response.status_code == 201, response.text
    return response.json()
