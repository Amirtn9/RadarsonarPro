#!/usr/bin/env bash
# Sonar Radar Pro 5.0 - guarded offline ZIP installer / upgrade
# Ubuntu / Debian systemd hosts only. Run using: sudo bash install.sh
set -Eeuo pipefail
umask 077

INSTALL_DIR="/opt/radar-sonar"
SERVICE_NAME="sonar-bot"
WEB_SERVICE="sonar-web"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
DB_ENV_FILE="/etc/sonar-bot.env"
BACKUP_ROOT="/var/backups/sonar-radar"
LOG_DIR="/var/log/sonar"
LOG_FILE="/var/log/sonar-install.log"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DB_NAME="sonar_ultra_pro"
DB_USER="sonar_user"
STAGE=""
PREVIOUS=""
UNIT_COPY=""
DEPLOY_STARTED=0
PREVIOUS_PRESENT=0
PREV_BOT_RUNNING=0
PREV_WEB_RUNNING=0
ROLLED_BACK=0

info() { printf '\n[+] %s\n' "$*"; }
warn() { printf '\n[!] %s\n' "$*" >&2; }
fail() { printf '\n[ERROR] %s\n' "$*" >&2; return 1; }

cleanup_and_rollback() {
    local rc=$?
    trap - EXIT
    if (( rc != 0 )); then
        warn "Installer aborted with status ${rc}."
        if (( DEPLOY_STARTED == 1 )); then
            warn 'Attempting code/service rollback (database changes are NOT auto-reversed).'
            systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
            systemctl stop "$WEB_SERVICE" >/dev/null 2>&1 || true
            if (( PREVIOUS_PRESENT == 1 )) && [[ -d "$PREVIOUS" ]]; then
                rm -rf -- "$INSTALL_DIR"
                mv -- "$PREVIOUS" "$INSTALL_DIR" || warn 'Could not restore previous application directory!'
            else
                rm -rf -- "$INSTALL_DIR"
            fi
            if [[ -n "$UNIT_COPY" && -f "$UNIT_COPY" ]]; then
                cp -p -- "$UNIT_COPY" "$UNIT_FILE" || true
            elif (( PREVIOUS_PRESENT == 0 )); then
                systemctl disable "$SERVICE_NAME" >/dev/null 2>&1 || true
                rm -f -- "$UNIT_FILE"
            fi
            systemctl daemon-reload >/dev/null 2>&1 || true
            if (( PREVIOUS_PRESENT == 1 && PREV_BOT_RUNNING == 1 )); then
                systemctl start "$SERVICE_NAME" || warn 'Previous bot service failed to restart.'
            fi
            if (( PREV_WEB_RUNNING == 1 )); then
                systemctl start "$WEB_SERVICE" || warn 'Previous web service failed to restart.'
            fi
            ROLLED_BACK=1
            warn "Rollback attempted. Review journalctl -u ${SERVICE_NAME} and ${LOG_FILE}."
        fi
    fi
    [[ -z "$STAGE" || ! -e "$STAGE" ]] || rm -rf -- "$STAGE"
    # Keep the previous source and DB dump for manual recovery on successful upgrades.
    exit "$rc"
}
trap cleanup_and_rollback EXIT

require_root() {
    (( EUID == 0 )) || fail 'Run as root: sudo bash install.sh'
    [[ -f /etc/os-release ]] || fail 'Unsupported host: missing /etc/os-release'
    # shellcheck disable=SC1091
    . /etc/os-release
    case " ${ID:-} ${ID_LIKE:-} " in
        *ubuntu*|*debian*) ;;
        *) fail 'Installer supports Debian/Ubuntu only.' ;;
    esac
    command -v systemctl >/dev/null || fail 'systemd is required.'
    command -v apt-get >/dev/null || fail 'apt-get is required.'
    command -v tar >/dev/null || fail 'tar is required.'
    [[ -f "$SOURCE_DIR/bot.py" && -f "$SOURCE_DIR/requirements.txt" && -f "$SOURCE_DIR/settings.py" ]] ||
        fail 'Source files are missing. Extract the FULL Sonar Radar ZIP first.'
    mkdir -p "$BACKUP_ROOT" "$LOG_DIR"
    touch "$LOG_FILE"
    chmod 600 "$LOG_FILE"
    if [[ -L "$DB_ENV_FILE" ]]; then fail 'Refusing symlinked database environment file.'; fi
}

