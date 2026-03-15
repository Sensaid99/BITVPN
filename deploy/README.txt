Папка deploy/ — скрипты и конфиги для сервера.
Все файлы здесь входят в репозиторий (не в .gitignore). При деплое (ДЕПЛОЙ_НА_СЕРВЕР.bat) они попадают на сервер через git pull.

Файлы:
- apply-nginx-sub.sh       — добавляет location /sub/ в nginx (запускается при деплое).
- apply-nginx-default.sh   — копирует nginx-default-full.conf в default и перезагружает nginx.
- nginx-default-full.conf  — полный пример sites-available/default (IP + домен, /sub/ и /api/).
- check-sub-url.sh         — диагностика ссылки /sub/ (запуск вручную на сервере).
- nginx-miniapp-api.conf   — образец location /sub/ и /api/.
- nginx-https-by-ip.conf   — образец server для HTTPS по IP (ручная настройка).
- vpn-bot.service, miniapp-api.service — systemd (копировать вручную при первой настройке).

Чтобы убрать «Ошибку загрузки» в мини-аппе — пошагово: docs/deploy/ПОШАГОВО_NGINX_И_ОШИБКА_ЗАГРУЗКИ.md
(кратко: деплой → git pull на сервере → сертификат для IP → sudo bash deploy/apply-nginx-default.sh).

Подробнее: docs/deploy/ЧТО_ДЕПЛОИТСЯ_И_КУДА.md
