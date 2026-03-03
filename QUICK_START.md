# 🚀 Быстрый запуск VPN Telegram Bot

## ⚡ За 5 минут до запуска

### 1️⃣ Установите зависимости
```bash
python install_dependencies.py
```

### 2️⃣ Настройте конфигурацию
```bash
# Скопируйте пример
cp .env.example .env

# Отредактируйте .env файл
nano .env
```

**Обязательно настройте:**
- `BOT_TOKEN` - получите у @BotFather
- `ADMIN_IDS` - ваш Telegram ID

### 3️⃣ Запустите бота
```bash
python start_bot.py
```

## 🛠️ Альтернативные способы запуска

### Прямой запуск
```bash
python bot/main.py
```

### Демонстрация
```bash
python demo_bot.py
```

### Тестирование настройки
```bash
python test_setup.py
```

## 📱 Mini App (кнопка «Открыть приложение»)

Чтобы кнопка открывала приложение, а не 404:
1. Запустите **`задеплоить_miniapp.bat`** (деплой папки `webapp` на Vercel).
2. Скопируйте выданный URL (например `https://bitvpn.vercel.app`) в `.env`:  
   `WEBAPP_URL=https://ваш-адрес.vercel.app`
3. Перезапустите бота. Подробно: **MINI_APP_VERCEL.md**.

## ❓ Частые проблемы

### Mini App: «404: NOT_FOUND»
В `.env` указан адрес, на котором ничего не развёрнуто. Задеплойте Mini App по инструкции **MINI_APP_VERCEL.md** и подставьте в `WEBAPP_URL` **тот URL, который выдаст Vercel**.

### Ошибка "ModuleNotFoundError: No module named 'telegram'"
**Решение:** Установите зависимости
```bash
pip install -r requirements.txt
```

### Ошибка "BOT_TOKEN is required"
**Решение:** 
1. Создайте бота у @BotFather в Telegram
2. Скопируйте токен в файл `.env`

### Ошибка "At least one ADMIN_ID is required"
**Решение:**
1. Узнайте свой Telegram ID (@userinfobot)
2. Добавьте в `.env`: `ADMIN_IDS=ваш_id`

## 📞 Поддержка

Если что-то не работает:
1. Запустите `python test_setup.py` для диагностики
2. Проверьте файл `.env`
3. Убедитесь, что Python версии 3.8+

---

**🎯 После запуска бот будет доступен в Telegram и готов к работе!**