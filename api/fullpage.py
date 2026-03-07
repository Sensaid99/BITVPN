# -*- coding: utf-8 -*-
"""
Отдаёт полный HTML мини-апп (api/root_index.html). При ошибке — минимальная страница (без 500).
"""
import os
from http.server import BaseHTTPRequestHandler

_FALLBACK = b"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Bit VPN</title></head><body><p><a href="https://t.me/Bitvpnproxy_bot">@Bitvpnproxy_bot</a></p></body></html>"""


def _get_html():
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(base, "root_index.html")
        if os.path.isfile(path):
            with open(path, "rb") as f:
                return f.read()
    except Exception:
        pass
    return _FALLBACK


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body = _get_html()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(_FALLBACK)

    def log_message(self, format, *args):
        pass
