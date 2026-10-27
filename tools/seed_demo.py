#!/usr/bin/env python3
"""Наполнение демонстрационной базы (для проверки интерфейса и обучения).

Пример:
    python desktop/launcher.py --host 127.0.0.1 --port 8770 --no-browser &
    python tools/seed_demo.py --url http://127.0.0.1:8770

Скрипт создаёт администратора, супервайзера и двух сотрудников с отчётами.
Повторный запуск на уже настроенной базе пропускается (кроме добавления отчётов).
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

HEADERS = {"Content-Type": "application/json"}


def call(base: str, path: str, method: str = "GET", body: Any = None,
         token: Optional[str] = None) -> Tuple[int, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(base + path, data=data, method=method)
    request.add_header("Content-Type", "application/json")
    if token:
        request.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(raw) if raw else {}
        except ValueError:
            return exc.code, {"detail": raw}


USERS = [
    {
        "username": "supervisor",
        "password": "Super12345",
        "full_name": "Иванова Мария Петровна",
        "position": "Начальник отдела",
        "email": "ivanova@example.com",
        "role": "supervisor",
    },
    {
        "username": "kuharenko",
        "password": "User12345",
        "full_name": "Кухаренко Юлия Владимировна",
        "position": "администратор отдела собственной розничной сети в г. Витебск",
        "email": "kuharenko@example.com",
        "role": "user",
    },
    {
        "username": "petrov",
        "password": "User12345",
        "full_name": "Петров Сергей Николаевич",
        "position": "менеджер по закупкам",
        "email": "petrov@example.com",
        "role": "user",
    },
]

REPORTS = [
    (
        "kuharenko",
        "User12345",
        {
            "report_date": "2026-10-26",
            "person_name": "Кухаренко Юлия Владимировна",
            "person_position": "администратор отдела собственной розничной сети в г. Витебск",
            "purpose": "Командировочные расходы",
            "advances": [{"date": "2026-10-19", "amount": "99.00"}],
            "expenses": [
                {
                    "date": "22.10.2026-23.10.2026",
                    "document": "",
                    "document_number": "",
                    "purpose": "суточные, 22.10.2026 - 23.10.2026, г. Минск, 2 сут.",
                    "amount": "26.00",
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
                    "document": "Платежный документ",
                    "document_number": "14935",
                    "purpose": 'проезд, Минск-Витебск, ООО "Юнибусбел"',
                    "amount": "35.00",
                },
            ],
        },
    ),
    (
        "kuharenko",
        "User12345",
        {
            "report_date": "2026-09-14",
            "person_name": "Кухаренко Юлия Владимировна",
            "person_position": "администратор отдела собственной розничной сети в г. Витебск",
            "purpose": "Расходы на хозяйственные нужды",
            "advances": [{"date": "2026-09-08", "amount": "150.00"}],
            "expenses": [
                {
                    "date": "10.09.2026",
                    "document": "Чек",
                    "document_number": "1546897",
                    "purpose": "Белоруснефть, АИ-95, АЗС №1111",
                    "amount": "145.69",
                }
            ],
        },
    ),
    (
        "petrov",
        "User12345",
        {
            "report_date": "2026-10-12",
            "person_name": "Петров Сергей Николаевич",
            "person_position": "менеджер по закупкам",
            "purpose": "Командировочные расходы",
            "advances": [{"date": "2026-10-06", "amount": "300.00"}],
            "expenses": [
                {
                    "date": "07.10.2026",
                    "document": "Счёт-фактура",
                    "document_number": "СФ-1024",
                    "purpose": "Гостиница «Планета», 1 сутки",
                    "amount": "180.00",
                },
                {
                    "date": "08.10.2026",
                    "document": "Проездной билет",
                    "document_number": "АВ2210456",
                    "purpose": "проезд, Минск-Гомель",
                    "amount": "42.50",
                },
            ],
        },
    ),
]


def login(base: str, username: str, password: str) -> str:
    status, payload = call(base, "/api/auth/login", "POST",
                           {"username": username, "password": password})
    if status != 200:
        raise SystemExit(f"Не удалось войти как {username}: {payload}")
    return payload["token"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Демонстрационные данные")
    parser.add_argument("--url", default="http://127.0.0.1:8770")
    parser.add_argument("--smtp-host", default="", help="SMTP-сервер для демонстрации отправки")
    parser.add_argument("--smtp-port", type=int, default=1025)
    parser.add_argument("--send-email", action="store_true", help="отправить первый отчёт по почте")
    args = parser.parse_args(argv)

    base = args.url.rstrip("/")
    status, info = call(base, "/api/public/info")
    if status != 200:
        raise SystemExit("Сервер недоступен: " + json.dumps(info, ensure_ascii=False))

    if info.get("needs_setup"):
        status, admin = call(base, "/api/setup", "POST", {
            "username": "admin",
            "password": "Admin12345",
            "full_name": "Сашко Наталья Викторовна",
            "org_name": 'ООО "Сэйлз Модерн групп"',
        })
        if status != 200:
            raise SystemExit("Ошибка первичной настройки: " + json.dumps(admin, ensure_ascii=False))
        print("Создан администратор: admin / Admin12345")
    else:
        print("Программа уже настроена — добавляем данные")

    admin_token = login(base, "admin", "Admin12345")

    smtp = {
        "host": args.smtp_host,
        "port": args.smtp_port,
        "security": "none" if args.smtp_host else "starttls",
        "username": "",
        "password": "",
        "from_email": "reports@example.com" if args.smtp_host else "",
        "from_name": "Авансовые отчёты",
        "subject_prefix": "Авансовый отчёт",
    }
    status, _ = call(base, "/api/settings", "PUT", {
        "org_name": 'ООО "Сэйлз Модерн групп"',
        "director_position": "Директор",
        "director_name": "Н.В. Сашко",
        "accountant_position": "Бухгалтер",
        "accountant_name": "Е.А. Сидорова",
        "default_recipient": "accounting@example.com",
        "purposes": ["Командировочные расходы", "Расходы на хозяйственные нужды"],
        "session_hours": 12,
        "smtp": smtp,
    }, admin_token)
    print("Настройки обновлены (SMTP:", args.smtp_host or "не настроен", ")")

    for user in USERS:
        status, payload = call(base, "/api/users", "POST", user, admin_token)
        if status == 201:
            print(f"Создан пользователь {user['username']} (пароль {user['password']})")
        elif status == 409:
            print(f"Пользователь {user['username']} уже есть")
        else:
            print(f"Ошибка создания {user['username']}: {payload}")

    created = []
    for username, password, payload in REPORTS:
        token = login(base, username, password)
        status, report = call(base, "/api/reports", "POST", payload, token)
        if status == 201:
            created.append((username, token, report))
            print(f"Создан отчёт {report['number']} для {username}")
        else:
            print(f"Ошибка создания отчёта: {report}")

    if args.send_email and created:
        username, token, report = created[0]
        status, payload = call(base, f"/api/reports/{report['id']}/email", "POST",
                               {"to": "accounting@example.com", "comment": "Прошу утвердить отчёт"},
                               token)
        print("Отправка по почте:", status, payload.get("detail", "отправлено"))

    print("\nГотово. Вход в демонстрационную версию:")
    print("  admin      / Admin12345   — администратор")
    print("  supervisor / Super12345   — супервайзер (видит все отчёты)")
    print("  kuharenko  / User12345    — пользователь")
    print("  petrov     / User12345    — пользователь")
    return 0


if __name__ == "__main__":
    sys.exit(main())
