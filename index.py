# -*- coding: utf-8 -*-
# Точка входа для Vercel — используем безопасный api.index (с fallback), а не api_miniapp напрямую
from api.index import app, handler