check_python() {
    python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit('Python >= 3.10 is required')
PY
}

preflight() {
    require_root
    info 'Preflight checks'
    check_python
    bash -n "$SOURCE_DIR/install.sh" "$SOURCE_DIR/install_web_panel.sh"
    python3 - "$SOURCE_DIR" <<'PY'
import json, pathlib, sys
base = pathlib.Path(sys.argv[1])
for name in ('sonar_config.json','requirements.txt','bot.py','pro_store.py','pro_portal.py'):
    if not (base/name).is_file(): raise SystemExit(f'Required file missing: {name}')
with (base/'sonar_config.json').open(encoding='utf-8') as f: json.load(f)
print('Source files and JSON structure: OK')
PY
    info 'Preflight passed (does not verify network or Telegram).'
}

backup_db_if_present() {
    if runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -qx 1; then
        local dump="$BACKUP_ROOT/${DB_NAME}-$(date -u +%Y%m%dT%H%M%SZ)-$$.dump"
        info "Creating pre-upgrade PostgreSQL dump: $dump"
        # The dump is written by root via stdout redirection, ensuring 0600 permissions.
        runuser -u postgres -- pg_dump -Fc -d "$DB_NAME" > "$dump"
        [[ -s "$dump" ]] || fail 'PostgreSQL dump is empty. Refusing upgrade.'
        chmod 600 "$dump"
        info 'Database backup complete. Automatic database rollback is intentionally disabled.'
    fi
}

ensure_database() {
    info 'Preparing PostgreSQL'
    systemctl enable --now postgresql >/dev/null
    if [[ -f "$DB_ENV_FILE" ]]; then
        local pass_line
        pass_line="$(grep -m1 '^SONAR_DB_PASSWORD=' "$DB_ENV_FILE" || true)"
        if [[ -n "$pass_line" ]]; then
            DB_PASS="${pass_line#SONAR_DB_PASSWORD=}"
        else
            DB_PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
            printf '\nSONAR_DB_PASSWORD=%s\n' "$DB_PASS" >> "$DB_ENV_FILE"
        fi
    else
        DB_PASS="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
        printf 'SONAR_DB_PASSWORD=%s\n' "$DB_PASS" > "$DB_ENV_FILE"
    fi
    chmod 600 "$DB_ENV_FILE"
    chown root:root "$DB_ENV_FILE"
    [[ "$DB_PASS" =~ ^[A-Za-z0-9_-]{20,}$ ]] ||
        fail 'Existing SONAR_DB_PASSWORD is not in the supported shell-safe format. Correct it securely before installing.'

    if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" | grep -qx 1; then
        runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "CREATE ROLE ${DB_USER} LOGIN" >/dev/null
    fi
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "ALTER ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}'" >/dev/null
    if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -qx 1; then
        runuser -u postgres -- createdb -O "$DB_USER" "$DB_NAME"
    fi
    runuser -u postgres -- psql -v ON_ERROR_STOP=1 -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER}" >/dev/null
}

read_old_config_to_stage() {
    if [[ -f "$INSTALL_DIR/sonar_config.json" ]]; then
        cp -p -- "$INSTALL_DIR/sonar_config.json" "$STAGE/sonar_config.json"
    fi
    if [[ -f "$INSTALL_DIR/secret.key" ]]; then
        cp -p -- "$INSTALL_DIR/secret.key" "$STAGE/secret.key"
    fi
    # Existing custom web URL lives in DB_ENV_FILE and is preserved separately.
    # Other unknown runtime files outside the shipped package are kept in PREVIOUS.
}

