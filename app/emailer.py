"""Отправка авансовых отчётов по электронной почте (SMTP)."""

from __future__ import annotations

import html
import re
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .excel_export import build_report_xlsx, report_filename
from .numberwords import format_money

EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[A-Za-zА-Яа-я]{2,}$")
MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]


class EmailError(RuntimeError):
    """Ошибка отправки письма с понятным пользователю текстом."""


def parse_recipients(value) -> List[str]:
    if isinstance(value, (list, tuple)):
        raw_items = []
        for item in value:
            raw_items.extend(str(item).replace(";", ",").split(","))
    else:
        raw_items = str(value or "").replace(";", ",").split(",")
    recipients: List[str] = []
    for item in raw_items:
        address = item.strip()
        if not address:
            continue
        if not EMAIL_RE.match(address):
            raise EmailError(f"Некорректный адрес электронной почты: {address}")
        if address.lower() not in [r.lower() for r in recipients]:
            recipients.append(address)
    if not recipients:
        raise EmailError("Укажите хотя бы один адрес электронной почты получателя.")
    if len(recipients) > 10:
        raise EmailError("Слишком много получателей (максимум 10).")
    return recipients


def smtp_configured(settings: Dict[str, Any]) -> bool:
    return bool(settings.get("host") and (settings.get("from_email") or settings.get("username")))


def _sender(settings: Dict[str, Any]) -> Tuple[str, str]:
    address = settings.get("from_email") or settings.get("username") or ""
    name = settings.get("from_name") or "Авансовые отчёты"
    return address, name


def _connect(settings: Dict[str, Any], timeout: int = 25) -> smtplib.SMTP:
    host = (settings.get("host") or "").strip()
    if not host:
        raise EmailError("SMTP-сервер не настроен. Обратитесь к администратору.")
    port = int(settings.get("port") or 587)
    security = (settings.get("security") or "starttls").lower()
    try:
        if security == "ssl":
            context = ssl.create_default_context()
            server: smtplib.SMTP = smtplib.SMTP_SSL(host, port, timeout=timeout, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
            server.ehlo()
            if security == "starttls":
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailError(f"Не удалось подключиться к SMTP-серверу {host}:{port}: {exc}") from exc

    username = (settings.get("username") or "").strip()
    password = settings.get("password") or ""
    if username:
        try:
            server.login(username, password)
        except smtplib.SMTPException as exc:
            try:
                server.quit()
            except smtplib.SMTPException:
                pass
            raise EmailError(
                "SMTP-сервер отклонил логин или пароль. Проверьте настройки почты."
            ) from exc
    return server


def send_message(
    settings: Dict[str, Any],
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    recipients: Sequence[str] = (),
    attachments: Iterable[Tuple[str, bytes, str]] = (),
) -> None:
    if not recipients:
        raise EmailError("Не указаны получатели письма.")
    sender_address, sender_name = _sender(settings)
    if not sender_address:
        raise EmailError("В настройках почты не указан адрес отправителя.")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((sender_name, sender_address))
    message["To"] = ", ".join(recipients)
    message["Date"] = datetime.now().astimezone().strftime("%a, %d %b %Y %H:%M:%S %z")
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for filename, content, subtype in attachments:
        message.add_attachment(
            content,
            maintype="application",
            subtype=subtype,
            filename=filename,
        )

    server = _connect(settings)
    try:
        server.send_message(message, from_addr=sender_address, to_addrs=list(recipients))
    except smtplib.SMTPException as exc:
        raise EmailError(f"SMTP-сервер не принял письмо: {exc}") from exc
    finally:
        try:
            server.quit()
        except smtplib.SMTPException:
            pass


def _format_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"{parsed.day:02d}.{parsed.month:02d}.{parsed.year}"


def _long_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value)[:10])
    except ValueError:
        return str(value)
    return f"«{parsed.day}» {MONTHS_GENITIVE[parsed.month - 1]} {parsed.year} г."


