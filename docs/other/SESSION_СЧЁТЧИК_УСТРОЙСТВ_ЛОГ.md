# Лог сессии: счётчик «Подключено» (0/10) не отображается

**Дата:** 15 марта 2025 (продолжим завтра)  
**Проблема:** В мини-приложении в разделе «Устройства» счётчик «Подключено» так и не отображается (остаётся 0/10 или не показывается).

---

## Что сделали

### 1. Откат главного экрана
- Вернули главный экран к исходному виду: убрали блок с иконкой/названием устройства на главной, вернули кнопку «Установить подписку».
- Файлы: `webapp/index.html`, `index.html`, `public/index.html`, `api/root_index.html`.

### 2. Разбор причин, почему счётчик не работает
- Написали, что счётчик берёт данные из API `/api/miniapp/me` → API вызывает Happ `list-install` по `install_code` из ссылки подписки.
- Добавили в `docs/СЧЁТЧИК_УСТРОЙСТВ_ПОШАГОВО.md` раздел «Почему счётчик не отображается или не меняется» (таблица причин).

### 3. Инструкция «куда нажимать»
- Создали `docs/КУДА_НАЖИМАТЬ_СЧЁТЧИК_УСТРОЙСТВ.md`: пошагово — взять ссылку в приложении, добавить в Happ, нажать «↻».
- Добавили раздел «Ноль» — как один раз зарегистрировать домен в Happ (`python scripts/happ_add_redirect_domain.py`).

### 4. Проверка HAPP_API_URL
- Сначала поменяли `HAPP_API_URL` на `https://api.happ-proxy.com` (думая, что без api. 404).
- Потом **проверили запросы**:
  - `https://api.happ-proxy.com/api/list-install` → **404** (эндпоинта нет).
  - `https://happ-proxy.com/api/list-install` → **200**, ответ есть, `rc: 1`, в списке 8 записей.
- Вернули в проекте **`HAPP_API_URL=https://happ-proxy.com`** (без api.).
- Обновлены: `.env`, `bot/config/settings.py`, `.env.example`, `docs/СЧЁТЧИК_УСТРОЙСТВ_ПОШАГОВО.md`, `scripts/test_happ_list_install.py`.

### 5. Регистрация домена в Happ
- Запустили `python scripts/happ_add_redirect_domain.py` — **успешно**: домен `213.165.38.222` уже зарегистрирован (rc=2 Domain hash exists).

### 6. Проверка ответа Happ list-install
- С `HAPP_API_URL=https://happ-proxy.com` и ключами из `.env` запрос к `list-install` возвращает:
  - `rc: 1`, `msg: Ok`, 8 записей.
  - Пример первой: `install_code=yHmESPsZKd76`, `install_count=0`, `install_limit=10`.
- То есть API Happ с нашего ПК с правильным URL и ключами **работает**, данные по установкам приходят.

---

## Что не сделано / не сработало

- **Счётчик в приложении по-прежнему не отображается.**  
  Пользователь сообщает: «счетчик так и не отображается».

- **Не проверяли на сервере:**
  - Какой именно `HAPP_API_URL` в `.env` на сервере (где крутится API: bitecosystem.ru / 213.165.38.222)?
  - Перезапускался ли API после смены URL?
  - Что возвращает `/api/miniapp/me` при открытии «Устройства» — приходят ли в ответе `devices_used` и `devices_limit`?

- **Не проверяли в браузере/приложении:**
  - Открывается ли раздел «Устройства», есть ли кнопка «↻», что приходит с API при нажатии «↻» (сеть/консоль).
  - Не проверяли debug-эндпоинт с сервера:  
    `https://ваш-API/api/miniapp/debug-install-stats?install_code=КОД_12_СИМВОЛОВ`.

---

## Текущее состояние

| Компонент | Статус |
|-----------|--------|
| Локальный `.env` | `HAPP_API_URL=https://happ-proxy.com` |
| Домен в Happ (add-domain) | Зарегистрирован (213.165.38.222) |
| Запрос list-install с ПК | 200, rc=1, 8 записей, есть install_count/install_limit |
| Счётчик в мини-приложении | **Не отображается** |

---

## Что проверить завтра (продолжение)

1. **Сервер API**
   - В `.env` на сервере должно быть `HAPP_API_URL=https://happ-proxy.com` (не api.happ-proxy.com).
   - После правки — перезапуск API (например `sudo systemctl restart miniapp-api`).

2. **Ответ `/api/miniapp/me`**
   - При открытии мини-приложения и раздела «Устройства» смотреть в сети (DevTools) запрос POST на `/api/miniapp/me`.
   - В ответе проверить: есть ли в `subscription` поля `devices_used`, `devices_limit` и не null ли они. Если там null — API на сервере не получает данные от Happ (URL, ключи или ссылка без /sub/CODE).

3. **Debug-эндпоинт**
   - Взять 12 символов кода из ссылки подписки (после `/sub/`).
   - Открыть в браузере:  
     `https://bitecosystem.ru/api/miniapp/debug-install-stats?install_code=XXXXXXXXXXXX`  
     (или IP сервера вместо домена).
   - Посмотреть: `found`, `install_count`, `install_limit`, есть ли ошибка про HAPP_*.

4. **Фронт**
   - В разделе «Устройства» при нажатии «↻» вызывается `loadMeFromApi` и затем `fillDevicesFromApi`. В `fillDevicesFromApi` используются `API_ME.subscription.devices_used` и `API_ME.subscription.devices_limit`. Если API не отдаёт их — счётчик останется 0 или пустым.

5. **Ссылка подписки**
   - В БД у пользователя ссылка должна быть вида `https://213.165.38.222/sub/XXXXXXXXXXXX` (12 символов). Если хранится старый формат (без /sub/ или без кода) — `parse_install_code_from_happ_link` вернёт null и get_install_stats не вызовется.

---

## Файлы, которые трогали в этой сессии

- `webapp/index.html`, `index.html`, `public/index.html`, `api/root_index.html` — откат главного экрана.
- `.env` — HAPP_API_URL (сейчас https://happ-proxy.com).
- `bot/config/settings.py` — дефолт HAPP_API_URL.
- `.env.example` — пример HAPP_API_URL.
- `docs/СЧЁТЧИК_УСТРОЙСТВ_ПОШАГОВО.md` — таблица причин, шаги, URL.
- `docs/КУДА_НАЖИМАТЬ_СЧЁТЧИК_УСТРОЙСТВ.md` — пошаговая инструкция + раздел «Ноль» (регистрация домена).
- `scripts/test_happ_list_install.py` — комментарий про URL.
- `docs/other/SESSION_СЧЁТЧИК_УСТРОЙСТВ_ЛОГ.md` — этот лог.

---

*Продолжить: проверить сервер (.env, перезапуск API), ответ /api/miniapp/me, debug-install-stats, при необходимости логи API при запросе me (get_install_stats).*
