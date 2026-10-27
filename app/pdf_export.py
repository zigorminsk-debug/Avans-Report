"""Формирование PDF-версии авансового отчёта (бланк A4 по исходной форме Excel).

Шрифты DejaVu Serif (свободная лицензия, поддержка кириллицы) поставляются
вместе с программой: app/assets/fonts/. Если их нет, используются системные
шрифты Windows (Times New Roman / Arial).
"""

from __future__ import annotations

import io
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from .config import resource_dir
from .numberwords import format_money

MONTHS_GENITIVE = [
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
]

MAX_EXPENSES = 10

_FONTS_READY = False
FONT_REGULAR = "AvansSerif"
FONT_BOLD = "AvansSerif-Bold"

_BUNDLED = [
    (FONT_REGULAR, "DejaVuSerif.ttf"),
    (FONT_BOLD, "DejaVuSerif-Bold.ttf"),
]

_SYSTEM_CANDIDATES = [
    # (regular, bold) — Windows, затем Linux/macOS
    ("C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Times New Roman.ttf",
     "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"),
]


def _font_dir() -> Path:
    return resource_dir() / "assets" / "fonts"


def _register_fonts() -> None:
    """Регистрирует шрифты с кириллицей. Вызывается один раз за процесс."""
    global _FONTS_READY, FONT_REGULAR, FONT_BOLD
    if _FONTS_READY:
        return

    folder = _font_dir()
    bundled_ok = all((folder / name).exists() for _, name in _BUNDLED)
    if bundled_ok:
        try:
            for alias, name in _BUNDLED:
                pdfmetrics.registerFont(TTFont(alias, str(folder / name)))
            _FONTS_READY = True
            return
        except Exception:  # pragma: no cover - повреждённый файл шрифта
            pass

    for regular, bold in _SYSTEM_CANDIDATES:
        if Path(regular).exists() and Path(bold).exists():
            try:
                pdfmetrics.registerFont(TTFont(FONT_REGULAR, regular))
                pdfmetrics.registerFont(TTFont(FONT_BOLD, bold))
                _FONTS_READY = True
                return
            except Exception:  # pragma: no cover
                continue

    # Крайний случай: встроенные шрифты PDF (без кириллицы, но файл создаётся)
    FONT_REGULAR = "Helvetica"
    FONT_BOLD = "Helvetica-Bold"
    _FONTS_READY = True


def _styles() -> Dict[str, ParagraphStyle]:
    _register_fonts()
    base = ParagraphStyle(
        "base", fontName=FONT_REGULAR, fontSize=8.6, leading=10.4,
        textColor=colors.black, alignment=TA_LEFT, spaceAfter=0, spaceBefore=0,
    )
    return {
        "base": base,
        "small": ParagraphStyle("small", parent=base, fontSize=7, leading=8.4),
        "tiny": ParagraphStyle("tiny", parent=base, fontSize=6.6, leading=7.8,
                               textColor=colors.HexColor("#444444")),
        "org": ParagraphStyle("org", parent=base, fontName=FONT_BOLD, fontSize=12.5, leading=15),
        "approve": ParagraphStyle("approve", parent=base, fontSize=10.5, leading=13),
        "title": ParagraphStyle("title", parent=base, fontName=FONT_BOLD, fontSize=15, leading=18,
                                alignment=TA_CENTER, spaceBefore=6, spaceAfter=2),
        "label": ParagraphStyle("label", parent=base, fontSize=9.5, leading=12),
        "value": ParagraphStyle("value", parent=base, fontSize=10.5, leading=13),
        "hint": ParagraphStyle("hint", parent=base, fontSize=6.4, leading=8,
                               alignment=TA_CENTER),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8.4, leading=10),
        "cell_center": ParagraphStyle("cell_center", parent=base, fontSize=8.4, leading=10,
                                      alignment=TA_CENTER),
        "cell_right": ParagraphStyle("cell_right", parent=base, fontSize=8.4, leading=10,
                                     alignment=TA_RIGHT),
        "th": ParagraphStyle("th", parent=base, fontName=FONT_BOLD, fontSize=8.2, leading=9.6,
                             alignment=TA_CENTER),
        "date_line": ParagraphStyle("date_line", parent=base, fontSize=10.5, leading=13,
                                    alignment=TA_RIGHT),
    }


def _markup(markup: str, style: ParagraphStyle) -> Paragraph:
    """Параграф с готовой разметкой (используется только для доверенных строк)."""
    return Paragraph(markup or "&nbsp;", style)


