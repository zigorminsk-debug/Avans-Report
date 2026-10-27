"""Автономная версия «Авансовые отчёты» — локальный сервер без входа в систему.

Особенности:
* нет пользователей, паролей и базы данных — любой, кто запустил программу,
  сразу формирует отчёт;
* отчёты сохраняются в PDF (и JSON) в личную папку сессии;
* один сервер обслуживает несколько одновременных запусков: второе окно
  программы не падает с «порт занят», а подключается к уже работающему серверу;
  в одном окне можно открыть сколько угодно вкладок — каждая ведёт свою сессию.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app import pdf_export
from app.numberwords import amount_in_words
from app.reports import ReportIn
from app.version import GITHUB_REPO, __version__

from . import config, storage

logger = logging.getLogger("avans.standalone")

SESSION_HEADER = "x-session-id"


def _safe_session(value: Optional[str]) -> str:
    raw = (value or "").strip()
    safe = "".join(ch for ch in raw if ch.isalnum() or ch in "-_")[:48]
    if len(safe) >= 8:
        return safe
    return config.new_session_id()


def _instance_port() -> Optional[int]:
    """Порт запущенного сервера — для запросов через прокси без порта в Host."""
    try:
        payload = json.loads(config.instance_path().read_text(encoding="utf-8"))
        port = payload.get("port")
        return int(port) if port else None
    except (OSError, ValueError, TypeError):
        return None


def _disposition(kind: str, filename: str, fallback: str) -> str:
    """Content-Disposition с поддержкой кириллических имён (RFC 5987)."""
    import urllib.parse

    quoted = urllib.parse.quote(filename)
    return f"{kind}; filename=\"{fallback}\"; filename*=UTF-8''{quoted}"


def _folder(request: Request) -> Path:
    session_id = _safe_session(request.headers.get(SESSION_HEADER))
    return config.session_dir(session_id)


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.cleanup_old_sessions()
    logger.info("Автономный режим. Данные: %s", config.data_dir())
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=config.APP_NAME,
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )

    shared = config.shared_static_dir()
    if shared.exists():
        app.mount("/shared", StaticFiles(directory=str(shared)), name="shared")
    own = config.standalone_static_dir()
    if own.exists():
        app.mount("/static", StaticFiles(directory=str(own)), name="static")

    @app.middleware("http")
    async def no_cache(request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.url.path.startswith("/api/") or request.url.path in ("/", "/index.html"):
            response.headers["Cache-Control"] = "no-store"
        return response

    # ------------------------------------------------------------------
    # Служебные
    # ------------------------------------------------------------------
    @app.get("/api/health")
    def health(request: Request) -> Dict[str, Any]:
        return {
            "status": "ok",
            "app": config.APP_NAME,
            "version": __version__,
            "mode": "standalone",
            "port": request.url.port or _instance_port(),
            "data_dir": str(config.data_dir()),
        }

    @app.get("/api/info")
    def info(request: Request) -> Dict[str, Any]:
        session_id = _safe_session(request.headers.get(SESSION_HEADER))
        folder = config.session_dir(session_id)
        stats = storage.session_stats(folder)
        return {
            "app_name": config.APP_NAME,
            "version": __version__,
            "github_repo": GITHUB_REPO,
            "session_id": session_id,
            "storage": {
                "mode": "shared",
                "folder": stats["folder"],
                "writable": True,
                "count": stats["count"],
                "total_cents": stats["total_cents"],
            },
            "settings": config.read_settings(),
            "platform": "windows" if sys.platform.startswith("win") else sys.platform,
            "login_required": False,
        }

    @app.post("/api/session")
    def new_session() -> Dict[str, Any]:
        session_id = config.new_session_id()
        folder = config.session_dir(session_id)
        return {"session_id": session_id, "folder": str(folder)}

    @app.post("/api/open-folder")
    def open_folder(request: Request) -> Dict[str, Any]:
        """Открывает папку с отчётами в проводнике (программа работает на этом же ПК)."""
        folder = _folder(request)
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))  # type: ignore[attr-defined]  # noqa: S606
            elif sys.platform == "darwin":
                import subprocess

                subprocess.Popen(["open", str(folder)])  # noqa: S603,S607
            else:
                import subprocess

                subprocess.Popen(["xdg-open", str(folder)])  # noqa: S603,S607
        except OSError as exc:  # pragma: no cover
            raise HTTPException(status_code=500, detail=f"Не удалось открыть папку: {exc}") from exc
        return {"ok": True, "folder": str(folder)}

    # ------------------------------------------------------------------
    # Настройки (общие для программы, без авторизации)
    # ------------------------------------------------------------------
    @app.get("/api/settings")
    def get_settings() -> Dict[str, Any]:
        return {"settings": config.read_settings()}

    @app.put("/api/settings")
    def put_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
        allowed = set(config.DEFAULT_SETTINGS)
        values = {k: v for k, v in (payload or {}).items() if k in allowed}
        if "purposes" in values:
            purposes = [str(item).strip() for item in values["purposes"] if str(item).strip()]
            values["purposes"] = purposes[:20] or config.DEFAULT_SETTINGS["purposes"]
        return {"ok": True, "settings": config.write_settings(values)}

    # ------------------------------------------------------------------
    # Отчёты
    # ------------------------------------------------------------------
    def _report_from_payload(payload: ReportIn, number: str) -> Dict[str, Any]:
        report = storage.build_report(payload, config.read_settings(), number)
        return storage.stamp(report)

    @app.post("/api/prepare")
    def prepare(request: Request, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Готовит отчёт (номер, итоги, сумма прописью) без сохранения на сервере.

        Используется предпросмотром PDF и режимом, когда браузер сохраняет файлы
        в выбранную пользователем папку самостоятельно.
        """
        raw = payload.get("payload") if isinstance(payload, dict) else None
        if raw is None:
            raw = payload
        try:
            data = ReportIn(**raw)
        except Exception as exc:  # noqa: BLE001 - текст ошибки показываем пользователю
            detail = str(exc)
            raise HTTPException(status_code=422, detail=detail) from exc
        requested = payload.get("number") if isinstance(payload, dict) else None
        number = requested if isinstance(requested, str) and requested.strip() else (
            storage.next_number(_folder(request), data.report_date.year)
        )
        report = storage.stamp(storage.build_report(data, config.read_settings(), number))
        return {"report": report, "number": number}

    @app.post("/api/pdf")
    def make_pdf(report: Dict[str, Any]) -> Response:
        """PDF по готовому представлению отчёта (для сохранения в папку браузером)."""
        if not isinstance(report, dict) or "totals" not in report:
            raise HTTPException(status_code=422, detail="Некорректные данные отчёта")
        content = pdf_export.build_report_pdf(report)
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline; filename=\"report.pdf\""},
        )

    @app.get("/api/number")
    def preview_number(request: Request, year: Optional[int] = None) -> Dict[str, Any]:
        from datetime import date as date_cls

        folder = _folder(request)
        target_year = int(year or date_cls.today().year)
        return {"number": storage.next_number(folder, target_year), "year": target_year}

    @app.get("/api/reports")
    def list_reports(request: Request) -> Dict[str, Any]:
        folder = _folder(request)
        items = storage.list_reports(folder)
        stats = storage.session_stats(folder)
        return {
            "items": items,
            "count": len(items),
            "total_cents": stats["total_cents"],
            "folder": stats["folder"],
            "session_id": folder.name,
        }

    @app.post("/api/reports", status_code=201)
    def create_report(payload: ReportIn, request: Request) -> Dict[str, Any]:
        folder = _folder(request)
        try:
            saved = storage.save_new_report(
                folder, payload, config.read_settings(), payload.report_date.year
            )
        except storage.StorageError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {
            "report": saved["report"],
            "files": saved["files"],
            "folder": str(folder),
            "number": saved["number"],
        }

    @app.get("/api/reports/{number}")
    def get_report(number: str, request: Request) -> Dict[str, Any]:
        report = storage.load_report(_folder(request), number)
        if report is None:
            raise HTTPException(status_code=404, detail="Отчёт не найден")
        return {"report": report}

    @app.get("/api/reports/{number}/pdf")
    def report_pdf(number: str, request: Request, download: int = 0) -> Response:
        folder = _folder(request)
        report = storage.load_report(folder, number)
        if report is None:
            raise HTTPException(status_code=404, detail="Отчёт не найден")
        pdf_path = folder / f"{number}.pdf"
        disposition = "attachment" if download else "inline"
        filename = pdf_export.report_pdf_filename(report)
        header = _disposition(disposition, filename, "report.pdf")
        if pdf_path.exists():
            return FileResponse(
                str(pdf_path), media_type="application/pdf",
                headers={"Content-Disposition": header},
            )
        content = pdf_export.build_report_pdf(report)
        return Response(
            content=content, media_type="application/pdf",
            headers={"Content-Disposition": header},
        )

    @app.get("/api/reports/{number}/json")
    def report_json(number: str, request: Request):
        folder = _folder(request)
        path = folder / f"{number}.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="Отчёт не найден")
        return FileResponse(
            str(path), media_type="application/json",
            headers={"Content-Disposition": _disposition("attachment", path.name, "report.json")},
        )

    @app.delete("/api/reports/{number}")
    def delete_report(number: str, request: Request) -> Dict[str, Any]:
        if not storage.delete_report(_folder(request), number):
            raise HTTPException(status_code=404, detail="Отчёт не найден")
        return {"ok": True}

    # ------------------------------------------------------------------
    # Обновления
    # ------------------------------------------------------------------
    @app.get("/api/update/check")
    def update_check(force: int = 0) -> Dict[str, Any]:
        from app import updates

        info = updates.check_for_updates(force=bool(force), asset_prefix="AvansStandalone")
        info["current_version"] = __version__
        info["can_install"] = bool(info.get("update_available") and updates.supports_self_update())
        return info

    @app.post("/api/update/install")
    def update_install() -> Dict[str, Any]:
        from app import updates

        current = updates.check_for_updates(force=True, asset_prefix="AvansStandalone")
        try:
            return updates.install_update(current, make_backup=False)
        except updates.UpdateError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/version")
    def version() -> Dict[str, Any]:
        return {"version": __version__, "app_name": config.APP_NAME, "mode": "standalone"}

    # ------------------------------------------------------------------
    # Интерфейс
    # ------------------------------------------------------------------
    @app.get("/", include_in_schema=False)
    def index():
        path = config.standalone_static_dir() / "index.html"
        if not path.exists():
            return JSONResponse(status_code=500, content={"detail": "Интерфейс не найден"})
        return FileResponse(str(path), media_type="text/html")

    @app.get("/favicon.svg", include_in_schema=False)
    def favicon():
        for candidate in (config.standalone_static_dir() / "favicon.svg",
                          config.shared_static_dir() / "favicon.svg"):
            if candidate.exists():
                return FileResponse(str(candidate), media_type="image/svg+xml")
        raise HTTPException(status_code=404)

    @app.get("/{full_path:path}", include_in_schema=False)
    def fallback(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Не найдено")
        path = config.standalone_static_dir() / "index.html"
        return FileResponse(str(path), media_type="text/html")

    return app


app = create_app()


def main(argv=None) -> int:
    from .launcher import run

    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
