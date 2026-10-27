"""Авансовые отчёты: валидация, расчёты, создание и выборка."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from decimal import Decimal
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from . import db
from .numberwords import amount_in_words, format_money, to_cents

MAX_ADVANCES = 3   # строки 26–28 формы
MAX_EXPENSES = 10  # строки 36–45 формы
MAX_AMOUNT_RUB = Decimal("99999999.99")

PURPOSE_CHOICES = [
    "Командировочные расходы",
    "Расходы на хозяйственные нужды",
]


class ReportValidationError(ValueError):
    """Ошибка заполнения отчёта (показывается пользователю)."""


class AdvanceIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    date: Optional[str] = None
    amount: Any = None

    @field_validator("date")
    @classmethod
    def _clean_date(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return None
        text = str(value).strip()[:10]
        try:
            date.fromisoformat(text)
        except ValueError as exc:  # pragma: no cover - защита от некорректных данных
            raise ValueError("Некорректная дата получения аванса") from exc
        return text


class ExpenseIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    date: str = ""
    document: str = ""
    document_number: str = ""
    purpose: str = ""
    amount: Any = None

    @field_validator("date", "document", "document_number", "purpose")
    @classmethod
    def _limit(cls, value: str) -> str:
        text = (value or "").strip()
        if len(text) > 200:
            raise ValueError("Слишком длинный текст в строке расхода (максимум 200 символов)")
        return text


class ReportIn(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=True)

    report_date: date
    person_name: str = Field(min_length=3, max_length=200)
    person_position: str = Field(default="", max_length=200)
    purpose: str = Field(default="", max_length=200)
    advances: List[AdvanceIn] = Field(default_factory=list, max_length=MAX_ADVANCES)
    expenses: List[ExpenseIn] = Field(default_factory=list, max_length=MAX_EXPENSES)

    @model_validator(mode="after")
    def _validate_rows(self) -> "ReportIn":
        if not self.person_name.strip():
            raise ValueError("Укажите подотчётное лицо")
        if not self.purpose.strip():
            raise ValueError("Укажите назначение аванса")

        cleaned_advances = []
        for row in self.advances:
            cents = to_cents(row.amount)
            if cents == 0:
                continue
            if cents < 0:
                raise ValueError("Сумма полученного аванса не может быть отрицательной")
            if to_cents(row.amount) > to_cents(MAX_AMOUNT_RUB):
                raise ValueError("Сумма полученного аванса слишком велика")
            if not row.date:
                raise ValueError("Укажите дату получения аванса")
            cleaned_advances.append({"date": row.date, "amount_cents": cents})
        self.advances = cleaned_advances  # type: ignore[assignment]

        cleaned_expenses = []
        for row in self.expenses:
            cents = to_cents(row.amount)
            empty_text = not any([row.date, row.document, row.document_number, row.purpose])
            if cents == 0 and empty_text:
                continue
            if cents <= 0:
                raise ValueError("Укажите сумму расхода больше нуля")
            if to_cents(row.amount) > to_cents(MAX_AMOUNT_RUB):
                raise ValueError("Сумма расхода слишком велика")
            if not row.date:
                raise ValueError("Укажите дату документа")
            if not row.purpose:
                raise ValueError("Укажите, кому и за что уплачено")
            cleaned_expenses.append(
                {
                    "date": row.date,
                    "document": row.document,
                    "document_number": row.document_number,
                    "purpose": row.purpose,
                    "amount_cents": cents,
                }
            )
        self.expenses = cleaned_expenses  # type: ignore[assignment]

        if not cleaned_expenses:
            raise ValueError("Добавьте хотя бы одну строку расходов")
        return self


def _cents(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def compute_totals(advances: List[dict], expenses: List[dict]) -> Dict[str, int]:
    received = sum(_cents(row.get("amount_cents")) for row in advances)
    spent = sum(_cents(row.get("amount_cents")) for row in expenses)
    return {
        "received_cents": received,
        "spent_cents": spent,
        "balance_cents": received - spent,
        "approved_cents": spent,
    }


def create_report(conn: sqlite3.Connection, user: sqlite3.Row, payload: ReportIn,
                  settings: Dict[str, Any]) -> int:
    """Создаёт отчёт. Сохранённый отчёт изменить нельзя — только создать новый."""
    advances = list(payload.advances)  # type: ignore[arg-type]
    expenses = list(payload.expenses)  # type: ignore[arg-type]
    totals = compute_totals(advances, expenses)

    number = db.next_report_number(conn, payload.report_date.year)
    snapshot = {
        "org_name": settings.get("org_name", ""),
        "director_position": settings.get("director_position", ""),
        "director_name": settings.get("director_name", ""),
        "accountant_position": settings.get("accountant_position", ""),
        "accountant_name": settings.get("accountant_name", ""),
    }
    data = {
        "number": number,
        "report_date": payload.report_date.isoformat(),
        "person_name": payload.person_name.strip(),
        "person_position": payload.person_position.strip(),
        "purpose": payload.purpose.strip(),
        "advances": advances,
        "expenses": expenses,
        "totals": totals,
        **snapshot,
    }
    created_at = db.now_iso()
    cursor = conn.execute(
        """
        INSERT INTO reports (
            number, user_id, status, report_date, person_name, person_position, purpose,
            total_received_cents, total_spent_cents, balance_cents, approved_cents,
            data, created_at
        ) VALUES (?, ?, 'saved', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            number,
            user["id"],
            payload.report_date.isoformat(),
            payload.person_name.strip(),
            payload.person_position.strip(),
            payload.purpose.strip(),
            totals["received_cents"],
            totals["spent_cents"],
            totals["balance_cents"],
            totals["approved_cents"],
            json.dumps(data, ensure_ascii=False),
            created_at,
        ),
    )
    report_id = int(cursor.lastrowid)
    db.audit(
        conn,
        "report.create",
        actor=user,
        entity="report",
        entity_id=report_id,
        details={"number": number, "spent_cents": totals["spent_cents"]},
    )
    return report_id