def _paragraph(text: str, style: ParagraphStyle) -> Paragraph:
    escaped = (
        str(text if text is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("\n", "<br/>")
    )
    return Paragraph(escaped or "&nbsp;", style)


def _parse_date(value: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(value or "")[:10])
    except ValueError:
        return None


def _date_text(value: str) -> str:
    moment = _parse_date(value)
    return f"{moment.day:02d}.{moment.month:02d}.{moment.year}" if moment else str(value or "")


def _money(cents: Any) -> str:
    return format_money(int(cents or 0))


def _signature_row(styles: Dict[str, ParagraphStyle], label: str, name: str,
                   width: float) -> Table:
    """Строка подписи: должность, линия подписи, расшифровка и подсказки под ней."""
    inner_width = width - 4
    label_width = inner_width * 0.40
    line_width = inner_width * 0.28
    name_width = inner_width - label_width - line_width

    line_cell = Table([[""]], colWidths=[line_width], rowHeights=[13])
    line_cell.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, -1), 0.6, colors.black),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    row = Table(
        [
            [_paragraph(label, styles["label"]), line_cell, _paragraph(name, styles["label"])],
            ["", _paragraph("(подпись)", styles["hint"]),
             _paragraph("(расшифровка подписи)", styles["hint"])],
        ],
        colWidths=[label_width, line_width, name_width],
    )
    row.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, 0), "BOTTOM"),
        ("VALIGN", (0, 1), (-1, 1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return row


def _approval_block(styles: Dict[str, ParagraphStyle], report: Dict[str, Any],
                    width: float) -> Table:
    words = report.get("amount_words") or ""
    director_position = report.get("director_position") or "Директор"
    director_name = report.get("director_name") or ""
    block = [
        [_paragraph("УТВЕРЖДАЮ", styles["approve"])],
        [_paragraph("Отчет в сумме:", styles["label"])],
        [_paragraph(words, styles["small"])],
        [Spacer(1, 4)],
        [_signature_row(styles, director_position, director_name, width - 4)],
        [Spacer(1, 2)],
        [_paragraph("(должность)", styles["hint"])],
    ]
    table = Table(block, colWidths=[width])
    table.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("ALIGN", (0, 0), (0, 5), "RIGHT"),
        ("LINEBELOW", (0, 3), (0, 3), 0, colors.white),
    ]))
    return table


def _field_row(styles: Dict[str, ParagraphStyle], label: str, value: str,
               total_width: float, hint: Optional[str] = None) -> Table:
    label_width = total_width * 0.30
    value_width = total_width - label_width
    body = Table(
        [[_paragraph(label, styles["label"]), _paragraph(value, styles["value"])]],
        colWidths=[label_width, value_width],
    )
    body.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("LINEBELOW", (1, 0), (1, 0), 0.6, colors.black),
        ("LEFTPADDING", (1, 0), (1, 0), 3),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ]))
    if not hint:
        return body
    hint_row = Table(
        [["", _paragraph(hint, styles["hint"])]],
        colWidths=[label_width, value_width],
    )
    hint_row.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    return KeepTogether([body, hint_row])


def _amounts_table(styles: Dict[str, ParagraphStyle], report: Dict[str, Any],
                   width: float) -> Table:
    totals = report.get("totals") or {}
    advances: List[dict] = list(report.get("advances") or [])
    col_left = width * 0.705
    col_right = width - col_left

    rows: List[List[Any]] = [[
        _paragraph("Наименование показателя", styles["th"]),
        _paragraph("Сумма, руб. коп", styles["th"]),
    ]]
    rows.append([
        _paragraph("Получено (дата):", styles["cell"]),
        _paragraph("—" if not advances else "", styles["cell_right"]),
    ])
    for advance in advances:
        rows.append([
            _paragraph("\u00a0\u00a0\u00a0" + _date_text(advance.get("date", "")), styles["cell"]),
            _paragraph(_money(advance.get("amount_cents")), styles["cell_right"]),
        ])
    rows.append([
        _paragraph("Итого получено", styles["cell"]),
        _paragraph(_money(totals.get("received_cents")), styles["cell_right"]),
    ])
    rows.append([
        _paragraph("Израсходовано", styles["cell"]),
        _paragraph(_money(totals.get("spent_cents")), styles["cell_right"]),
    ])
    rows.append([
        _paragraph(
            "Остаток денежных средств (к возврату) / - Перерасход (к возмещению)",
            styles["cell"],
        ),
        _paragraph(_money(totals.get("balance_cents")), styles["cell_right"]),
    ])

    table = Table(rows, colWidths=[col_left, col_right])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EDEDED")),
        ("FONTNAME", (0, 1), (-1, -1), FONT_REGULAR),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 3),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _expenses_table(styles: Dict[str, ParagraphStyle], report: Dict[str, Any],
                    width: float) -> Table:
    totals = report.get("totals") or {}
    expenses: List[dict] = list(report.get("expenses") or [])

    widths = [width * 0.155, width * 0.185, width * 0.135, width * 0.395]
    widths.append(width - sum(widths))

    header = [
        [
            _paragraph("Документ, подтверждающий приобретение товаров (работ, услуг)",
                       styles["th"]),
            "",
            "",
            _paragraph("Кому, за что уплачено. Иная информация (при необходимости)",
                       styles["th"]),
            _paragraph("Сумма, руб. коп", styles["th"]),
        ],
        [
            _paragraph("Дата", styles["th"]),
            _paragraph("Наименование документа", styles["th"]),
            _paragraph("Номер", styles["th"]),
            "",
            "",
        ],
    ]

    body: List[List[Any]] = []
    for index in range(MAX_EXPENSES):
        expense = expenses[index] if index < len(expenses) else None
        if expense:
            body.append([
                _paragraph(expense.get("date", ""), styles["cell_center"]),
                _paragraph(expense.get("document", ""), styles["cell"]),
                _paragraph(expense.get("document_number", ""), styles["cell_center"]),
                _paragraph(expense.get("purpose", ""), styles["cell"]),
                _paragraph(_money(expense.get("amount_cents")), styles["cell_right"]),
            ])
        else:
            body.append(["", "", "", "", ""])

    total_row = [
        _paragraph("Итого", styles["th"]),
        "",
        "",
        "",
        _paragraph(_money(totals.get("spent_cents")), styles["cell_right"]),
    ]

    rows = header + body + [total_row]
    table = Table(rows, colWidths=widths, rowHeights=[None, None] + [19] * MAX_EXPENSES + [None])
    style = [
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("SPAN", (0, 0), (2, 0)),
        ("SPAN", (3, 0), (3, 1)),
        ("SPAN", (4, 0), (4, 1)),
        ("SPAN", (0, len(rows) - 1), (3, len(rows) - 1)),
        ("BACKGROUND", (0, 0), (-1, 1), colors.HexColor("#EDEDED")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 2.5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2.5),
    ]
    table.setStyle(TableStyle(style))
    return table


