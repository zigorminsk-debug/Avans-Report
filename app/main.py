"""HTTP-сервер приложения «Авансовые отчёты» (FastAPI)."""

from __future__ import annotations

import io
import json
import logging
import os
import re
import sqlite3
import urllib.parse
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import config, db, emailer, reports, updates
from .numberwords import amount_in_words, format_money
from .security import (
    PasswordPolicyError,
    expires_at,
    hash_password,
    login_throttle,
    new_token,
    token_hash,
    validate_password,
    validate_username,
    verify_password,
)
from .version import APP_NAME, GITHUB_REPO, __version__

logger = logging.getLogger("avans")

ROLE_LABELS = {"admin": "Администратор", "supervisor": "Супервайзер", "user": "Пользователь"}
USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-zА-Яа-я]{2,}$")


# --------------------------------------------------------------------------
# Схемы запросов
# --------------------------------------------------------------------------
class LoginIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    username: str
    password: str


class SetupIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    username: str
    password: str
    full_name: str = Field(min_length=3, max_length=200)
    org_name: str = Field(default="", max_length=200)


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str


class ProfileIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    full_name: str = Field(min_length=3, max_length=200)
    position: str = Field(default="", max_length=200)
    email: str = Field(default="", max_length=200)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str) -> str:
        value = (value or "").strip()
        if value and not EMAIL_RE.match(value):
            raise ValueError("Некорректный адрес электронной почты")
        return value


class UserIn(ProfileIn):
    username: str
    role: str = "user"
    password: str = Field(min_length=8, max_length=256)


class UserPatch(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    full_name: Optional[str] = None
    position: Optional[str] = None
    email: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class EmailIn(BaseModel):
    to: str = ""
    comment: str = Field(default="", max_length=2000)


class SmtpIn(BaseModel):
    host: str = ""
    port: int = 587
    security: str = "starttls"
    username: str = ""
    password: str = ""
    from_email: str = ""
    from_name: str = APP_NAME
    subject_prefix: str = "Авансовый отчёт"


class SettingsIn(BaseModel):
    org_name: str = ""
    director_position: str = ""
    director_name: str = ""
    accountant_position: str = ""
    accountant_name: str = ""
    default_recipient: str = ""
    purposes: List[str] = Field(default_factory=list)
    session_hours: int = 12
    smtp: SmtpIn = Field(default_factory=SmtpIn)


class SmtpTestIn(BaseModel):
    recipient: str
    smtp: Optional[SmtpIn] = None


# --------------------------------------------------------------------------
# Аутентификация
# --------------------------------------------------------------------------
def _extract_token(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    return request.cookies.get("avans_token", "") or ""


def current_user(request: Request) -> sqlite3.Row:
    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Требуется вход в систему")
    with db.session() as conn:
        row = db.query_one(
            conn,
            "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.token_hash = ? AND s.expires_at > ?",
            (token_hash(token), db.now_iso()),
        )
    if row is None:
        raise HTTPException(status_code=401, detail="Сессия истекла, войдите заново")
    if not int(row["is_active"]):
        raise HTTPException(status_code=403, detail="Учётная запись заблокирована")
    return row


def require_roles(*roles: str):
    def dependency(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
        if roles and user["role"] not in roles:
            raise HTTPException(status_code=403, detail="Недостаточно прав для этого действия")
        return user

    return dependency


def user_public(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "full_name": row["full_name"],
        "position": row["position"],
        "email": row["email"],
        "role": row["role"],
        "role_label": ROLE_LABELS.get(row["role"], row["role"]),
        "is_active": bool(row["is_active"]),
        "must_change_password": bool(row["must_change_password"]),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"] if "last_login_at" in row.keys() else None,
    }


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _create_session(conn: sqlite3.Connection, user: sqlite3.Row, request: Request,
                    hours: int) -> str:
    token = new_token()
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at, ip, user_agent) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            token_hash(token),
            user["id"],
            db.now_iso(),
            expires_at(hours),
            _client_ip(request),
            (request.headers.get("user-agent") or "")[:300],
        ),
    )
    return token