set_credentials() {
    local location="$1" token admin
    if [[ -s "$location/sonar_config.json" ]] && python3 - "$location/sonar_config.json" <<'PY'
import json,sys
try:
 d=json.load(open(sys.argv[1],encoding='utf-8'))
 assert isinstance(d.get('bot_token'),str) and d['bot_token'].strip()
 assert str(d.get('admin_id','')).isdigit() and int(d['admin_id'])>0
except Exception: raise SystemExit(1)
PY
    then
        info 'Existing bot token and admin ID preserved.'
        return 0
    fi

    info 'Please enter Telegram credentials for a new installation.'
    read -r -s -p 'Bot token (hidden): ' token; printf '\n'
    read -r -p 'Admin numeric Telegram ID: ' admin
    [[ -n "$token" && "$admin" =~ ^[0-9]+$ && "$admin" != "0" ]] || fail 'Invalid credentials.'
    SONAR_INPUT_TOKEN="$token" SONAR_INPUT_ADMIN="$admin" python3 - "$location/sonar_config.json" <<'PY'
import json,os,sys
p=sys.argv[1]
try:
 with open(p,encoding='utf-8') as f: d=json.load(f)
except FileNotFoundError: d={}
d['bot_token']=os.environ['SONAR_INPUT_TOKEN']
d['admin_id']=os.environ['SONAR_INPUT_ADMIN']
with open(p,'w',encoding='utf-8') as f: json.dump(d,f,ensure_ascii=False,indent=2)
PY
    unset token
    chmod 600 "$location/sonar_config.json"
}

install_requirements() {
    info 'Updating package index and installing OS dependencies'
    DEBIAN_FRONTEND=noninteractive apt-get update -y >> "$LOG_FILE" 2>&1 || fail "apt-get update failed; see $LOG_FILE"
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
        python3 python3-pip python3-venv git curl bc tar \
        build-essential libssl-dev libffi-dev python3-dev \
        postgresql postgresql-contrib libpq-dev \
        libpango-1.0-0 libpangoft2-1.0-0 fonts-dejavu-core \
        >> "$LOG_FILE" 2>&1 || fail "OS dependency install failed; see $LOG_FILE"
    check_python
    info 'Building a clean Python virtual environment BEFORE stopping the existing bot'
    python3 -m venv "$STAGE/venv"
    "$STAGE/venv/bin/python" -m pip install --upgrade pip setuptools wheel >> "$LOG_FILE" 2>&1 ||
        fail "pip bootstrap failed; see $LOG_FILE"
    "$STAGE/venv/bin/python" -m pip install -r "$STAGE/requirements.txt" >> "$LOG_FILE" 2>&1 ||
        fail "Python dependency install failed; see $LOG_FILE"
    "$STAGE/venv/bin/python" -m compileall -q "$STAGE" || fail 'Python syntax validation failed.'
}

# A venv created under STAGE contains absolute shebangs in pip/uvicorn scripts.
# Rewrite them to the final path BEFORE moving the staged release.
relocate_venv_entrypoints() {
    info 'Fixing virtualenv script paths for the final installation directory'
    python3 - "$STAGE" "$INSTALL_DIR" <<'PYRELOCATE'
from pathlib import Path
import sys
old=Path(sys.argv[1]); new=Path(sys.argv[2]); bindir=old/'venv'/'bin'
count=0
for file in bindir.iterdir():
    if file.is_symlink() or not file.is_file():
        continue
    content=file.read_bytes()
    if content.startswith(b'#!') and str(old).encode() in content.split(b'\n',1)[0]:
        content=content.replace(str(old).encode(),str(new).encode(),1)
        file.write_bytes(content)
        count+=1
    elif file.name.startswith('activate') and str(old).encode() in content:
        file.write_bytes(content.replace(str(old).encode(),str(new).encode()))
print(f'Updated {count} virtualenv console-script shebangs')
for name in ('pip','uvicorn'):
    script=bindir/name
    if script.is_file():
        with script.open('rb') as f: first=f.readline()
        if str(old).encode() in first:
            raise SystemExit(f'Broken stage shebang remains in {name}')
PYRELOCATE
}

write_service() {
    cat > "$UNIT_FILE" <<EOF
[Unit]
Description=Sonar Radar Pro 5 Bot
Wants=network-online.target
After=network-online.target postgresql.service
[Service]
Type=simple
User=sonar-bot
Group=sonar-bot
EnvironmentFile=$DB_ENV_FILE
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/bot.py
NoNewPrivileges=true
PrivateTmp=true
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
    chmod 644 "$UNIT_FILE"
}