def serialize(row: sqlite3.Row, *, owner: Optional[sqlite3.Row] = None,
              include_data: bool = True) -> Dict[str, Any]:
    data = json.loads(row["data"]) if "data" in row.keys() and row["data"] else {}
    report: Dict[str, Any] = {
        "id": row["id"],
        "number": row["number"],
        "status": row["status"],
        "report_date": row["report_date"],
        "person_name": row["person_name"],
        "person_position": row["person_position"],
        "purpose": row["purpose"],
        "totals": {
            "received_cents": row["total_received_cents"],
            "spent_cents": row["total_spent_cents"],
            "balance_cents": row["balance_cents"],
            "approved_cents": row["approved_cents"],
        },
        "created_at": row["created_at"],
        "sent_at": row["sent_at"],
        "sent_to": row["sent_to"],
        "email_status": row["email_status"],
        "owner": {
            "id": row["user_id"],
            "username": row["username"] if owner is None else owner["username"],
            "full_name": row["full_name"] if owner is None else owner["full_name"],
            "position": row["position"] if "position" in row.keys() else "",
            "email": row["email"] if "email" in row.keys() else "",
        },
        "org_name": data.get("org_name", ""),
        "director_position": data.get("director_position", ""),
        "director_name": data.get("director_name", ""),
        "accountant_position": data.get("accountant_position", ""),
        "accountant_name": data.get("accountant_name", ""),
        "amount_words": amount_in_words(row["approved_cents"]),
        "amount_formatted": format_money(row["approved_cents"]),
    }
    if include_data:
        report["advances"] = data.get("advances", [])
        report["expenses"] = data.get("expenses", [])
    return report


SELECT_WITH_OWNER = """
    SELECT r.*, u.username, u.full_name, u.position, u.email
    FROM reports r
    JOIN users u ON u.id = r.user_id
"""


def get_report(conn: sqlite3.Connection, report_id: int) -> Optional[sqlite3.Row]:
    return db.query_one(conn, SELECT_WITH_OWNER + " WHERE r.id = ?", (report_id,))


def can_view(user: sqlite3.Row, report: sqlite3.Row) -> bool:
    if user["role"] in ("admin", "supervisor"):
        return True
    return int(report["user_id"]) == int(user["id"])


def list_reports(
    conn: sqlite3.Connection,
    user: sqlite3.Row,
    *,
    scope: str = "auto",
    owner_id: Optional[int] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    status: Optional[str] = None,
    search: str = "",
    limit: int = 200,
    offset: int = 0,
) -> Dict[str, Any]:
    clauses = []
    params: List[Any] = []

    sees_all = user["role"] in ("admin", "supervisor") and scope != "mine"
    if not sees_all:
        clauses.append("r.user_id = ?")
        params.append(user["id"])
    elif owner_id:
        clauses.append("r.user_id = ?")
        params.append(owner_id)

    if date_from:
        clauses.append("r.report_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("r.report_date <= ?")
        params.append(date_to)
    if status in ("saved", "sent"):
        clauses.append("r.status = ?")
        params.append(status)
    if search.strip():
        needle = f"%{search.strip()}%"
        clauses.append(
            "(r.number LIKE ? OR r.person_name LIKE ? OR r.purpose LIKE ? "
            "OR u.full_name LIKE ? OR r.sent_to LIKE ?)"
        )
        params.extend([needle] * 5)

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    total_row = db.query_one(
        conn,
        "SELECT COUNT(*) AS c, COALESCE(SUM(r.approved_cents), 0) AS s "
        "FROM reports r JOIN users u ON u.id = r.user_id" + where,
        params,
    )
    limit = max(1, min(int(limit), 500))
    offset = max(0, int(offset))
    rows = db.query_all(
        conn,
        SELECT_WITH_OWNER + where + " ORDER BY r.report_date DESC, r.id DESC LIMIT ? OFFSET ?",
        params + [limit, offset],
    )
    return {
        "items": [serialize(row, include_data=False) for row in rows],
        "total": int(total_row["c"]) if total_row else 0,
        "total_amount_cents": int(total_row["s"]) if total_row else 0,
        "limit": limit,
        "offset": offset,
    }


def mark_sent(conn: sqlite3.Connection, user: sqlite3.Row, report_id: int,
              recipients: List[str], ok: bool, error: Optional[str] = None) -> None:
    if ok:
        conn.execute(
            "UPDATE reports SET status = 'sent', sent_at = ?, sent_to = ?, email_status = ? "
            "WHERE id = ?",
            (db.now_iso(), ", ".join(recipients), "sent", report_id),
        )
    else:
        conn.execute(
            "UPDATE reports SET email_status = ? WHERE id = ?",
            (f"error: {(error or '')[:300]}", report_id),
        )
    db.audit(
        conn,
        "report.email" if ok else "report.email_failed",
        actor=user,
        entity="report",
        entity_id=report_id,
        details={"recipients": recipients, "error": (error or "")[:500]},
    )
