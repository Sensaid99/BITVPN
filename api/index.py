# -*- coding: utf-8 -*-
"""
Точка входа API для Vercel. GET / обрабатывается первым.
Для /api/* необработанные ошибки → JSON 500 (чтобы Mini App мог показать сообщение).
Для остальных — минимальный HTML (без 500).
"""
import sys
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fastapi import FastAPI, Request
from fastapi.responses import Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import HTTPException

# Минимальная страница — отдаём при необработанной ошибке на не-API путях
_MINIMAL_HTML = b"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bit VPN</title></head><body><p>Bit VPN</p><p><a href="https://t.me/Bitvpnproxy_bot">@Bitvpnproxy_bot</a></p></body></html>"""


app = FastAPI(title="Bit VPN API")


@app.exception_handler(Exception)
def _catch_all(request: Request, exc: Exception):
    """HTTPException → проброс. Для /api/* — JSON 500. Иначе — 200 + минимальный HTML."""
    if isinstance(exc, HTTPException):
        raise exc
    path = getattr(request, "scope", {}).get("path", "")
    if path.startswith("/api/"):
        return JSONResponse(
            status_code=500,
            content={"detail": "Ошибка сервера. Попробуйте в боте: «Купить VPN»."},
        )
    return Response(content=_MINIMAL_HTML, media_type="text/html; charset=utf-8", status_code=200)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _root_html():
    """Прочитать api/root_index.html (рядом с этим файлом). Не бросает исключений."""
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "root_index.html")
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()
    except Exception:
        pass
    return _MINIMAL_HTML


# Сначала регистрируем корень — они сработают до любых маршрутов из api_miniapp
@app.get("/")
@app.get("/index.html")
def serve_root():
    try:
        body = _root_html()
        return Response(content=body, media_type="text/html; charset=utf-8")
    except Exception:
        return Response(content=_MINIMAL_HTML, media_type="text/html; charset=utf-8")

# Подключаем полный API (тарифы, /api/miniapp/me и т.д.). Если импорт упадёт — для /api/* отдаём JSON, не HTML.
try:
    from api_miniapp import app as miniapp_app
    app.include_router(miniapp_app.router)
except Exception as _e:
    import logging
    logging.getLogger(__name__).warning("api_miniapp import failed (API will return 503): %s", _e)

    @app.api_route("/api/{path:path}", methods=["GET", "POST"])
    def api_fallback(path: str = ""):
        return JSONResponse(
            status_code=503,
            content={
                "detail": "API недоступен на этом сервере. Укажите в ссылке на приложение свой сервер: ?api=https://ваш-домен (см. ЛОГИ_API_НА_СЕРВЕРЕ.txt)"
            },
        )

from mangum import Mangum
handler = Mangum(app, lifespan="off")