def _settings_public() -> Dict[str, Any]:
    settings = db.all_settings()
    smtp = dict(settings.get("smtp") or {})
    smtp.pop("password", None)
    return {
        "org_name": settings.get("org_name", ""),
        "director_position": settings.get("director_position", ""),
        "director_name": settings.get("director_name", ""),
        "accountant_position": settings.get("accountant_position", ""),
        "accountant_name": settings.get("accountant_name", ""),
        "default_recipient": settings.get("default_recipient", ""),
        "purposes": settings.get("purposes") or reports.PURPOSE_CHOICES,
        "smtp": smtp,
        "session_hours": settings.get("session_hours", 12),
    }


# --------------------------------------------------------------------------
# Приложение
# --------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    db.ensure_daily_backup()
    try:
        with db.transaction() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (db.now_iso(),))
    except sqlite3.Error:  # pragma: no cover
        logger.warning("Не удалось очистить просроченные сессии", exc_info=True)
    logger.info("Сервер запущен. Данные: %s", config.data_dir())
    yield


_ASSET_RE = re.compile(r'(href|src)="(/static/[^"?]+)"')


def _index_html() -> Optional[str]:
    """index.html со ссылками вида /static/app.js?v=<версия>."""
    path = config.static_dir() / "index.html"
    if not path.exists():
        return None
    html = path.read_text(encoding="utf-8")
    return _ASSET_RE.sub(lambda m: f'{m.group(1)}="{m.group(2)}?v={__version__}"', html)


