"""Сумма прописью (русский язык) и денежное форматирование."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import List

_UNITS_MALE = [
    "", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
]
_UNITS_FEMALE = [
    "", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять",
]
_TEENS = [
    "десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать",
    "пятнадцать", "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать",
]
_TENS = [
    "", "", "двадцать", "тридцать", "сорок", "пятьдесят",
    "шестьдесят", "семьдесят", "восемьдесят", "девяносто",
]
_HUNDREDS = [
    "", "сто", "двести", "триста", "четыреста", "пятьсот",
    "шестьсот", "семьсот", "восемьсот", "девятьсот",
]

_RUBLE_FORMS = ("рубль", "рубля", "рублей")
_KOPECK_FORMS = ("копейка", "копейки", "копеек")
_THOUSAND_FORMS = ("тысяча", "тысячи", "тысяч")
_MILLION_FORMS = ("миллион", "миллиона", "миллионов")
_BILLION_FORMS = ("миллиард", "миллиарда", "миллиардов")


def plural(value: int, forms: tuple) -> str:
    value = abs(int(value))
    if value % 100 in (11, 12, 13, 14):
        return forms[2]
    last = value % 10
    if last == 1:
        return forms[0]
    if last in (2, 3, 4):
        return forms[1]
    return forms[2]


def _triple(value: int, female: bool = False) -> str:
    """Число от 0 до 999 прописью."""
    words: List[str] = []
    hundreds, rest = divmod(value, 100)
    if hundreds:
        words.append(_HUNDREDS[hundreds])
    if 10 <= rest <= 19:
        words.append(_TEENS[rest - 10])
        return " ".join(words)
    tens, unit = divmod(rest, 10)
    if tens:
        words.append(_TENS[tens])
    if unit:
        words.append((_UNITS_FEMALE if female else _UNITS_MALE)[unit])
    return " ".join(words)


def _group(value: int, forms: tuple, female: bool = False) -> str:
    """Группа из трёх цифр с названием разряда."""
    if value == 0:
        return ""
    words = _triple(value, female)
    return f"{words} {plural(value, forms)}"


def amount_in_words(cents: int, *, capitalize: bool = True) -> str:
    """123456 -> 'Одна тысяча двести тридцать четыре рубля 56 копеек'."""
    cents = int(cents)
    negative = cents < 0
    cents = abs(cents)
    rubles, kopecks = divmod(cents, 100)

    if rubles == 0:
        words = "ноль"
    else:
        groups: List[str] = []
        billions, rest = divmod(rubles, 1_000_000_000)
        millions, rest = divmod(rest, 1_000_000)
        thousands, units = divmod(rest, 1_000)
        if billions:
            groups.append(_group(billions, _BILLION_FORMS))
        if millions:
            groups.append(_group(millions, _MILLION_FORMS))
        if thousands:
            groups.append(_group(thousands, _THOUSAND_FORMS, female=True))
        if units:
            groups.append(_triple(units))
        words = " ".join(part for part in groups if part).strip()

    result = (
        f"{words} {plural(rubles, _RUBLE_FORMS)} "
        f"{kopecks:02d} {plural(kopecks, _KOPECK_FORMS)}"
    )
    if negative:
        result = "минус " + result
    if capitalize and result:
        result = result[0].upper() + result[1:]
    return result


def to_cents(value) -> int:
    """Строка/число в рублях -> копейки (без потерь на плавающей точке)."""
    if value is None or value == "":
        return 0
    if isinstance(value, int):
        return value * 100
    if isinstance(value, Decimal):
        decimal_value = value
    else:
        text = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", ".")
        if not text:
            return 0
        decimal_value = Decimal(text)
    return int((decimal_value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def from_cents(cents: int) -> Decimal:
    return (Decimal(int(cents)) / Decimal(100)).quantize(Decimal("0.01"))


def format_money(cents: int) -> str:
    """123456 -> '1 234,56'."""
    cents = int(cents)
    negative = cents < 0
    rubles, kopecks = divmod(abs(cents), 100)
    grouped = f"{rubles:,}".replace(",", " ")
    return f"{'-' if negative else ''}{grouped},{kopecks:02d}"