install_or_update() {
    local mode="$1" stamp
    preflight
    if [[ "$mode" == "install" && -e "$INSTALL_DIR" ]]; then
        fail "Installation exists at $INSTALL_DIR. Use Update (option 2), not Install."
    fi
    if [[ "$mode" == "update" && ! -d "$INSTALL_DIR" ]]; then
        fail 'No existing installation found. Use Install (option 1).'
    fi
    if [[ "$mode" == "update" && "$SOURCE_DIR" == "$INSTALL_DIR" ]]; then
        fail 'Unzip the NEW release into a separate folder before updating.'
    fi

    stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
    STAGE="$(mktemp -d /opt/.sonar-stage.XXXXXXXX)"
    info "Preparing new release at $STAGE"
    tar -C "$SOURCE_DIR" --exclude='./venv' --exclude='./.git' \
        --exclude='./__pycache__' --exclude='./.pytest_cache' --exclude='./logs' \
        -cf - . | tar -C "$STAGE" -xf -
    if [[ "$mode" == "update" ]]; then
        read_old_config_to_stage
    fi
    set_credentials "$STAGE"
    install_requirements
    relocate_venv_entrypoints
    # Postgres is the only mutable external component. Prepare a DB dump BEFORE modifying it.
    systemctl enable --now postgresql >/dev/null
    backup_db_if_present
    ensure_database

    info 'Preparing dedicated service account'
    id -u sonar-bot >/dev/null 2>&1 || useradd --system --home-dir "$INSTALL_DIR" --shell /usr/sbin/nologin sonar-bot
    mkdir -p "$LOG_DIR"
    chown -R sonar-bot:sonar-bot "$STAGE" "$LOG_DIR"
    chmod 600 "$STAGE/sonar_config.json"
    [[ ! -f "$STAGE/secret.key" ]] || chmod 600 "$STAGE/secret.key"
    chmod 755 "$STAGE" "$STAGE/install.sh"

    if [[ -d "$INSTALL_DIR" ]]; then PREVIOUS_PRESENT=1; else PREVIOUS_PRESENT=0; fi
    if systemctl is-active --quiet "$SERVICE_NAME"; then PREV_BOT_RUNNING=1; fi
    if systemctl is-active --quiet "$WEB_SERVICE"; then PREV_WEB_RUNNING=1; fi
    if [[ -f "$UNIT_FILE" ]]; then
        UNIT_COPY="$BACKUP_ROOT/${SERVICE_NAME}.${stamp}.service"
        cp -p -- "$UNIT_FILE" "$UNIT_COPY"
    fi

    info 'Switching releases; previous service will stop briefly'
    systemctl stop "$SERVICE_NAME" >/dev/null 2>&1 || true
    if (( PREV_WEB_RUNNING == 1 )); then systemctl stop "$WEB_SERVICE"; fi
    DEPLOY_STARTED=1
    if (( PREVIOUS_PRESENT == 1 )); then
        PREVIOUS="/opt/.sonar-previous-${stamp}"
        mv -- "$INSTALL_DIR" "$PREVIOUS"
    fi
    mv -- "$STAGE" "$INSTALL_DIR"
    STAGE=""
    write_service
    systemctl daemon-reload
    systemctl enable "$SERVICE_NAME" >/dev/null
    systemctl reset-failed "$SERVICE_NAME" >/dev/null 2>&1 || true
    systemctl restart "$SERVICE_NAME"
    sleep 12
    systemctl is-active --quiet "$SERVICE_NAME" || fail 'Bot did not stay active after launch.'
    local restarts
    restarts="$(systemctl show "$SERVICE_NAME" --value -p NRestarts 2>/dev/null || echo 0)"
    if [[ "$restarts" =~ ^[0-9]+$ ]] && (( restarts > 0 )); then
        fail "Bot restarted ${restarts} time(s) during startup; investigate journal logs."
    fi
    # Existing web service may need to reload modules/assets after a bot upgrade.
    if (( PREV_WEB_RUNNING == 1 )); then
        systemctl restart "$WEB_SERVICE"
        sleep 2
        systemctl is-active --quiet "$WEB_SERVICE" || fail 'Existing Mini App service failed after upgrade.'
    fi
    DEPLOY_STARTED=0
    info 'Bot service appears active. Verify Telegram messages and all features manually.'
    [[ -z "$PREVIOUS" ]] || info "Previous release kept at: $PREVIOUS"
    info "Installer log: $LOG_FILE"
    info "Check: systemctl status $SERVICE_NAME && journalctl -u $SERVICE_NAME -n 80 --no-pager"
    info 'IMPORTANT: this test is NOT an end-to-end Telegram/agent/database restore test.'
}

