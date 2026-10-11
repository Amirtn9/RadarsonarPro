#!/usr/bin/env bash
# Optional: install API only. This does not open a public port or provision TLS.
set -euo pipefail
if [[ "$EUID" -ne 0 ]]; then echo 'Run as root on the bot host.'; exit 1; fi
APP_HOME=/opt/radar-sonar
if [[ ! -x "$APP_HOME/venv/bin/python" ]];then echo "Bot not installed at $APP_HOME";exit 1;fi
"$APP_HOME/venv/bin/python" -m pip install -r "$APP_HOME/requirements-web.txt"
cat >/etc/systemd/system/sonar-web.service <<EOF
[Unit]
Description=Sonar Radar Pro Mini App backend
After=network.target postgresql.service sonar-bot.service
[Service]
Type=simple
User=sonar-bot
Group=sonar-bot
WorkingDirectory=$APP_HOME
EnvironmentFile=/etc/sonar-bot.env
Environment=SONAR_DB_POOL_MAX=12
ExecStart=$APP_HOME/venv/bin/uvicorn pro_portal:app --host 127.0.0.1 --port 8090 --workers 2
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$APP_HOME /var/log/sonar
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now sonar-web
printf '%s\n' 'Web API started on http://127.0.0.1:8090 (LOCAL ONLY).' \
 'Configure a secure HTTPS reverse proxy to this port.' \
 'Set SONAR_WEBAPP_URL=https://your-domain.example/ in /etc/sonar-bot.env and restart sonar-bot.' \
 'Do NOT expose port 8090 directly to the internet.'