def build_report_pdf(report: Dict[str, Any]) -> bytes:
    """Собирает бланк отчёта в PDF (одна страница A4)."""
    styles = _styles()
    buffer = io.BytesIO()
    left_margin = 12 * mm
    right_margin = 12 * mm
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=left_margin,
        rightMargin=right_margin,
        topMargin=9 * mm,
        bottomMargin=8 * mm,
        title=f"Авансовый отчёт № {report.get('number', '')}",
        author=report.get("org_name") or "Авансовые отчёты",
        subject="Отчет об израсходованных суммах",
        creator="Авансовые отчёты",
        keywords="авансовый отчет",
    )
    width = A4[0] - left_margin - right_margin

    org_width = width * 0.52
    approve_width = width - org_width - 8

    header = Table(
        [[
            _paragraph(report.get("org_name", ""), styles["org"]),
            _approval_block(styles, report, approve_width),
        ]],
        colWidths=[org_width, approve_width],
    )
    header.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))

    report_date = _parse_date(report.get("report_date"))
    if report_date:
        date_line = (
            f"от «{report_date.day}» {MONTHS_GENITIVE[report_date.month - 1]} "
            f"{report_date.year} г."
        )
    else:
        date_line = ""

    number_and_date = Table(
        [[
            _paragraph(f"№ {report.get('number', '')}", styles["label"]),
            _paragraph(date_line, styles["date_line"]),
        ]],
        colWidths=[width * 0.35, width * 0.65],
    )
    number_and_date.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))

    signature_rows = [
        _signature_row(styles, "Подотчетное лицо", report.get("person_name", ""), width),
        Spacer(1, 6),
        Table(
            [[
                _paragraph("Отчет проверен. К утверждению в сумме:", styles["label"]),
                _markup(
                    f"<u>\u00a0\u00a0{_money((report.get('totals') or {}).get('approved_cents'))}"
                    f"\u00a0\u00a0</u>",
                    styles["value"],
                ),
                _paragraph("руб.коп", styles["label"]),
            ]],
            colWidths=[width * 0.52, width * 0.22, width * 0.26],
            style=TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
            ]),
        ),
        Spacer(1, 8),
        _signature_row(
            styles,
            report.get("accountant_position") or "Бухгалтер",
            report.get("accountant_name") or "",
            width,
        ),
    ]

    created_at = report.get("created_at") or ""
    created_text = ""
    try:
        created_text = datetime.fromisoformat(str(created_at).replace("Z", "+00:00")).strftime(
            "%d.%m.%Y %H:%M"
        )
    except ValueError:
        created_text = str(created_at)

    story = [
        header,
        Spacer(1, 6),
        _paragraph("Отчет об израсходованных суммах", styles["title"]),
        number_and_date,
        Spacer(1, 5),
        _field_row(styles, "Подотчетное лицо", report.get("person_name", ""), width,
                   "(фамилия, инициалы)"),
        Spacer(1, 4),
        _field_row(styles, "Должность служащего (профессия рабочего)",
                   report.get("person_position", ""), width),
        Spacer(1, 4),
        _field_row(styles, "Назначение аванса", report.get("purpose", ""), width),
        Spacer(1, 7),
        _amounts_table(styles, report, width),
        Spacer(1, 7),
        _expenses_table(styles, report, width),
        Spacer(1, 10),
        *signature_rows,
        Spacer(1, 10),
        _paragraph(
            f"Отчёт № {report.get('number', '')} · сформирован {created_text}",
            styles["tiny"],
        ),
    ]

    doc.build(story)
    return buffer.getvalue()


def report_pdf_filename(report: Dict[str, Any]) -> str:
    number = str(report.get("number") or "report")
    person = str(report.get("person_name") or "").strip().replace(" ", "_")
    filename = f"Авансовый_отчет_{number}"
    if person:
        filename += f"_{person}"
    return filename + ".pdf"