change_credentials() {
    require_root
    [[ -d "$INSTALL_DIR" ]] || fail 'Bot is not installed.'
    local token admin
    read -r -s -p 'New Bot token (hidden): ' token; printf '\n'
    read -r -p 'New admin numeric Telegram ID: ' admin
    [[ -n "$token" && "$admin" =~ ^[0-9]+$ && "$admin" != '0' ]] || fail 'Invalid credentials.'
    SONAR_INPUT_TOKEN="$token" SONAR_INPUT_ADMIN="$admin" python3 - "$INSTALL_DIR/sonar_config.json" <<'PY'
import json,os,sys,tempfile
p=sys.argv[1]
with open(p,encoding='utf-8') as f: data=json.load(f)
data.update(bot_token=os.environ['SONAR_INPUT_TOKEN'],admin_id=os.environ['SONAR_INPUT_ADMIN'])
with tempfile.NamedTemporaryFile('w',encoding='utf-8',dir=os.path.dirname(p),delete=False) as f:
    json.dump(data,f,ensure_ascii=False,indent=2)
    temp=f.name
os.chmod(temp,0o600)
os.replace(temp,p)
PY
    chown sonar-bot:sonar-bot "$INSTALL_DIR/sonar_config.json"
    systemctl restart "$SERVICE_NAME"
    info 'Credentials updated without resetting other settings.'
}

uninstall() {
    require_root
    [[ -d "$INSTALL_DIR" ]] || fail 'No installed bot found.'
    warn 'Uninstall removes installed application files only. Database, backup, DB env and system packages remain.'
    local confirmation
    read -r -p 'Type UNINSTALL to remove bot and web service: ' confirmation
    [[ "$confirmation" == 'UNINSTALL' ]] || { warn 'Cancelled.'; return 0; }
    systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1 || true
    systemctl disable --now "$WEB_SERVICE" >/dev/null 2>&1 || true
    rm -f -- "$UNIT_FILE" "/etc/systemd/system/${WEB_SERVICE}.service"
    systemctl daemon-reload
    local archive="$BACKUP_ROOT/uninstalled-$(date -u +%Y%m%dT%H%M%SZ)-$$"
    mv -- "$INSTALL_DIR" "$archive"
    info "Bot files archived at $archive (not destroyed)."
}

menu() {
    require_root
    while true; do
        printf '\n===== SONAR RADAR PRO 5.0 | Safe Installer =====\n'
        printf ' 1) New install\n 2) Upgrade from this extracted ZIP\n 3) Restart bot\n 4) Bot logs\n 5) Change token/admin\n 6) Uninstall (archive files)\n 7) Exit\n 8) Preflight only\n'
        local option
        read -r -p 'Select [1-8]: ' option || break
        case "$option" in
            1) install_or_update install ;;
            2) install_or_update update ;;
            3) systemctl restart "$SERVICE_NAME" && info 'Restart requested.' ;;
            4) journalctl -u "$SERVICE_NAME" -n 100 --no-pager ;;
            5) change_credentials ;;
            6) uninstall ;;
            7) break ;;
            8) preflight ;;
            *) warn 'Unknown choice' ;;
        esac
    done
}

case "${1:-}" in
    --check) preflight ;;
    --install) install_or_update install ;;
    --update) install_or_update update ;;
    --help|-h) printf 'Usage: sudo bash install.sh [--check|--install|--update]\n';;
    '') menu ;;
    *) fail 'Unknown argument; try --help' ;;
esac