def build_report_letter(report: Dict[str, Any], comment: str = "") -> Tuple[str, str, str]:
    """Возвращает (тема, текстовая версия, HTML-версия) письма."""
    totals = report.get("totals") or {}
    approved = int(totals.get("approved_cents") or 0)
    subject = (
        f"Авансовый отчёт № {report.get('number')} от {_format_date(report.get('report_date'))} — "
        f"{report.get('person_name')}"
    )

    rows_html = []
    for index, row in enumerate(report.get("expenses") or [], start=1):
        rows_html.append(
            "<tr>"
            f"<td style='border:1px solid #c9d3dc;padding:4px 6px;'>{index}</td>"
            f"<td style='border:1px solid #c9d3dc;padding:4px 6px;'>{html.escape(str(row.get('date', '')))}</td>"
            f"<td style='border:1px solid #c9d3dc;padding:4px 6px;'>{html.escape(str(row.get('document', '')))}</td>"
            f"<td style='border:1px solid #c9d3dc;padding:4px 6px;'>{html.escape(str(row.get('document_number', '')))}</td>"
            f"<td style='border:1px solid #c9d3dc;padding:4px 6px;'>{html.escape(str(row.get('purpose', '')))}</td>"
            f"<td style='border:1px solid #c9d3dc;padding:4px 6px;text-align:right;'>{format_money(int(row.get('amount_cents') or 0))}</td>"
            "</tr>"
        )

    rows_text = "\n".join(
        f"  {i}. {row.get('date', '')} | {row.get('document', '')} | "
        f"{row.get('document_number', '')} | {row.get('purpose', '')} | "
        f"{format_money(int(row.get('amount_cents') or 0))}"
        for i, row in enumerate(report.get("expenses") or [], start=1)
    )

    comment_html = ""
    if comment:
        comment_html = (
            "<p style='background:#f4f7fa;border-left:3px solid #156082;padding:10px 12px;"
            f"white-space:pre-wrap;'>{html.escape(comment)}</p>"
        )

    html_body = f"""
    <div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;color:#1a2733;max-width:760px;">
      <p>Здравствуйте!</p>
      <p>Направляю авансовый отчёт <b>№ {html.escape(str(report.get('number')))}</b>
         от {_long_date(report.get('report_date'))}.</p>
      {comment_html}
      <table style="border-collapse:collapse;margin:12px 0;font-size:13px;">
        <tr><td style="padding:3px 12px 3px 0;color:#5b6b7a;">Подотчётное лицо:</td>
            <td><b>{html.escape(str(report.get('person_name') or ''))}</b></td></tr>
        <tr><td style="padding:3px 12px 3px 0;color:#5b6b7a;">Должность:</td>
            <td>{html.escape(str(report.get('person_position') or '—'))}</td></tr>
        <tr><td style="padding:3px 12px 3px 0;color:#5b6b7a;">Назначение аванса:</td>
            <td>{html.escape(str(report.get('purpose') or '—'))}</td></tr>
        <tr><td style="padding:3px 12px 3px 0;color:#5b6b7a;">Получено:</td>
            <td>{format_money(int(totals.get('received_cents') or 0))} руб.</td></tr>
        <tr><td style="padding:3px 12px 3px 0;color:#5b6b7a;">Израсходовано:</td>
            <td>{format_money(int(totals.get('spent_cents') or 0))} руб.</td></tr>
        <tr><td style="padding:3px 12px 3px 0;color:#5b6b7a;">Остаток / перерасход:</td>
            <td>{format_money(int(totals.get('balance_cents') or 0))} руб.</td></tr>
        <tr><td style="padding:3px 12px 3px 0;color:#5b6b7a;">К утверждению:</td>
            <td><b>{format_money(approved)} руб.</b> ({html.escape(str(report.get('amount_words') or ''))})</td></tr>
      </table>
      <table style="border-collapse:collapse;font-size:12px;width:100%;">
        <thead>
          <tr style="background:#e8eef4;">
            <th style="border:1px solid #c9d3dc;padding:5px 6px;">№</th>
            <th style="border:1px solid #c9d3dc;padding:5px 6px;">Дата</th>
            <th style="border:1px solid #c9d3dc;padding:5px 6px;">Документ</th>
            <th style="border:1px solid #c9d3dc;padding:5px 6px;">Номер</th>
            <th style="border:1px solid #c9d3dc;padding:5px 6px;">Кому, за что уплачено</th>
            <th style="border:1px solid #c9d3dc;padding:5px 6px;">Сумма, руб.</th>
          </tr>
        </thead>
        <tbody>{''.join(rows_html)}</tbody>
      </table>
      <p style="color:#5b6b7a;font-size:12px;margin-top:14px;">
        Бланк отчёта в формате Excel приложен к письму.
        Письмо сформировано автоматически программой «{html.escape(str(report.get('org_name') or 'Авансовые отчёты'))}».
      </p>
    </div>
    """

    text_body = (
        f"Авансовый отчёт № {report.get('number')} от {_format_date(report.get('report_date'))}\n\n"
        f"Подотчётное лицо: {report.get('person_name')}\n"
        f"Должность: {report.get('person_position') or '—'}\n"
        f"Назначение аванса: {report.get('purpose') or '—'}\n"
        f"Получено: {format_money(int(totals.get('received_cents') or 0))} руб.\n"
        f"Израсходовано: {format_money(int(totals.get('spent_cents') or 0))} руб.\n"
        f"Остаток / перерасход: {format_money(int(totals.get('balance_cents') or 0))} руб.\n"
        f"К утверждению: {format_money(approved)} руб.\n\n"
        f"Расходы:\n{rows_text}\n"
    )
    if comment:
        text_body += f"\nКомментарий:\n{comment}\n"
    return subject, text_body, html_body


def send_report(
    settings: Dict[str, Any],
    report: Dict[str, Any],
    recipients: Sequence[str],
    comment: str = "",
) -> None:
    subject, text_body, html_body = build_report_letter(report, comment)
    prefix = (settings.get("subject_prefix") or "").strip()
    if prefix and not subject.startswith(prefix):
        subject = f"{prefix} {subject}"

    attachments = []
    excel_bytes = build_report_xlsx(report)
    attachments.append(
        (
            report_filename(report),
            excel_bytes,
            "vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    )
    send_message(settings, subject, text_body, html_body, recipients, attachments)


def test_settings(settings: Dict[str, Any], recipient: str) -> None:
    """Проверка настроек: отправляет короткое тестовое письмо."""
    recipients = parse_recipients(recipient)
    send_message(
        settings,
        "Проверка настроек почты — Авансовые отчёты",
        "Это тестовое письмо. Настройки SMTP указаны верно.",
        "<p>Это тестовое письмо. Настройки SMTP указаны верно.</p>",
        recipients,
    )
