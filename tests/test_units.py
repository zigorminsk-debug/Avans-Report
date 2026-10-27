from decimal import Decimal

import pytest

from app import updates
from app.numberwords import amount_in_words, format_money, to_cents


@pytest.mark.parametrize(
    "cents,expected",
    [
        (0, "Ноль рублей 00 копеек"),
        (100, "Один рубль 00 копеек"),
        (200, "Два рубля 00 копеек"),
        (500, "Пять рублей 00 копеек"),
        (1100, "Одиннадцать рублей 00 копеек"),
        (2100, "Двадцать один рубль 00 копеек"),
        (2200, "Двадцать два рубля 00 копеек"),
        (2500, "Двадцать пять рублей 00 копеек"),
        (8945, "Восемьдесят девять рублей 45 копеек"),
        (100000, "Одна тысяча рублей 00 копеек"),
        (200000, "Две тысячи рублей 00 копеек"),
        (500000, "Пять тысяч рублей 00 копеек"),
        (123456789, "Один миллион двести тридцать четыре тысячи пятьсот шестьдесят семь рублей 89 копеек"),
        (1, "Ноль рублей 01 копейка"),
        (102, "Один рубль 02 копейки"),
    ],
)
def test_amount_in_words(cents, expected):
    assert amount_in_words(cents) == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("99", 9900),
        ("99,5", 9950),
        ("99.50", 9950),
        (" 1 234,56 ", 123456),
        (Decimal("28.45"), 2845),
        (35, 3500),
        ("", 0),
        (None, 0),
        (0, 0),
    ],
)
def test_to_cents(value, expected):
    assert to_cents(value) == expected


def test_format_money():
    assert format_money(123456) == "1 234,56"
    assert format_money(5) == "0,05"
    assert format_money(-1050) == "-10,50"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("1.0.0", (1, 0, 0)),
        ("v1.2.3", (1, 2, 3)),
        ("1.2", (1, 2, 0)),
        ("2", (2, 0, 0)),
    ],
)
def test_parse_version(value, expected):
    assert updates.parse_version(value) == expected


def test_is_newer():
    assert updates.is_newer("1.2.0", "1.1.9")
    assert updates.is_newer("v2.0.0", "1.99.99")
    assert not updates.is_newer("1.0.0", "1.0.0")
    assert not updates.is_newer("0.9.9", "1.0.0")


def test_recipients_parsing():
    from app.emailer import EmailError, parse_recipients

    assert parse_recipients("a@b.ru, c@d.ru") == ["a@b.ru", "c@d.ru"]
    assert parse_recipients("a@b.ru; c@d.ru") == ["a@b.ru", "c@d.ru"]
    with pytest.raises(EmailError):
        parse_recipients("not-an-email")
    with pytest.raises(EmailError):
        parse_recipients("")


def test_password_hash_roundtrip():
    from app.security import hash_password, verify_password

    stored = hash_password("Passw0rd123")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("Passw0rd123", stored)
    assert not verify_password("wrong-password", stored)
    assert not verify_password("Passw0rd123", "broken-hash")


def test_password_policy():
    from app.security import PasswordPolicyError, validate_password, validate_username

    with pytest.raises(PasswordPolicyError):
        validate_password("short")
    with pytest.raises(PasswordPolicyError):
        validate_password("12345678")
    with pytest.raises(PasswordPolicyError):
        validate_password("abcdefgh")
    with pytest.raises(PasswordPolicyError):
        validate_username("пользователь")
    assert validate_username("Ivanov.1") == "ivanov.1"


def _printed_report(**over):
    from app import pdf_export
    from app.reports import ReportIn
    from standalone import config, storage

    data = {
        "report_date": "2026-10-26",
        "person_name": "Кухаренко Юлия Владимировна",
        "person_position": "администратор отдела розничной сети и развития региональных продаж",
        "purpose": "Командировочные расходы на поездку в г. Гомель для переговоров с клиентом",
        "advances": [{"date": "2026-10-19", "amount": "1000.00"}],
        "expenses": [{"date": "22.10.2026", "document": "Чек", "document_number": "1",
                      "purpose": "проезд", "amount": "100.00"}],
    }
    data.update(over)
    report = storage.build_report(ReportIn(**data), dict(config.DEFAULT_SETTINGS), "АО-2026-0001")
    return pdf_export.build_report_pdf(storage.stamp(report))


def _pdf_pages(content: bytes) -> int:
    """Число страниц PDF без внешних зависимостей."""
    import re

    counts = [int(m.group(1)) for m in re.finditer(rb"/Type\s*/Pages[^>]*?/Count\s+(\d+)", content)]
    if counts:
        return max(counts)
    return len(re.findall(rb"/Type\s*/Page[^s]", content))


def test_pdf_is_single_page_even_when_full():
    """Максимум строк, длинные ФИО и назначение — всё равно один лист."""
    content = _printed_report(
        advances=[{"date": f"2026-10-1{i}", "amount": "1000.00"} for i in range(1, 4)],
        expenses=[{"date": f"{10 + i}.10.2026",
                   "document": "Платежный документ, подтверждающий оплату",
                   "document_number": f"ЖЕ211018579{i}",
                   "purpose": "Проезд и проживание, дополнительные расходы в пути",
                   "amount": "1123,45"} for i in range(10)],
    )
    assert content.startswith(b"%PDF")
    assert _pdf_pages(content) == 1


def test_pdf_fits_one_page_for_long_header_text():
    content = _printed_report(
        org_name='ООО "Сэйлз Модерн групп" · официальный дистрибьютор моющих средств',
        person_name="Константинопольский Александр Владимирович",
        purpose="Командировочные расходы на поездку в г. Гомель для проведения переговоров "
                "с ключевым клиентом и подписания договора поставки на 2027 год",
    )
    assert _pdf_pages(content) == 1


def test_update_check_uses_trusted_certificates(monkeypatch):
    """Проверка обновлений должна доверять сертификату GitHub в собранной программе."""
    import ssl

    from app import updates

    context = updates.ssl_context()
    assert isinstance(context, ssl.SSLContext)
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.get_ca_certs(), "в контексте нет ни одного сертификата"


def test_update_check_explains_certificate_error():
    from app import updates

    exc = ssl_error = Exception(
        "SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: "
        "unable to get local issuer certificate (_ssl.c:1006)"
    )
    text = updates._friendly_network_error(ssl_error)
    assert "сертификат" in text.lower()
    assert "Скачать файл" in text
    assert "CERTIFICATE_VERIFY_FAILED" not in text

    other = updates._friendly_network_error(Exception("timed out"))
    assert "Нет связи с GitHub" in other


def test_packaging_bundles_certifi():
    """Сертификаты certifi попадают в сборку, иначе обновления не проверяются."""
    from pathlib import Path as _Path

    root = _Path(__file__).resolve().parent.parent
    for spec in ("AvansReport.spec", "AvansStandalone.spec"):
        text = (root / "desktop" / spec).read_text(encoding="utf-8")
        assert 'collect_data_files("certifi")' in text, spec
        assert '"certifi"' in text, spec

    assert "certifi" in (root / "requirements.txt").read_text(encoding="utf-8")
    assert "certifi" in (root / "pyproject.toml").read_text(encoding="utf-8")
