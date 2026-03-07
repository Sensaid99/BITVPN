# -*- coding: utf-8 -*-
"""
Только минимальный HTML без чтения файлов. Страница сама подгружает приложение через /api/fullpage.
Так корень никогда не падает с 500 (нет open(), нет тяжёлого кода).
"""
from http.server import BaseHTTPRequestHandler

# Один раз встроенный HTML: загрузка + запрос полной страницы с /api/fullpage
_BODY = b"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Bit VPN</title></head><body><p>Загрузка...</p><script>
fetch('/api/fullpage').then(function(r){return r.text();}).then(function(html){
  document.open();document.write(html);document.close();
}).catch(function(){
  document.body.innerHTML='<p>Не удалось загрузить. <a href="https://t.me/Bitvpnproxy_bot">@Bitvpnproxy_bot</a></p>';
});
</script></body></html>"""


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(_BODY)))
            self.end_headers()
            self.wfile.write(_BODY)
        except Exception:
            try:
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_BODY)
            except Exception:
                pass

    def do_HEAD(self):
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
        except Exception:
            pass

    def do_POST(self):
        self.do_GET()

    def log_message(self, format, *args):
        pass
