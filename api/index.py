# -*- coding: utf-8 -*-
"""
Точка входа API для Vercel Serverless.
Все запросы переписываются сюда (vercel.json), Mangum передаёт их в FastAPI.
"""
import sys
import os

# Корень проекта — родитель папки api/
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from api_miniapp import app
from mangum import Mangum

handler = Mangum(app, lifespan="off")
