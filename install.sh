#!/bin/bash

# ==============================================================================
# 🦇 SONAR RADAR ULTRA MONITOR 1.5 - AUTO CONFIG MANAGER
# ==============================================================================

# --- Configuration ---
INSTALL_DIR="/opt/radar-sonar"
SERVICE_NAME="sonar-bot"
REPO_URL="https://github.com/Amirtn9/radar-sonar.git"
RAW_URL="https://raw.githubusercontent.com/Amirtn9/radar-sonar/main"
DB_FILE="sonar_ultra_pro.db"
KEY_FILE="secret.key"
CONFIG_FILE="sonar_config.json"
SETTINGS_FILE="settings.py"

# --- Colors (Neon Theme) ---
RESET='\033[0m'
BOLD='\033[1m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
PURPLE='\033[0;35m'

# --- Utils ---
function print_title() {
    clear
    echo -e "${PURPLE}${BOLD}"
    echo "      /\\                 /\\    "
    echo "     / \\'._   (\_/)   _.'/ \\   "
    echo "    /_.''._'--('.')--'_.''._\  "
    echo "    | \_ / \`  ~ ~  \`/ \_ / |  "
    echo "     \_/  \`/       \`'  \_/   "
    echo "           \`           \`      "
    echo -e "${RESET}"
    echo -e "   ${CYAN}${BOLD}🦇 SONAR RADAR ULTRA MONITOR 1.5${RESET}"
    echo -e "   ${BLUE}──────────────────────────────────${RESET}"
    echo ""
}

function print_success() { echo -e "${GREEN}${BOLD}✅ $1${RESET}"; }
function print_error() { echo -e "${RED}${BOLD}❌ $1${RESET}"; }
function print_info() { echo -e "${YELLOW}➤ $1...${RESET}"; }
function wait_enter() { echo ""; read -p "Press [Enter] to continue..." dummy; }

# --- Helper: Read JSON with Python ---
function read_json_val() {
    local file=$1
    local key=$2
    if [ -f "$file" ]; then
        python3 -c "import json; print(json.load(open('$file')).get('$key', ''))" 2>/dev/null
    else
        echo ""
    fi
}

# --- Helper: Update Settings.py ---
function update_settings_py() {
    local admin_id=$1
    local settings_path="$INSTALL_DIR/$SETTINGS_FILE"
    
    if [ -f "$settings_path" ]; then
        sed -i "s/^SUPER_ADMIN_ID = .*/SUPER_ADMIN_ID = $admin_id/" "$settings_path"
        print_success "Updated SUPER_ADMIN_ID in $SETTINGS_FILE"
    else
        print_error "$SETTINGS_FILE not found, could not update admin ID in python file."
    fi
}

