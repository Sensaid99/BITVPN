# -*- coding: utf-8 -*-
"""
Отдельная минимальная функция только для GET / — без FastAPI и без импорта api_miniapp.
Так главная страница не падает, даже если основной API крэшится при загрузке.
"""
import os
from http.server import BaseHTTPRequestHandler

# Путь к public/index.html относительно этого файла (api/root.py)
_HTML_PATH = os.path.join(os.path.dirname(__file__), "..", "public", "index.html")

_FALLBACK_HTML = b"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Bit VPN</title></head><body><p>Bit VPN</p><p>Файл public/index.html не найден. Загрузите его в репозиторий и задеплойте снова.</p></body></html>"""


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            if os.path.isfile(_HTML_PATH):
                with open(_HTML_PATH, "rb") as f:
                    body = f.read()
            else:
                body = _FALLBACK_HTML
        except Exception:
            body = _FALLBACK_HTML
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass
