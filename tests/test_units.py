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