# --- Loading Animations ---
function show_loading() {
    local pid=$1
    local text=$2
    local spinstr='|/-\'
    while [ "$(ps a | awk '{print $1}' | grep $pid)" ]; do
        local temp=${spinstr#?}
        printf " [%c]  %s" "$spinstr" "$text"
        local spinstr=$temp${spinstr%"$temp"}
        sleep 0.1
        printf "\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b\b"
    done
    printf "    \b\b\b\b"
}

function progress_bar() {
    local duration=$1
    local width=30
    local step_time=$(echo "$duration / $width" | bc -l)
    echo -ne "\n"
    for ((i=0; i<=$width; i++)); do
        local percent=$((i * 100 / width))
        local filled=$(printf "%0.s█" $(seq 1 $i))
        local unfilled=$(printf "%0.s░" $(seq 1 $((width - i))))
        if [ $percent -lt 30 ]; then color=$RED; elif [ $percent -lt 70 ]; then color=$YELLOW; else color=$GREEN; fi
        printf "\r ${color}[${filled}${unfilled}]${RESET} ${percent}%%  Loading..."
        sleep $step_time
    done
    echo -ne "\n"
}

# --- Root Check ---
if [ "$EUID" -ne 0 ]; then echo -e "${RED}❌ Please run as root.${RESET}"; exit 1; fi

# ==============================================================================
# 🔧 DATABASE CONFIGURATION
# ==============================================================================
function setup_postgres() {
    print_info "Configuring PostgreSQL Database..."
    
    # 1. Start Postgres Service
    systemctl start postgresql
    systemctl enable postgresql
    
    # 2. Create User and Database (Match settings.py)
    DB_NAME="sonar_ultra_pro"
    DB_USER="sonar_user"
    DB_PASS="SonarPassword2025"
    
    # Run commands as postgres user
    sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';" 2>/dev/null || true
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;" 2>/dev/null || true
    sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;" 2>/dev/null || true
    
    print_success "PostgreSQL configured successfully."
}

# ==============================================================================
# 🔧 CORE INSTALLATION LOGIC
# ==============================================================================
function install_process() {
    local KEEP_CONFIG=$1 # true = update mode, false = fresh install
    
    print_title
    echo -e "${BOLD}🚀 STARTING OPERATION...${RESET}\n"

    # 1. Stop Service
    if systemctl is-active --quiet $SERVICE_NAME; then
        print_info "Stopping active service"
        systemctl stop $SERVICE_NAME
    fi

    # 2. Backup Critical Data (DB & Config)
    local OLD_TOKEN=""
    local OLD_ADMIN=""
    
    print_info "Backing up Configuration"
    if [ -f "$INSTALL_DIR/$KEY_FILE" ]; then cp "$INSTALL_DIR/$KEY_FILE" /tmp/sonar_key.bak; fi
    
    if [ "$KEEP_CONFIG" = true ] && [ -f "$INSTALL_DIR/$CONFIG_FILE" ]; then
        print_info "Reading configuration from $CONFIG_FILE"
        OLD_TOKEN=$(read_json_val "$INSTALL_DIR/$CONFIG_FILE" "bot_token")
        OLD_ADMIN=$(read_json_val "$INSTALL_DIR/$CONFIG_FILE" "admin_id")
    fi

    # 3. Clean Slate
    print_info "Wiping directory for installation"
    rm -rf "$INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"

    # 4. System Dependencies
    print_info "Updating System Packages"
    apt-get update -y > /dev/null 2>&1 &
    show_loading $! "Apt Update..."
    
    apt-get install -y python3 python3-pip python3-venv git curl bc build-essential libssl-dev libffi-dev python3-dev postgresql postgresql-contrib libpq-dev > /dev/null 2>&1 &
    show_loading $! "Installing OS Deps..."

    # Configure Database right after installing packages
    setup_postgres

    # 5. Download Source
    print_info "Cloning Source Code"
    if ! git clone "$REPO_URL" "$INSTALL_DIR" > /dev/null 2>&1; then
        print_info "Git clone failed, downloading files manually..."
        # Updated file list to include all required components
        local FILES=("bot.py" "core.py" "cronjobs.py" "database.py" "keyboard.py" "settings.py" "monitor_agent.py" "admin_panel.py" "server_stats.py" "scoring.py" "tunnel_logic.py" "requirements.txt" "alerts.py" "logger_setup.py" "topics.py")
        
        for file in "${FILES[@]}"; do
             curl -s -o "$INSTALL_DIR/$file" "$RAW_URL/$file"
        done
    fi

    if [ -f "$INSTALL_DIR/monitor_agent.py" ]; then
        chmod +x "$INSTALL_DIR/monitor_agent.py"
    fi

    # 6. Restore Data
    print_info "Restoring Keys"
    if [ -f "/tmp/sonar_key.bak" ]; then mv /tmp/sonar_key.bak "$INSTALL_DIR/$KEY_FILE"; fi

    # 7. Setup Python Environment
    print_info "Creating Virtual Environment"
    python3 -m venv "$INSTALL_DIR/venv"
    source "$INSTALL_DIR/venv/bin/activate"

    print_info "Installing Python Libraries"
    pip install --upgrade pip setuptools wheel > /dev/null 2>&1
    pip install "python-telegram-bot[job-queue]" paramiko cryptography jdatetime matplotlib requests psycopg2-binary > /dev/null 2>&1 &
    show_loading $! "Pip Install..."

    # 8. Setup Service
    cat <<EOF > /etc/systemd/system/$SERVICE_NAME.service
[Unit]
Description=Sonar Radar Ultra Pro Bot
After=network.target postgresql.service

[Service]
Type=simple
User=root
WorkingDirectory=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    systemctl enable $SERVICE_NAME > /dev/null 2>&1

    # 9. Handle Configuration
    if [ "$KEEP_CONFIG" = true ] && [ -n "$OLD_TOKEN" ]; then
        print_info "Restoring Config (Token & Admin ID)"
        echo "{\"bot_token\": \"$OLD_TOKEN\", \"admin_id\": \"$OLD_ADMIN\"}" > "$INSTALL_DIR/$CONFIG_FILE"
        update_settings_py "$OLD_ADMIN"
    else
        configure_token_interactive
    fi

    # 10. Launch
    print_info "Starting Bot Service"
    systemctl restart $SERVICE_NAME
    
    progress_bar 5

    if systemctl is-active --quiet $SERVICE_NAME; then
        print_success "Bot is ONLINE and Ready! 🦇"
    else
        print_error "Bot failed to start. Check logs (journalctl -u $SERVICE_NAME -f)."
    fi
    wait_enter
}

function configure_token_interactive() {
    print_title
    echo -e "${BOLD}⚙️ SETUP CONFIGURATION${RESET}\n"
    echo -e "${CYAN}🤖 Enter Telegram Bot Token:${RESET}"
    read -p ">> " TOKEN_INPUT
    echo -e "\n${CYAN}👤 Enter Admin Numeric ID:${RESET}"
    read -p ">> " ADMIN_INPUT

    if [ -n "$TOKEN_INPUT" ] && [ -n "$ADMIN_INPUT" ]; then
        echo "{\"bot_token\": \"$TOKEN_INPUT\", \"admin_id\": \"$ADMIN_INPUT\"}" > "$INSTALL_DIR/$CONFIG_FILE"
        update_settings_py "$ADMIN_INPUT"
        print_success "Configuration Saved & Applied!"
    else
        print_error "Invalid input. Config failed."
    fi
}

function manual_config_menu() {
    if [ ! -d "$INSTALL_DIR" ]; then print_error "Bot not installed."; wait_enter; return; fi
    configure_token_interactive
    systemctl restart $SERVICE_NAME
    print_success "Bot Restarted with new config."
    wait_enter
}

function full_restart() {
    print_title
    echo -e "${BOLD}♻️ FULL RESTART${RESET}\n"
    systemctl stop $SERVICE_NAME
    print_info "Killing zombie processes"
    pkill -f "$INSTALL_DIR/bot.py" > /dev/null 2>&1
    sleep 1
    systemctl start $SERVICE_NAME
    progress_bar 5
    if systemctl is-active --quiet $SERVICE_NAME; then
        print_success "Restarted Successfully."
    else
        print_error "Failed."
    fi
    wait_enter
}

function view_logs() {
    clear
    echo -e "${GREEN}${BOLD}📜 LIVE LOGS (Ctrl+C to exit)${RESET}"
    journalctl -u $SERVICE_NAME -f -n 50
}

function uninstall_bot() {
    print_title
    echo -e "${RED}${BOLD}🗑️ UNINSTALL${RESET}\n"
    read -p "Delete EVERYTHING (DB, Logs, Config)? (y/n): " confirm
    if [[ "$confirm" == "y" || "$confirm" == "Y" ]]; then
        systemctl stop $SERVICE_NAME
        systemctl disable $SERVICE_NAME > /dev/null 2>&1
        rm -f /etc/systemd/system/$SERVICE_NAME.service
        systemctl daemon-reload
        rm -rf "$INSTALL_DIR"
        print_success "Deleted."
    fi
    wait_enter
}

# --- Main Menu Loop ---
while true; do
    print_title
    echo -e " ${GREEN}1)${RESET} 🚀 Install Bot "
    echo -e " ${GREEN}2)${RESET} 🔄 Update Bot "
    echo -e " ${GREEN}3)${RESET} ♻️  Restart Bot"
    echo -e " ${GREEN}4)${RESET} 📜 View Logs"
    echo -e " ${GREEN}5)${RESET} ⚙️  Change Token/Admin"
    echo -e " ${GREEN}6)${RESET} 🗑️  Uninstall"
    echo -e " ${RED}7) ❌ Exit${RESET}"
    echo ""
    read -p " Select [1-7]: " OPTION
    case $OPTION in
        1) install_process false ;; 
        2) install_process true  ;; 
        3) full_restart ;;
        4) view_logs ;;
        5) manual_config_menu ;;
        6) uninstall_bot ;;
        7) clear; exit ;;
        8) setup_postgres ;;
        *) echo "Invalid Option" ;;
    esac
done