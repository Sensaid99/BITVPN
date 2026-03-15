#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка ответа Happ API list-install (для отладки счётчика «Подключено»).

Запуск из корня проекта:
  python scripts/test_happ_list_install.py
  python scripts/test_happ_list_install.py yHmESPsZKd76   # проверить, есть ли этот код в списке
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env"))
except Exception:
    pass


def main():
    api_url = (os.environ.get("HAPP_API_URL") or "https://happ-proxy.com").strip().rstrip("/")  # list-install на happ-proxy.com; api.happ-proxy.com даёт 404
    provider = (os.environ.get("HAPP_PROVIDER_CODE") or "").strip()
    auth_key = (os.environ.get("HAPP_AUTH_KEY") or "").strip()
    check_code = (sys.argv[1] or "").strip() if len(sys.argv) > 1 else None

    if not provider or not auth_key:
        print("Задайте в .env: HAPP_PROVIDER_CODE, HAPP_AUTH_KEY")
        sys.exit(1)

    url = f"{api_url}/api/list-install"
    params = {"provider_code": provider, "auth_key": auth_key}

    try:
        import requests
        r = requests.get(url, params=params, headers={"Accept": "application/json"}, timeout=15)
        data = r.json() if r.ok else {}
    except Exception as e:
        print("Ошибка запроса:", e)
        sys.exit(1)

    print("rc =", data.get("rc"), "| msg =", data.get("msg"))
    if data.get("rc") != 1:
        print("Полный ответ:", json.dumps(data, ensure_ascii=False, indent=2)[:1500])
        sys.exit(1)

    items = data.get("data") or data.get("obj") or data.get("list") or []
    if isinstance(items, dict):
        items = items.get("list") or []
    if not isinstance(items, list):
        items = []

    print("Всего записей:", len(items))
    if items and isinstance(items[0], dict):
        print("Ключи в первой записи:", list(items[0].keys()))

    if check_code and len(check_code) == 12:
        for i, item in enumerate(items):
            code = (item.get("install_code") or item.get("installCode") or item.get("install_id") or "").strip()
            if code and code.lower() == check_code.lower():
                print("Найдено: install_code =", code, "| install_count =", item.get("install_count", item.get("installCount")), "| install_limit =", item.get("install_limit", item.get("installLimit")))
                sys.exit(0)
        print("Код", check_code, "в списке не найден. Убедитесь, что в Happ добавлена ссылка из приложения (Скопировать ссылку).")
        if items:
            print("Примеры кодов в ответе (первые 6 символов):", [str(item.get("install_code") or item.get("installCode") or item.get("install_id"))[:6] for item in items[:8]])
    elif items:
        print("Первые 3 записи (сокращённо):")
        for i, item in enumerate(items[:3]):
            code = (item.get("install_code") or item.get("installCode") or item.get("install_id") or "")
            print("  ", code, "| count =", item.get("install_count", item.get("installCount")), "| limit =", item.get("install_limit", item.get("installLimit")))


if __name__ == "__main__":
    main()
