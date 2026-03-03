# -*- coding: utf-8 -*-
"""
Локальный сервер для Mini App (webapp).
Запуск: python server_webapp.py
Для Telegram нужен HTTPS: используйте ngrok (ngrok http 8080) и подставьте URL в .env → WEBAPP_URL
"""
import os
import http.server
import socketserver

PORT = int(os.getenv("WEBAPP_PORT", "8080"))
DIR = os.path.join(os.path.dirname(__file__), "webapp")
os.chdir(DIR)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIR, **kwargs)

    def log_message(self, msg, *args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


if __name__ == "__main__":
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print("Mini App: http://localhost:%s" % PORT)
        print("Для Telegram: ngrok http %s → скопируйте https URL в .env (WEBAPP_URL)" % PORT)
        httpd.serve_forever()
