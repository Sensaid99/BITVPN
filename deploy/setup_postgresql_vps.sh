#!/usr/bin/env bash
# Интерактивная установка PostgreSQL и создание БД под VPN-бота (Ubuntu/Debian).
# Запуск из корня репозитория: sudo bash deploy/setup_postgresql_vps.sh
# Пароль без символа одинарной кавычки ' (или задайте пользователя/БД вручную по VPS_POSTGRES_ПЕРЕНОС_И_ДЕПЛОЙ_ПОШАГОВО.md).

set -euo pipefail

if [[ "${EUID:-0}" -ne 0 ]]; then
  echo "Запустите с sudo: sudo bash $0"
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y postgresql postgresql-contrib
systemctl enable --now postgresql

read -r -p "Имя пользователя БД [vpn_bot]: " DB_USER
DB_USER=${DB_USER:-vpn_bot}
read -r -s -p "Пароль пользователя БД (без символа '): " DB_PASS
echo
read -r -p "Имя базы [vpn_bot_db]: " DB_NAME
DB_NAME=${DB_NAME:-vpn_bot_db}

sudo -u postgres psql -v ON_ERROR_STOP=1 -c "DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '${DB_USER}') THEN
    CREATE ROLE \"${DB_USER}\" LOGIN PASSWORD '${DB_PASS}';
  ELSE
    ALTER ROLE \"${DB_USER}\" WITH PASSWORD '${DB_PASS}';
  END IF;
END \$\$;"

if ! sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1; then
  sudo -u postgres createdb -O "${DB_USER}" "${DB_NAME}"
fi

sudo -u postgres psql -d "${DB_NAME}" -v ON_ERROR_STOP=1 -c "GRANT ALL ON SCHEMA public TO \"${DB_USER}\";"

echo ""
echo "=== Готово ==="
echo "Добавьте в .env (спецсимволы в пароле закодируйте для URL):"
echo "DATABASE_URL=postgresql://${DB_USER}:ПАРОЛЬ@127.0.0.1:5432/${DB_NAME}"
echo ""
echo "Проверка: sudo -u postgres psql -d ${DB_NAME} -c \"SELECT 1;\""
