"""Хранение отчётов автономной версии: файлы JSON + PDF в папке сессии."""

from __future__ import annotations

import json
import os
import re
import threading
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from app import pdf_export
from app.numberwords import amount_in_words, format_money
from app.reports import ReportIn, compute_totals

from . import config

NUMBER_RE = re.compile(r"^АО-(\d{4})-(\d{4,})$")
_lock = threading.Lock()


class StorageError(RuntimeError):
    pass


def _report_files(folder: Path) -> List[Path]:
    return sorted(folder.glob("АО-*.json"))


COUNTER_NAME = "_counter.json"


def _read_counters(folder: Path) -> Dict[str, int]:
    path = folder / COUNTER_NAME
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_counters(folder: Path, counters: Dict[str, int]) -> None:
    path = folder / COUNTER_NAME
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(counters, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _max_in_files(folder: Path, year: int) -> int:
    maximum = 0
    for path in _report_files(folder):
        match = NUMBER_RE.match(path.stem)
        if match and int(match.group(1)) == year:
            maximum = max(maximum, int(match.group(2)))
    return maximum


def next_number(folder: Path, year: int) -> str:
    """Следующий номер отчёта. Удалённые номера не используются повторно."""
    counters = _read_counters(folder)
    current = max(counters.get(str(year), 0), _max_in_files(folder, year))
    return f"АО-{year}-{current + 1:04d}"


def _allocate_number(folder: Path, year: int) -> str:
    """Выделяет номер и сразу его фиксирует (вызывать под блокировкой)."""
    counters = _read_counters(folder)
    current = max(counters.get(str(year), 0), _max_in_files(folder, year))
    number = f"АО-{year}-{current + 1:04d}"
    counters[str(year)] = current + 1
    _write_counters(folder, counters)
    return number


def build_report(data: ReportIn, settings: Dict[str, Any], number: str) -> Dict[str, Any]:
    """Собирает полное представление отчёта (как в серверной версии)."""
    advances = list(data.advances)  # type: ignore[arg-type]
    expenses = list(data.expenses)  # type: ignore[arg-type]
    totals = compute_totals(advances, expenses)
    return {
        "number": number,
        "report_date": data.report_date.isoformat(),
        "person_name": data.person_name.strip(),
        "person_position": data.person_position.strip(),
        "purpose": data.purpose.strip(),
        "org_name": settings.get("org_name", ""),
        "director_position": settings.get("director_position", ""),
        "director_name": settings.get("director_name", ""),
        "accountant_position": settings.get("accountant_position", ""),
        "accountant_name": settings.get("accountant_name", ""),
        "advances": advances,
        "expenses": expenses,
        "totals": totals,
        "amount_words": amount_in_words(totals["approved_cents"]),
        "amount_formatted": format_money(totals["approved_cents"]),
        "created_at": None,
        "created_at_local": None,
        "mode": "standalone",
    }


def stamp(report: Dict[str, Any]) -> Dict[str, Any]:
    from datetime import datetime, timezone

    moment = datetime.now(timezone.utc).replace(microsecond=0)
    report["created_at"] = moment.isoformat().replace("+00:00", "Z")
    report["created_at_local"] = datetime.now().strftime("%d.%m.%Y %H:%M")
    return report


def save_new_report(folder: Path, data: "object", settings: Dict[str, Any],
                    year: int) -> Dict[str, Any]:
    """Выделяет номер и сохраняет JSON + PDF одной операцией.

    Блокировка гарантирует корректность при одновременном сохранении
    из нескольких окон браузера.
    """
    with _lock:
        number = _allocate_number(folder, year)
        report = stamp(build_report(data, settings, number))  # type: ignore[arg-type]
        files = _write_files(folder, report)
        return {"number": number, "report": report, "files": files}


def save_report(folder: Path, report: Dict[str, Any]) -> Dict[str, str]:
    """Пишет JSON и PDF. Возвращает пути к файлам."""
    with _lock:
        return _write_files(folder, report)


def _write_files(folder: Path, report: Dict[str, Any]) -> Dict[str, str]:
    pdf_bytes = pdf_export.build_report_pdf(report)
    json_path = folder / f"{report['number']}.json"
    pdf_path = folder / f"{report['number']}.pdf"

    # Эксклюзивное создание защищает от случайного перезаписывания чужого отчёта
    try:
        with open(json_path, "x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
    except FileExistsError as exc:
        raise StorageError("Отчёт с таким номером уже существует") from exc
    pdf_tmp = pdf_path.with_suffix(".pdf.part")
    pdf_tmp.write_bytes(pdf_bytes)
    os.replace(pdf_tmp, pdf_path)

    return {"json": str(json_path), "pdf": str(pdf_path), "pdf_name": pdf_path.name,
            "json_name": json_path.name}


def load_report(folder: Path, number: str) -> Optional[Dict[str, Any]]:
    path = folder / f"{number}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StorageError("Файл отчёта повреждён") from exc


def list_reports(folder: Path) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for path in _report_files(folder):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pdf_path = folder / f"{path.stem}.pdf"
        items.append({
            "number": data.get("number") or path.stem,
            "report_date": data.get("report_date"),
            "person_name": data.get("person_name", ""),
            "person_position": data.get("person_position", ""),
            "purpose": data.get("purpose", ""),
            "totals": data.get("totals", {}),
            "amount_words": data.get("amount_words", ""),
            "created_at": data.get("created_at"),
            "created_at_local": data.get("created_at_local"),
            "has_pdf": pdf_path.exists(),
            "json_name": path.name,
            "pdf_name": f"{path.stem}.pdf",
        })
    items.sort(key=lambda item: (item.get("report_date") or "", item["number"]), reverse=True)
    return items


def delete_report(folder: Path, number: str) -> bool:
    removed = False
    for suffix in (".json", ".pdf"):
        path = folder / f"{number}{suffix}"
        if path.exists():
            path.unlink()
            removed = True
    return removed


def session_stats(folder: Path) -> Dict[str, Any]:
    reports = list_reports(folder)
    total = sum(int((item.get("totals") or {}).get("approved_cents") or 0) for item in reports)
    return {
        "count": len(reports),
        "total_cents": total,
        "folder": str(folder),
    }


def cleanup_old_sessions(days: int = 30) -> int:
    """Удаляет пустые сессии старше N дней (не трогает сессии с отчётами)."""
    removed = 0
    cutoff = date.today().toordinal() - max(1, int(days))
    root = config.sessions_dir()
    for folder in root.iterdir():
        if not folder.is_dir():
            continue
        if any(folder.iterdir()):
            continue
        try:
            from datetime import datetime

            if datetime.fromtimestamp(folder.stat().st_mtime).date().toordinal() < cutoff:
                folder.rmdir()
                removed += 1
        except OSError:  # pragma: no cover
            continue
    return removed
