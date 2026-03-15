#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Один раз зарегистрировать домен редиректа в Happ (add-domain).
Без этого счётчик «Подключено» не обновляется, когда пользователи добавляют ссылку вида https://ваш-API/sub/КОД.

Запуск из корня проекта: python scripts/happ_add_redirect_domain.py
Требуется .env с HAPP_API_URL, HAPP_PROVIDER_CODE, HAPP_AUTH_KEY, HAPP_SUBSCRIPTION_REDIRECT_BASE.
"""

import hashlib
import os
import sys
from urllib.parse import urlparse

# корень проекта
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except Exception:
    pass


def main():
    # add-domain в документации работает по https://api.happ-proxy.com
    add_domain_base = "https://api.happ-proxy.com"
    provider = (os.environ.get("HAPP_PROVIDER_CODE") or "").strip()
    auth_key = (os.environ.get("HAPP_AUTH_KEY") or "").strip()
    redirect_base = (os.environ.get("HAPP_SUBSCRIPTION_REDIRECT_BASE") or "").strip()

    if not provider or not auth_key:
        print("Задайте в .env: HAPP_PROVIDER_CODE, HAPP_AUTH_KEY")
        sys.exit(1)
    if not redirect_base:
        print("Задайте в .env: HAPP_SUBSCRIPTION_REDIRECT_BASE (например https://155.212.164.135)")
        sys.exit(1)

    parsed = urlparse(redirect_base if "://" in redirect_base else "https://" + redirect_base)
    domain = (parsed.hostname or parsed.path or redirect_base).strip().lower()
    if not domain:
        print("Не удалось извлечь домен из HAPP_SUBSCRIPTION_REDIRECT_BASE:", redirect_base)
        sys.exit(1)

    domain_hash = hashlib.sha256(domain.encode()).hexdigest()
    url = f"{add_domain_base}/api/add-domain"
    params = {"provider_code": provider, "auth_key": auth_key, "domain_hash": domain_hash, "domain_name": domain}

    try:
        import requests
        r = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=15)
        try:
            data = r.json()
        except Exception:
            data = {}
            if r.text:
                print("Ответ не JSON. status =", r.status_code, "| body:", r.text[:400])
        if data.get("rc") == 1:
            print("OK: домен", domain, "зарегистрирован в Happ. Счётчик устройств должен начать обновляться.")
        elif data.get("rc") == 2 or (data.get("msg") and "exist" in str(data.get("msg")).lower()):
            print("OK: домен", domain, "уже зарегистрирован в Happ (rc=2 Domain hash exists).")
            print("Если счётчик всё ещё 0: в Happ удалите подписку и добавьте заново ссылку из приложения (Скопировать ссылку), подождите 1–2 мин, нажмите обновить в приложении.")
        else:
            msg = data.get("msg") or data.get("message") or ("HTTP " + str(r.status_code) if not data else str(data))
            print("Ответ API:", msg, "| rc =", data.get("rc"))
    except Exception as e:
        print("Ошибка запроса:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