def create_app() -> FastAPI:
    app = FastAPI(
        title=APP_NAME,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    static_dir = config.static_dir()
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        # Запрещаем кэширование HTML и API, чтобы после обновления не грузился старый интерфейс
        path = request.url.path
        if path.startswith("/api/") or path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-store"
        elif path.startswith("/static/"):
            # Иначе после обновления браузер покажет старый app.js и старые стили
            response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    @app.exception_handler(reports.ReportValidationError)
    async def report_validation_handler(request: Request, exc: reports.ReportValidationError):
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    # ---------------- Служебное ----------------
    @app.get("/api/health")
    def health() -> Dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "app": APP_NAME,
            "time": db.now_iso(),
            "platform": updates.platform_key(),
            "desktop": config.is_frozen() or os.environ.get(config.ENV_DESKTOP) == "1",
        }

    @app.get("/api/public/info")
    def public_info() -> Dict[str, Any]:
        return {
            "app_name": APP_NAME,
            "version": __version__,
            "github_repo": GITHUB_REPO,
            "needs_setup": not db.has_users(),
            "org_name": db.get_setting("org_name", ""),
            "platform": updates.platform_key(),
            "desktop": config.is_frozen() or os.environ.get(config.ENV_DESKTOP) == "1",
        }

    # ---------------- Первичная настройка ----------------
    @app.post("/api/setup")
    def setup(payload: SetupIn, request: Request) -> Dict[str, Any]:
        if db.has_users():
            raise HTTPException(status_code=409, detail="Программа уже настроена")
        try:
            username = validate_username(payload.username)
            validate_password(payload.password)
        except PasswordPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not payload.full_name.strip():
            raise HTTPException(status_code=422, detail="Укажите фамилию и инициалы администратора")

        with db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO users (username, full_name, position, email, role, password_hash, "
                "is_active, must_change_password, created_at) VALUES (?, ?, '', '', 'admin', ?, 1, 0, ?)",
                (username, payload.full_name.strip(), hash_password(payload.password), db.now_iso()),
            )
            admin_id = int(cursor.lastrowid)
            admin = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (admin_id,))
            token = _create_session(conn, admin, request, 12)
            if payload.org_name.strip():
                conn.execute(
                    "UPDATE settings SET value = ? WHERE key = 'org_name'",
                    (json.dumps(payload.org_name.strip(), ensure_ascii=False),),
                )
            db.audit(conn, "setup", actor=admin, entity="user", entity_id=admin_id)
        return {
            "token": token,
            "user": user_public(admin),
            "settings": _settings_public(),
            "version": __version__,
            "github_repo": GITHUB_REPO,
            "platform": updates.platform_key(),
            "self_update_supported": updates.supports_self_update(),
        }

    # ---------------- Вход / профиль ----------------
    @app.post("/api/auth/login")
    def login(payload: LoginIn, request: Request) -> Dict[str, Any]:
        username = (payload.username or "").strip().lower()
        ip = _client_ip(request)
        if login_throttle.is_blocked(username, ip):
            wait = login_throttle.retry_after(username, ip)
            raise HTTPException(
                status_code=429,
                detail=f"Слишком много неудачных попыток входа. Повторите через {wait} с.",
            )
        with db.transaction() as conn:
            row = db.query_one(conn, "SELECT * FROM users WHERE username = ?", (username,))
            if row is None or not verify_password(payload.password, row["password_hash"]):
                login_throttle.register_failure(username, ip)
                raise HTTPException(status_code=401, detail="Неверный логин или пароль")
            if not int(row["is_active"]):
                raise HTTPException(status_code=403, detail="Учётная запись заблокирована")
            login_throttle.reset(username, ip)
            settings = db.all_settings()
            token = _create_session(conn, row, request, int(settings.get("session_hours", 12) or 12))
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (db.now_iso(), row["id"]))
            db.audit(conn, "login", actor=row, entity="user", entity_id=row["id"])
        return {
            "token": token,
            "user": user_public(row),
            "settings": _settings_public(),
            "version": __version__,
            "github_repo": GITHUB_REPO,
            "platform": updates.platform_key(),
            "self_update_supported": updates.supports_self_update(),
        }

    @app.post("/api/auth/logout")
    def logout(request: Request, user: sqlite3.Row = Depends(current_user)) -> Dict[str, Any]:
        token = _extract_token(request)
        with db.transaction() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
            db.audit(conn, "logout", actor=user, entity="user", entity_id=user["id"])
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user: sqlite3.Row = Depends(current_user)) -> Dict[str, Any]:
        return {
            "user": user_public(user),
            "settings": _settings_public(),
            "version": __version__,
            "github_repo": GITHUB_REPO,
            "platform": updates.platform_key(),
            "self_update_supported": updates.supports_self_update(),
        }

    @app.post("/api/auth/change-password")
    def change_password(payload: ChangePasswordIn, request: Request,
                        user: sqlite3.Row = Depends(current_user)) -> Dict[str, Any]:
        if not verify_password(payload.current_password, user["password_hash"]):
            raise HTTPException(status_code=400, detail="Текущий пароль указан неверно")
        try:
            validate_password(payload.new_password)
        except PasswordPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        token = _extract_token(request)
        with db.transaction() as conn:
            conn.execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                (hash_password(payload.new_password), user["id"]),
            )
            conn.execute(
                "DELETE FROM sessions WHERE user_id = ? AND token_hash <> ?",
                (user["id"], token_hash(token)),
            )
            db.audit(conn, "password.change", actor=user, entity="user", entity_id=user["id"])
        return {"ok": True}

    @app.post("/api/auth/profile")
    def update_profile(payload: ProfileIn, user: sqlite3.Row = Depends(current_user)) -> Dict[str, Any]:
        with db.transaction() as conn:
            conn.execute(
                "UPDATE users SET full_name = ?, position = ?, email = ? WHERE id = ?",
                (payload.full_name.strip(), payload.position.strip(), payload.email.strip(), user["id"]),
            )
            row = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (user["id"],))
            db.audit(conn, "profile.update", actor=user, entity="user", entity_id=user["id"])
        return {"user": user_public(row)}

    # ---------------- Отчёты ----------------
    @app.get("/api/reports")
    def list_reports(
        scope: str = "auto",
        user_id: Optional[int] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        status: Optional[str] = None,
        q: str = "",
        limit: int = 200,
        offset: int = 0,
        user: sqlite3.Row = Depends(current_user),
    ) -> Dict[str, Any]:
        for value, label in ((date_from, "дата начала"), (date_to, "дата окончания")):
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=f"Некорректная {label}") from exc
        with db.session() as conn:
            result = reports.list_reports(
                conn,
                user,
                scope=scope,
                owner_id=user_id,
                date_from=date_from,
                date_to=date_to,
                status=status,
                search=q,
                limit=limit,
                offset=offset,
            )
        result["scope"] = "all" if user["role"] in ("admin", "supervisor") and scope != "mine" else "mine"
        return result

    @app.post("/api/reports", status_code=201)
    def create_report(payload: reports.ReportIn,
                      user: sqlite3.Row = Depends(current_user)) -> Dict[str, Any]:
        settings = db.all_settings()
        try:
            with db.transaction() as conn:
                report_id = reports.create_report(conn, user, payload, settings)
                row = reports.get_report(conn, report_id)
        except sqlite3.IntegrityError as exc:  # pragma: no cover
            raise HTTPException(status_code=409, detail="Не удалось сохранить отчёт") from exc
        # Отчёт сохраняется один раз и больше не изменяется (только создание нового).
        return reports.serialize(row)

    @app.get("/api/reports/{report_id}")
    def get_report(report_id: int, user: sqlite3.Row = Depends(current_user)) -> Dict[str, Any]:
        with db.session() as conn:
            row = reports.get_report(conn, report_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Отчёт не найден")
        if not reports.can_view(user, row):
            raise HTTPException(status_code=403, detail="Нет доступа к этому отчёту")
        return reports.serialize(row)

    @app.get("/api/reports/{report_id}/excel")
    def download_excel(report_id: int, user: sqlite3.Row = Depends(current_user)):
        from .excel_export import build_report_xlsx, report_filename

        with db.session() as conn:
            row = reports.get_report(conn, report_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Отчёт не найден")
        if not reports.can_view(user, row):
            raise HTTPException(status_code=403, detail="Нет доступа к этому отчёту")
        report = reports.serialize(row)
        content = build_report_xlsx(report)
        filename = report_filename(report)
        quoted = urllib.parse.quote(filename)
        return Response(
            content=content,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f"attachment; filename=\"report-{report_id}.xlsx\"; "
                                       f"filename*=UTF-8''{quoted}"
            },
        )

    @app.get("/api/reports/{report_id}/pdf")
    def download_pdf(report_id: int, user: sqlite3.Row = Depends(current_user)):
        from .pdf_export import build_report_pdf, report_pdf_filename

        with db.session() as conn:
            row = reports.get_report(conn, report_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Отчёт не найден")
        if not reports.can_view(user, row):
            raise HTTPException(status_code=403, detail="Нет доступа к этому отчёту")
        report = reports.serialize(row)
        content = build_report_pdf(report)
        quoted = urllib.parse.quote(report_pdf_filename(report))
        return Response(
            content=content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=\"report-{report_id}.pdf\"; "
                                       f"filename*=UTF-8''{quoted}"
            },
        )

    @app.post("/api/reports/{report_id}/email")
    def email_report(report_id: int, payload: EmailIn,
                     user: sqlite3.Row = Depends(current_user)) -> Dict[str, Any]:
        with db.session() as conn:
            row = reports.get_report(conn, report_id)
        if row is None:
            raise HTTPException(status_code=404, detail="Отчёт не найден")
        if not reports.can_view(user, row):
            raise HTTPException(status_code=403, detail="Нет доступа к этому отчёту")

        settings = db.all_settings()
        smtp = settings.get("smtp") or {}
        if not emailer.smtp_configured(smtp):
            raise HTTPException(
                status_code=400,
                detail="Почта не настроена. Администратор должен заполнить SMTP-параметры в разделе «Настройки».",
            )
        try:
            recipients = emailer.parse_recipients(payload.to or settings.get("default_recipient"))
        except emailer.EmailError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        report = reports.serialize(row)
        try:
            emailer.send_report(smtp, report, recipients, payload.comment.strip())
        except emailer.EmailError as exc:
            with db.transaction() as conn:
                reports.mark_sent(conn, user, report_id, recipients, False, str(exc))
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:  # pragma: no cover - неожиданные ошибки SMTP
            logger.exception("Ошибка отправки отчёта")
            with db.transaction() as conn:
                reports.mark_sent(conn, user, report_id, recipients, False, str(exc))
            raise HTTPException(status_code=502, detail=f"Не удалось отправить письмо: {exc}") from exc

        with db.transaction() as conn:
            reports.mark_sent(conn, user, report_id, recipients, True)
            row = reports.get_report(conn, report_id)
        return {"ok": True, "report": reports.serialize(row), "recipients": recipients}

    @app.delete("/api/reports/{report_id}")
    def delete_report(report_id: int, user: sqlite3.Row = Depends(require_roles("admin"))) -> Dict[str, Any]:
        with db.transaction() as conn:
            row = reports.get_report(conn, report_id)
            if row is None:
                raise HTTPException(status_code=404, detail="Отчёт не найден")
            conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
            db.audit(
                conn,
                "report.delete",
                actor=user,
                entity="report",
                entity_id=report_id,
                details={"number": row["number"], "owner": row["username"]},
            )
        return {"ok": True}

    # ---------------- Пользователи ----------------
    @app.get("/api/users")
    def list_users(user: sqlite3.Row = Depends(require_roles("admin", "supervisor"))) -> Dict[str, Any]:
        with db.session() as conn:
            rows = db.query_all(
                conn,
                "SELECT u.*, (SELECT COUNT(*) FROM reports r WHERE r.user_id = u.id) AS report_count "
                "FROM users u ORDER BY u.full_name COLLATE NOCASE",
            )
        items = []
        for row in rows:
            if user["role"] == "supervisor" and row["role"] == "admin":
                continue
            item = user_public(row)
            item["report_count"] = int(row["report_count"])
            items.append(item)
        return {"items": items, "roles": ROLE_LABELS}

    @app.post("/api/users", status_code=201)
    def create_user(payload: UserIn,
                    user: sqlite3.Row = Depends(require_roles("admin", "supervisor"))) -> Dict[str, Any]:
        if payload.role not in ("admin", "supervisor", "user"):
            raise HTTPException(status_code=422, detail="Неизвестная роль")
        if user["role"] == "supervisor" and payload.role != "user":
            raise HTTPException(
                status_code=403,
                detail="Супервайзер может создавать только обычных пользователей",
            )
        try:
            username = validate_username(payload.username)
            validate_password(payload.password)
        except PasswordPolicyError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not payload.full_name.strip():
            raise HTTPException(status_code=422, detail="Укажите ФИО пользователя")
        with db.transaction() as conn:
            existing = db.query_one(conn, "SELECT id FROM users WHERE username = ?", (username,))
            if existing:
                raise HTTPException(status_code=409, detail="Пользователь с таким логином уже есть")
            cursor = conn.execute(
                "INSERT INTO users (username, full_name, position, email, role, password_hash, "
                "is_active, must_change_password, created_at, created_by) "
                "VALUES (?, ?, ?, ?, ?, ?, 1, 1, ?, ?)",
                (
                    username,
                    payload.full_name.strip(),
                    payload.position.strip(),
                    payload.email.strip(),
                    payload.role,
                    hash_password(payload.password),
                    db.now_iso(),
                    user["id"],
                ),
            )
            new_id = int(cursor.lastrowid)
            new_row = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (new_id,))
            db.audit(
                conn, "user.create", actor=user, entity="user", entity_id=new_id,
                details={"username": username, "role": payload.role},
            )
        return {"user": user_public(new_row)}

    @app.patch("/api/users/{user_id}")
    def update_user(user_id: int, payload: UserPatch,
                    user: sqlite3.Row = Depends(require_roles("admin", "supervisor"))) -> Dict[str, Any]:
        with db.transaction() as conn:
            target = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
            if target is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")

            is_admin = user["role"] == "admin"
            if not is_admin:
                if target["role"] != "user" or payload.password is None:
                    raise HTTPException(
                        status_code=403,
                        detail="Супервайзер может только задать новый пароль обычному пользователю",
                    )
                if any(
                    value is not None
                    for value in (payload.full_name, payload.position, payload.email,
                                  payload.role, payload.is_active)
                ):
                    raise HTTPException(
                        status_code=403,
                        detail="Супервайзер не может изменять данные пользователя",
                    )

            updates: Dict[str, Any] = {}
            if payload.full_name is not None:
                if len(payload.full_name.strip()) < 3:
                    raise HTTPException(status_code=422, detail="ФИО слишком короткое")
                updates["full_name"] = payload.full_name.strip()
            if payload.position is not None:
                updates["position"] = payload.position.strip()
            if payload.email is not None:
                email_value = payload.email.strip()
                if email_value and not EMAIL_RE.match(email_value):
                    raise HTTPException(status_code=422, detail="Некорректный e-mail")
                updates["email"] = email_value
            if payload.role is not None:
                if payload.role not in ("admin", "supervisor", "user"):
                    raise HTTPException(status_code=422, detail="Неизвестная роль")
                if target["id"] == user["id"] and payload.role != "admin":
                    raise HTTPException(status_code=422, detail="Нельзя снять права с самого себя")
                updates["role"] = payload.role
            if payload.is_active is not None:
                if target["id"] == user["id"] and not payload.is_active:
                    raise HTTPException(status_code=422, detail="Нельзя заблокировать самого себя")
                updates["is_active"] = 1 if payload.is_active else 0
                if not payload.is_active:
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
            if payload.password is not None:
                try:
                    validate_password(payload.password)
                except PasswordPolicyError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
                updates["password_hash"] = hash_password(payload.password)
                updates["must_change_password"] = 1
                if target["id"] != user["id"]:
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

            if updates:
                assignments = ", ".join(f"{column} = ?" for column in updates)
                conn.execute(
                    f"UPDATE users SET {assignments} WHERE id = ?",
                    list(updates.values()) + [user_id],
                )
            updated = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
            db.audit(
                conn, "user.update", actor=user, entity="user", entity_id=user_id,
                details={"fields": sorted(updates.keys()), "username": updated["username"]},
            )
        return {"user": user_public(updated)}

    @app.delete("/api/users/{user_id}")
    def delete_user(user_id: int, user: sqlite3.Row = Depends(require_roles("admin"))) -> Dict[str, Any]:
        if int(user_id) == int(user["id"]):
            raise HTTPException(status_code=422, detail="Нельзя удалить самого себя")
        with db.transaction() as conn:
            target = db.query_one(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
            if target is None:
                raise HTTPException(status_code=404, detail="Пользователь не найден")
            count = db.query_one(
                conn, "SELECT COUNT(*) AS c FROM reports WHERE user_id = ?", (user_id,)
            )
            if count and int(count["c"]) > 0:
                raise HTTPException(
                    status_code=409,
                    detail="У пользователя есть отчёты. Заблокируйте учётную запись вместо удаления.",
                )
            if target["role"] == "admin":
                admins = db.query_one(
                    conn, "SELECT COUNT(*) AS c FROM users WHERE role = 'admin' AND is_active = 1"
                )
                if admins and int(admins["c"]) <= 1:
                    raise HTTPException(status_code=422, detail="Нельзя удалить последнего администратора")
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            db.audit(
                conn, "user.delete", actor=user, entity="user", entity_id=user_id,
                details={"username": target["username"]},
            )
        return {"ok": True}

    # ---------------- Настройки (администратор) ----------------
    @app.get("/api/settings")
    def get_settings(user: sqlite3.Row = Depends(require_roles("admin"))) -> Dict[str, Any]:
        settings = db.all_settings()
        smtp = dict(settings.get("smtp") or {})
        smtp["password_set"] = bool(smtp.get("password"))
        smtp.pop("password", None)
        settings["smtp"] = smtp
        return {"settings": settings}

    @app.put("/api/settings")
    def save_settings(payload: SettingsIn,
                      user: sqlite3.Row = Depends(require_roles("admin"))) -> Dict[str, Any]:
        purposes = [item.strip() for item in payload.purposes if item and item.strip()][:20]
        if not purposes:
            purposes = list(reports.PURPOSE_CHOICES)
        current = db.all_settings()
        smtp_current = dict(current.get("smtp") or {})
        smtp_new = payload.smtp.model_dump()
        if not smtp_new.get("password"):
            smtp_new["password"] = smtp_current.get("password", "")
        if smtp_new.get("security") not in ("starttls", "ssl", "none"):
            smtp_new["security"] = "starttls"
        values = {
            "org_name": payload.org_name.strip(),
            "director_position": payload.director_position.strip(),
            "director_name": payload.director_name.strip(),
            "accountant_position": payload.accountant_position.strip(),
            "accountant_name": payload.accountant_name.strip(),
            "default_recipient": payload.default_recipient.strip(),
            "purposes": purposes,
            "session_hours": max(1, min(int(payload.session_hours or 12), 720)),
            "smtp": smtp_new,
        }
        with db.transaction() as conn:
            for key, value in values.items():
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, json.dumps(value, ensure_ascii=False)),
                )
            db.audit(conn, "settings.update", actor=user, entity="settings",
                     details={"keys": sorted(values.keys())})
        return {"settings": _settings_public(), "ok": True}

    @app.post("/api/settings/smtp/test")
    def test_smtp(payload: SmtpTestIn,
                  user: sqlite3.Row = Depends(require_roles("admin"))) -> Dict[str, Any]:
        settings = dict(db.get_setting("smtp") or {})
        if payload.smtp is not None:
            candidate = payload.smtp.model_dump()
            if not candidate.get("password"):
                # Пустое поле пароля означает «оставить сохранённый»
                candidate["password"] = settings.get("password", "")
            settings.update(candidate)
        try:
            emailer.test_settings(settings, payload.recipient)
        except emailer.EmailError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"ok": True, "detail": "Тестовое письмо отправлено"}

    # ---------------- Система ----------------
    @app.get("/api/system/info")
    def system_info(user: sqlite3.Row = Depends(require_roles("admin"))) -> Dict[str, Any]:
        database = config.db_path()
        with db.session() as conn:
            counts = {
                "users": int(db.query_one(conn, "SELECT COUNT(*) AS c FROM users")["c"]),
                "reports": int(db.query_one(conn, "SELECT COUNT(*) AS c FROM reports")["c"]),
                "sent": int(
                    db.query_one(conn, "SELECT COUNT(*) AS c FROM reports WHERE status = 'sent'")["c"]
                ),
            }
        backups = sorted(config.backups_dir().glob("avans-*.db"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        return {
            "version": __version__,
            "app_name": APP_NAME,
            "data_dir": str(config.data_dir()),
            "db_path": str(database),
            "db_size": database.stat().st_size if database.exists() else 0,
            "counts": counts,
            "backups": [
                {
                    "name": backup.name,
                    "size": backup.stat().st_size,
                    "mtime": datetime.fromtimestamp(backup.stat().st_mtime).isoformat(timespec="seconds"),
                }
                for backup in backups[:10]
            ],
            "platform": updates.platform_key(),
            "desktop": config.is_frozen() or os.environ.get(config.ENV_DESKTOP) == "1",
            "github_repo": GITHUB_REPO,
        }

    @app.post("/api/system/backup")
    def make_backup(user: sqlite3.Row = Depends(require_roles("admin"))) -> Dict[str, Any]:
        path = db.backup_database(reason="manual")
        with db.transaction() as conn:
            db.audit(conn, "backup.create", actor=user, entity="system",
                     details={"file": path.name})
        return {"ok": True, "file": path.name, "size": path.stat().st_size}

    @app.get("/api/system/backup/download")
    def download_backup(user: sqlite3.Row = Depends(require_roles("admin"))):
        path = db.backup_database(reason="download")
        return FileResponse(
            str(path),
            media_type="application/x-sqlite3",
            filename=path.name,
        )

    @app.get("/api/audit")
    def audit_log(limit: int = 200, user: sqlite3.Row = Depends(require_roles("admin"))) -> Dict[str, Any]:
        limit = max(1, min(int(limit), 1000))
        with db.session() as conn:
            rows = db.query_all(
                conn, "SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,)
            )
        return {
            "items": [
                {
                    "id": row["id"],
                    "ts": row["ts"],
                    "actor": row["actor_name"],
                    "action": row["action"],
                    "entity": row["entity"],
                    "entity_id": row["entity_id"],
                    "details": row["details"],
                }
                for row in rows
            ]
        }

    # ---------------- Обновления ----------------
    @app.get("/api/update/check")
    def update_check(force: int = 0, user: sqlite3.Row = Depends(current_user)) -> Dict[str, Any]:
        info = updates.check_for_updates(force=bool(force))
        info["can_install"] = bool(
            user["role"] == "admin" and info.get("update_available") and updates.supports_self_update()
        )
        info["current_version"] = __version__
        return info

    @app.post("/api/update/install")
    def update_install(user: sqlite3.Row = Depends(require_roles("admin"))) -> Dict[str, Any]:
        info = updates.check_for_updates(force=True)
        try:
            result = updates.install_update(info)
        except updates.UpdateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        with db.transaction() as conn:
            db.audit(conn, "update.install", actor=user, entity="system",
                     details={"version": info.get("latest_version")})
        return result

    @app.get("/api/version")
    def version_info() -> Dict[str, Any]:
        return {
            "version": __version__,
            "app_name": APP_NAME,
            "github_repo": GITHUB_REPO,
            "platform": updates.platform_key(),
        }

    # ---------------- Интерфейс ----------------
    @app.get("/", include_in_schema=False)
    def index():
        page = _index_html()
        if page is None:
            return JSONResponse(status_code=500, content={"detail": "Интерфейс не найден"})
        return HTMLResponse(content=page, headers={"Cache-Control": "no-store, must-revalidate"})

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        path = config.static_dir() / "favicon.svg"
        if path.exists():
            return FileResponse(str(path), media_type="image/svg+xml")
        raise HTTPException(status_code=404)

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Не найдено")
        return RedirectResponse(url="/")

    return app


app = create_app()
