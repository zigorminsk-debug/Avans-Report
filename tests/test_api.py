import sqlite3

import pytest
from conftest import ADMIN, auth, create_report, create_user, login, report_payload, setup_admin


def test_health_and_public_info(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    info = client.get("/api/public/info").json()
    assert info["needs_setup"] is True
    assert info["app_name"]


def test_setup_flow(client):
    weak = client.post("/api/setup", json={**ADMIN, "password": "123"})
    assert weak.status_code == 422

    token, user = setup_admin(client)
    assert user["role"] == "admin"
    assert client.get("/api/public/info").json()["needs_setup"] is False

    again = client.post("/api/setup", json=ADMIN)
    assert again.status_code == 409

    bad = client.post("/api/auth/login", json={"username": ADMIN["username"], "password": "nope"})
    assert bad.status_code == 401

    ok = client.post("/api/auth/login", json={"username": ADMIN["username"], "password": ADMIN["password"]})
    assert ok.status_code == 200
    me = client.get("/api/auth/me", headers=auth(token)).json()
    assert me["user"]["username"] == "admin"


def test_report_lifecycle_and_totals(client):
    token, _ = setup_admin(client)
    report = create_report(client, token)
    totals = report["totals"]
    assert totals["received_cents"] == 9900
    assert totals["spent_cents"] == 8945
    assert totals["balance_cents"] == 955
    assert report["number"].startswith("АО-2026-")
    assert report["amount_words"].startswith("Восемьдесят девять рублей")
    assert len(report["expenses"]) == 3

    fetched = client.get(f"/api/reports/{report['id']}", headers=auth(token))
    assert fetched.status_code == 200
    assert fetched.json()["expenses"][1]["document"] == "Проездной билет"

    listing = client.get("/api/reports", headers=auth(token)).json()
    assert listing["total"] == 1
    assert listing["items"][0]["totals"]["approved_cents"] == 8945


@pytest.mark.parametrize(
    "overrides",
    [
        {"expenses": []},
        {"advances": [{"date": "2026-10-19", "amount": "-5"}]},
        {"purpose": ""},
        {"report_date": "not-a-date"},
        {"expenses": [{"date": "01.01.2026", "purpose": "x", "amount": "-5"}]},
        {"expenses": [{"date": "", "purpose": "x", "amount": "10"}]},
        {"expenses": [{"date": "01.01.2026", "purpose": "", "amount": "10"}]},
        {"expenses": [{"date": "01.01.2026", "purpose": "x", "amount": "10"}] * 11},
    ],
)
def test_report_validation_errors(client, overrides):
    token, _ = setup_admin(client)
    response = client.post("/api/reports", headers=auth(token), json=report_payload(**overrides))
    assert response.status_code == 422, response.text


def test_saved_report_cannot_be_modified(client, data_dir):
    token, _ = setup_admin(client)
    report = create_report(client, token)

    # Нет HTTP-метода для изменения отчёта
    for method in ("put", "patch"):
        response = getattr(client, method)(f"/api/reports/{report['id']}", json={"purpose": "new"})
        assert response.status_code in (404, 405)

    # И на уровне базы данных изменение запрещено триггером
    from app.config import db_path

    connection = sqlite3.connect(db_path())
    try:
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("UPDATE reports SET purpose = 'changed' WHERE id = ?", (report["id"],))
            connection.commit()
    finally:
        connection.close()


def test_role_permissions(client):
    admin_token, _ = setup_admin(client)
    create_user(client, admin_token, "super1", role="supervisor", full_name="Супервайзер Один")
    create_user(client, admin_token, "user1", role="user", full_name="Пользователь Один")
    super_token = login(client, "super1", "Passw0rd123")
    user_token = login(client, "user1", "Passw0rd123")

    user_report = create_report(client, user_token)
    admin_report = create_report(client, admin_token, person_name="Администратор Отчётович")

    user_list = client.get("/api/reports", headers=auth(user_token)).json()
    assert user_list["total"] == 1
    assert user_list["items"][0]["id"] == user_report["id"]

    super_list = client.get("/api/reports", headers=auth(super_token)).json()
    assert super_list["total"] == 2
    assert super_list["scope"] == "all"

    # Чужой отчёт недоступен обычному пользователю
    forbidden = client.get(f"/api/reports/{admin_report['id']}", headers=auth(user_token))
    assert forbidden.status_code == 403
    excel_forbidden = client.get(f"/api/reports/{admin_report['id']}/excel", headers=auth(user_token))
    assert excel_forbidden.status_code == 403

    # Удалять может только администратор
    assert client.delete(f"/api/reports/{user_report['id']}", headers=auth(user_token)).status_code == 403
    assert client.delete(f"/api/reports/{user_report['id']}", headers=auth(super_token)).status_code == 403
    assert client.delete(f"/api/reports/{user_report['id']}", headers=auth(admin_token)).status_code == 200
    assert client.get(f"/api/reports/{user_report['id']}", headers=auth(admin_token)).status_code == 404

    # Пользователи: создаёт администратор и супервайзер
    assert client.post(
        "/api/users",
        headers=auth(user_token),
        json={"username": "hacker", "password": "Passw0rd123", "full_name": "Хакер Хакерович", "role": "user"},
    ).status_code == 403

    created = client.post(
        "/api/users",
        headers=auth(super_token),
        json={"username": "user2", "password": "Passw0rd123", "full_name": "Второй Пользователь", "role": "user"},
    )
    assert created.status_code == 201
    assert created.json()["user"]["must_change_password"] is True

    escalated = client.post(
        "/api/users",
        headers=auth(super_token),
        json={"username": "user3", "password": "Passw0rd123", "full_name": "Третий Пользователь", "role": "admin"},
    )
    assert escalated.status_code == 403

    # Супервайзер может задать пароль обычному пользователю, но не менять его данные
    user2_id = created.json()["user"]["id"]
    assert client.patch(
        f"/api/users/{user2_id}", headers=auth(super_token), json={"password": "NewPassw0rd"}
    ).status_code == 200
    assert client.patch(
        f"/api/users/{user2_id}", headers=auth(super_token), json={"full_name": "Другое Имя"}
    ).status_code == 403

    # Доступ к настройкам только у администратора
    assert client.get("/api/settings", headers=auth(super_token)).status_code == 403
    assert client.get("/api/settings", headers=auth(admin_token)).status_code == 200


def test_user_blocking_and_deletion_rules(client):
    admin_token, admin_user = setup_admin(client)
    user = create_user(client, admin_token, "worker", full_name="Работник Работникович")
    user_token = login(client, "worker", "Passw0rd123")
    create_report(client, user_token)

    # Пользователя с отчётами удалить нельзя
    blocked_delete = client.delete(f"/api/users/{user['id']}", headers=auth(admin_token))
    assert blocked_delete.status_code == 409

    # Блокировка закрывает доступ
    patched = client.patch(f"/api/users/{user['id']}", headers=auth(admin_token), json={"is_active": False})
    assert patched.status_code == 200
    assert client.get("/api/reports", headers=auth(user_token)).status_code == 401
    blocked_login = client.post(
        "/api/auth/login", json={"username": "worker", "password": "Passw0rd123"}
    )
    assert blocked_login.status_code == 403

    # Нельзя заблокировать или удалить самого себя
    assert client.patch(
        f"/api/users/{admin_user['id']}", headers=auth(admin_token), json={"is_active": False}
    ).status_code == 422
    assert client.delete(f"/api/users/{admin_user['id']}", headers=auth(admin_token)).status_code == 422


def test_password_change_and_sessions(client):
    token, _ = setup_admin(client)
    create_user(client, token, "user1", full_name="Пользователь Один")
    user_token = login(client, "user1", "Passw0rd123")

    assert client.post(
        "/api/auth/change-password",
        headers=auth(user_token),
        json={"current_password": "wrong", "new_password": "NewPassw0rd1"},
    ).status_code == 400
    changed = client.post(
        "/api/auth/change-password",
        headers=auth(user_token),
        json={"current_password": "Passw0rd123", "new_password": "NewPassw0rd1"},
    )
    assert changed.status_code == 200
    assert login(client, "user1", "NewPassw0rd1")
    assert client.post(
        "/api/auth/login", json={"username": "user1", "password": "Passw0rd123"}
    ).status_code == 401


def test_settings_and_smtp(client, monkeypatch):
    token, _ = setup_admin(client)
    payload = {
        "org_name": 'ООО "Тест"',
        "director_position": "Директор",
        "director_name": "И.И. Иванов",
        "accountant_position": "Бухгалтер",
        "accountant_name": "П.П. Петрова",
        "default_recipient": "boss@example.com",
        "purposes": ["Командировочные расходы"],
        "session_hours": 12,
        "smtp": {
            "host": "smtp.example.com",
            "port": 587,
            "security": "starttls",
            "username": "reports@example.com",
            "password": "secret",
            "from_email": "reports@example.com",
            "from_name": "Авансовые отчёты",
            "subject_prefix": "Авансовый отчёт",
        },
    }
    saved = client.put("/api/settings", headers=auth(token), json=payload)
    assert saved.status_code == 200

    current = client.get("/api/settings", headers=auth(token)).json()["settings"]
    assert current["org_name"] == 'ООО "Тест"'
    assert current["smtp"]["password_set"] is True
    assert "password" not in current["smtp"]

    # Пустой пароль при повторном сохранении не затирает прежний
    payload["smtp"]["password"] = ""
    payload["org_name"] = 'ООО "Тест 2"'
    assert client.put("/api/settings", headers=auth(token), json=payload).status_code == 200
    assert client.get("/api/settings", headers=auth(token)).json()["settings"]["smtp"]["password_set"] is True

    report = create_report(client, token)
    assert report["org_name"] == 'ООО "Тест 2"'

    sent = {}

    def fake_send(settings, report_data, recipients, comment):
        sent["recipients"] = recipients
        sent["comment"] = comment
        sent["number"] = report_data["number"]

    monkeypatch.setattr("app.emailer.send_report", fake_send)
    response = client.post(
        f"/api/reports/{report['id']}/email",
        headers=auth(token),
        json={"to": "boss@example.com, hr@example.com", "comment": "Прошу утвердить"},
    )
    assert response.status_code == 200, response.text
    assert sent["recipients"] == ["boss@example.com", "hr@example.com"]
    assert sent["comment"] == "Прошу утвердить"
    assert sent["number"] == report["number"]
    updated = response.json()["report"]
    assert updated["status"] == "sent"
    assert updated["sent_at"]
    assert "boss@example.com" in updated["sent_to"]

    # Ошибка SMTP сохраняется в отчёте, но не роняет сервер
    def failing_send(*args, **kwargs):
        from app.emailer import EmailError

        raise EmailError("SMTP недоступен")

    monkeypatch.setattr("app.emailer.send_report", failing_send)
    failed = client.post(
        f"/api/reports/{report['id']}/email", headers=auth(token), json={"to": "boss@example.com"}
    )
    assert failed.status_code == 502
    failed_report = client.get(f"/api/reports/{report['id']}", headers=auth(token)).json()
    assert failed_report["email_status"].startswith("error")


def test_email_requires_smtp_settings(client):
    token, _ = setup_admin(client)
    report = create_report(client, token)
    response = client.post(
        f"/api/reports/{report['id']}/email", headers=auth(token), json={"to": "boss@example.com"}
    )
    assert response.status_code == 400
    assert "SMTP" in response.json()["detail"]


def test_report_numbering_is_sequential(client):
    token, _ = setup_admin(client)
    first = create_report(client, token)
    second = create_report(client, token)
    assert first["number"] != second["number"]
    first_index = int(first["number"].rsplit("-", 1)[1])
    second_index = int(second["number"].rsplit("-", 1)[1])
    assert second_index == first_index + 1

    # Номер не переиспользуется после удаления
    assert client.delete(f"/api/reports/{first['id']}", headers=auth(token)).status_code == 200
    third = create_report(client, token)
    assert int(third["number"].rsplit("-", 1)[1]) == second_index + 1


def test_backup_and_system_info(client, data_dir):
    token, _ = setup_admin(client)
    info = client.get("/api/system/info", headers=auth(token)).json()
    assert info["counts"]["users"] == 1
    assert info["db_path"].endswith("avans.db")

    created = client.post("/api/system/backup", headers=auth(token))
    assert created.status_code == 200
    backup_file = data_dir / "backups" / created.json()["file"]
    assert backup_file.exists()
    assert backup_file.stat().st_size > 0

    download = client.get("/api/system/backup/download", headers=auth(token))
    assert download.status_code == 200
    assert download.content[:15] == b"SQLite format 3"

    audit = client.get("/api/audit", headers=auth(token)).json()
    assert any(item["action"] == "setup" for item in audit["items"])


def test_data_survives_restart(data_dir):
    """Имитация обновления программы: база данных остаётся на месте."""
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as first_client:
        token, _ = setup_admin(first_client)
        report = create_report(first_client, token)

    with TestClient(create_app()) as second_client:
        login_token = login(second_client, ADMIN["username"], ADMIN["password"])
        listing = second_client.get("/api/reports", headers=auth(login_token)).json()
        assert listing["total"] == 1
        assert listing["items"][0]["id"] == report["id"]


def test_update_check(client, monkeypatch):
    token, _ = setup_admin(client)

    def fake_request(url, timeout=10):
        return {
            "tag_name": "v9.9.9",
            "name": "Версия 9.9.9",
            "body": "Новые возможности",
            "html_url": "https://github.com/example/releases/tag/v9.9.9",
            "published_at": "2026-01-01T00:00:00Z",
            "assets": [
                {
                    "name": "AvansReport-Setup-9.9.9.exe",
                    "size": 12345678,
                    "browser_download_url": "https://github.com/example/AvansReport-Setup-9.9.9.exe",
                }
            ],
        }

    monkeypatch.setattr("app.updates._request_json", fake_request)
    info = client.get("/api/update/check?force=1", headers=auth(token)).json()
    assert info["latest_version"] == "9.9.9"
    assert info["update_available"] is True
    assert info["assets"]["windows_installer"]["name"] == "AvansReport-Setup-9.9.9.exe"
    assert info["can_install"] is False or isinstance(info["can_install"], bool)
    assert info["release_notes"] == "Новые возможности"

    monkeypatch.setattr("app.updates._request_json", lambda *a, **k: {"tag_name": "v0.0.1"})
    info = client.get("/api/update/check?force=1", headers=auth(token)).json()
    assert info["update_available"] is False


def test_unauthenticated_access_denied(client):
    assert client.get("/api/reports").status_code == 401
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/settings").status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_login_throttle(client):
    admin_token, _ = setup_admin(client)
    create_user_name = "throttle_user"
    create_user(client, admin_token, create_user_name, full_name="Троттл Пользователь")
    for _ in range(10):
        response = client.post(
            "/api/auth/login", json={"username": create_user_name, "password": "wrong-pass1"}
        )
        assert response.status_code == 401
    blocked = client.post(
        "/api/auth/login", json={"username": create_user_name, "password": "Passw0rd123"}
    )
    assert blocked.status_code == 429
