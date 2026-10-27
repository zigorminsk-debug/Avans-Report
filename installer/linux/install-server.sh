#!/usr/bin/env bash
# Установка сервера «Авансовые отчёты» на Linux (systemd).
#
#   sudo ./install-server.sh /opt/AvansReport-Linux-x86_64.tar.gz
#
# Скрипт распаковывает сборку, создаёт системного пользователя, каталог данных
# и службу systemd. База данных лежит в /var/lib/avansreport и сохраняется
# при обновлении: достаточно распаковать новую сборку и перезапустить службу.

set -euo pipefail

ARCHIVE="${1:-}"
APP_DIR="/opt/avansreport"
DATA_DIR="/var/lib/avansreport"
SERVICE_USER="avansreport"
PORT="${AVANS_PORT:-8770}"

if [[ -z "$ARCHIVE" || ! -f "$ARCHIVE" ]]; then
  echo "Использование: sudo $0 путь/к/AvansReport-Linux-x86_64-<версия>.tar.gz" >&2
  exit 1
fi

if [[ $EUID -ne 0 ]]; then
  echo "Запустите скрипт от имени root (sudo)." >&2
  exit 1
fi

if ! id "$SERVICE_USER" >/dev/null 2>&1; then
  useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
  echo "Создан системный пользователь $SERVICE_USER"
fi

mkdir -p "$APP_DIR" "$DATA_DIR"
STAGING="$(mktemp -d)"
tar -xzf "$ARCHIVE" -C "$STAGING"
rm -rf "${APP_DIR:?}"/*
cp -r "$STAGING"/AvansReport/* "$APP_DIR"/
rm -rf "$STAGING"
chown -R root:root "$APP_DIR"
chown -R "$SERVICE_USER":"$SERVICE_USER" "$DATA_DIR"
chmod 750 "$DATA_DIR"

cat > /etc/systemd/system/avansreport.service <<EOF
[Unit]
Description=Авансовые отчёты (сервер)
After=network.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
Environment=AVANS_DATA_DIR=$DATA_DIR
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/AvansReport --host 0.0.0.0 --port $PORT --no-browser
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now avansreport.service

sleep 2
if curl -fsS "http://127.0.0.1:$PORT/api/health"; then
  echo
  echo "Сервер запущен: http://$(hostname -I | awk '{print $1}'):$PORT"
  echo "Данные: $DATA_DIR"
  echo "Журнал: journalctl -u avansreport -f"
else
  echo "Не удалось проверить сервер, смотрите: journalctl -u avansreport -n 50" >&2
  exit 1
fi
