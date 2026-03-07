# -*- coding: utf-8 -*-
"""
Точка входа API для Vercel Serverless.
Если основной API не загружается — отдаём простую страницу, чтобы не было 500 в браузере.
"""
import sys
import os

# Корень проекта — родитель папки api/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

try:
    from api_miniapp import app
except Exception:
    # Запасной вариант: минимальное приложение, чтобы не падать с 500 при открытии в браузере
    from fastapi import FastAPI
    from fastapi.responses import Response
    app = FastAPI()
    _html = b"<!DOCTYPE html><html><head><meta charset=\"utf-8\"><title>Bit VPN</title></head><body><p>Bit VPN</p><p>Откройте приложение в Telegram: <a href=\"https://t.me/Bitvpnproxy_bot\">@Bitvpnproxy_bot</a></p></body></html>"
    @app.api_route("/{path:path}", methods=["GET", "POST"])
    def fallback(path: str = ""):
        return Response(content=_html, media_type="text/html; charset=utf-8")

from mangum import Mangum
handler = Mangum(app, lifespan="off")
