# Пошаговая настройка nginx (устранение «Ошибка загрузки» в мини-аппе)

Один документ со всеми шагами: от деплоя с вашего ПК до проверки на сервере.

---

## Этап 1. На вашем ПК (перед деплоем)

**Шаг 1.1.** Убедитесь, что в репозитории есть файлы:
- `deploy/nginx-default-full.conf`
- `deploy/apply-nginx-default.sh`

**Шаг 1.2.** Закоммитьте и запушьте изменения (если ещё не сделали):
```cmd
git add deploy/nginx-default-full.conf deploy/apply-nginx-default.sh deploy/README.txt
git commit -m "nginx: полный конфиг и скрипт применения"
git push origin main
```

---

## Этап 2. Подключение к серверу

**Шаг 2.1.** Подключитесь по SSH к серверу (IP: `155.212.164.135`, домен: `nikolay.lisobyk.fvds.ru`):
```bash
ssh user@155.212.164.135
```
(подставьте своего пользователя вместо `user`)

**Шаг 2.2.** Перейдите в каталог проекта:
```bash
cd /opt/vpn-bot
```
(если проект лежит в другом каталоге — замените путь)

---

## Этап 3. Обновление кода на сервере

**Шаг 3.1.** Подтяните последние изменения из репозитория:
```bash
git pull
```

**Шаг 3.2.** Проверьте, что появился файл конфига:
```bash
ls -la deploy/nginx-default-full.conf deploy/apply-nginx-default.sh
```
Оба файла должны существовать.

---

## Этап 4. Сертификат для доступа по IP (один раз)

Нужен для работы ссылок вида `https://155.212.164.135/sub/КОД`.

**Шаг 4.1.** Создайте каталог для сертификатов (если его нет):
```bash
sudo mkdir -p /etc/nginx/ssl
```

**Шаг 4.2.** Создайте самоподписанный сертификат для IP:
```bash
sudo openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/155.212.164.135.key \
  -out /etc/nginx/ssl/155.212.164.135.crt \
  -subj "/CN=155.212.164.135" -addext "subjectAltName=IP:155.212.164.135"
```

**Шаг 4.3.** Проверьте, что файлы созданы:
```bash
ls -la /etc/nginx/ssl/155.212.164.135.*
```

---

## Этап 5. Сертификат для домена (если ещё нет)

Нужен для мини-аппа с `?api=https://nikolay.lisobyk.fvds.ru`.

**Шаг 5.1.** Если Let's Encrypt для домена уже настроен — переходите к этапу 6.

**Шаг 5.2.** Если нет — установите certbot (пример для Ubuntu/Debian):
```bash
sudo apt update
sudo apt install -y certbot python3-certbot-nginx
```

**Шаг 5.3.** Получите сертификат (nginx на время остановится или будет перезаписан — лучше делать до применения нашего конфига или после временного отключения блоков для домена):
```bash
sudo certbot certonly --nginx -d nikolay.lisobyk.fvds.ru
```

**Шаг 5.4.** Проверьте, что сертификаты на месте:
```bash
sudo ls -la /etc/letsencrypt/live/nikolay.lisobyk.fvds.ru/
```
Должны быть `fullchain.pem` и `privkey.pem`.

---

## Этап 6. Применение конфига nginx

**Шаг 6.1.** Запустите скрипт (он сделает бэкап старого default, подставит новый и перезагрузит nginx):
```bash
sudo bash /opt/vpn-bot/deploy/apply-nginx-default.sh
```

**Шаг 6.2.** Если скрипт выдал ошибку `nginx -t`:
- Проверьте, что сертификат для IP создан (этап 4).
- Если домен ещё не настроен — откройте конфиг и закомментируйте весь блок `server { ... server_name nikolay.lisobyk.fvds.ru; ... }` в конце файла:
  ```bash
  sudo nano /etc/nginx/sites-available/default
  ```
  Закомментируйте строки от `# HTTPS по домену` до закрывающей `}` этого блока. Сохраните (Ctrl+O, Enter, Ctrl+X), затем снова:
  ```bash
  sudo nginx -t && sudo systemctl reload nginx
  ```

**Шаг 6.3.** Убедитесь, что nginx перезагрузился без ошибок:
```bash
sudo systemctl status nginx
```
Должно быть `active (running)`.

---

## Этап 7. Проверка

**Шаг 7.1.** Проверка по IP (с сервера или с ПК):
```bash
curl -k -s -o /dev/null -w "%{http_code}" https://155.212.164.135/api/miniapp/plans
```
Ожидается `200`.

**Шаг 7.2.** Проверка по домену (если блок для домена включён):
```bash
curl -s -o /dev/null -w "%{http_code}" https://nikolay.lisobyk.fvds.ru/api/miniapp/plans
```
Ожидается `200`.

**Шаг 7.3.** В браузере откройте мини-апп из бота. В `.env` на сервере (или в ссылке мини-аппа) должен быть указан API по домену, например:
```
WEBAPP_URL=https://ваш-мини-апп.vercel.app?api=https://nikolay.lisobyk.fvds.ru
```
После этого «Ошибка загрузки» должна пропасть, если причина была в недоступности API по домену.

---

## Краткая шпаргалка (если уже всё делали)

1. ПК: `git push origin main`
2. Сервер: `cd /opt/vpn-bot && git pull`
3. Сервер: один раз создать сертификат для IP (этап 4), при необходимости — для домена (этап 5)
4. Сервер: `sudo bash /opt/vpn-bot/deploy/apply-nginx-default.sh`
5. Проверка: `curl -k -s -o /dev/null -w "%{http_code}" https://155.212.164.135/api/miniapp/plans` → 200

---

Если после этих шагов ошибка остаётся — проверьте логи API и список «Нет подписки / ошибка загрузки» в `docs/НЕТ_ПОДПИСКИ_ЧТО_ПРОВЕРИТЬ.md`.
