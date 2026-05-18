#!/bin/bash
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# ForcedFocus Installer
# Deploys all components to system paths and loads the LaunchDaemon.
# Must be run as root: sudo bash install.sh
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

set -euo pipefail

# ── Visual Configuration ──────────────────────────────────────────────────────
RED='\033[38;5;196m'
GREEN='\033[38;5;82m'
YELLOW='\033[38;5;226m'
BLUE='\033[38;5;33m'
MAGENTA='\033[38;5;165m'
CYAN='\033[38;5;51m'
WHITE='\033[38;5;255m'
BOLD='\033[1m'
DIM='\033[2m'
NC='\033[0m'

# Utility for beautiful step headers
print_step() {
    echo -e "${BLUE}${BOLD}➤${NC} ${WHITE}${BOLD}$1${NC} ${DIM}...${NC}"
}

print_success() {
    echo -e "${GREEN}${BOLD}  ✓${NC} ${DIM}$1${NC}"
}

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DAEMON_SRC="${SCRIPT_DIR}/forcefocus_daemon.py"
CLI_SRC="${SCRIPT_DIR}/forcefocus_cli.py"
WEB_SRC="${SCRIPT_DIR}/forcefocus_web.py"
PLIST_SRC="${SCRIPT_DIR}/com.forcefocus.daemon.plist"
WEB_DIR_SRC="${SCRIPT_DIR}/web"

DAEMON_DST="/usr/local/bin/forcefocus_daemon.py"
CLI_DST="/usr/local/bin/forcefocus"
WEB_DST="/usr/local/bin/forcefocus_web.py"
PLIST_DST="/Library/LaunchDaemons/com.forcefocus.daemon.plist"
CONFIG_DIR="/etc/forcefocus"
WEB_DIR_DST="/usr/local/share/forcefocus/web"
PLIST_LABEL="com.forcefocus.daemon"

# ── Header ──────────────────────────────────────────────────────────────────
clear
echo -e "${MAGENTA}${BOLD}┌─────────────────────────────────────────────────────────────┐${NC}"
echo -e "${MAGENTA}${BOLD}│${NC}  ${WHITE}${BOLD}⚡ ForcedFocus Installer${NC}                               ${MAGENTA}${BOLD}│${NC}"
echo -e "${MAGENTA}${BOLD}│${NC}  ${DIM}Deploying Absolute Productivity Infrastructure${NC}          ${MAGENTA}${BOLD}│${NC}"
echo -e "${MAGENTA}${BOLD}└─────────────────────────────────────────────────────────────┘${NC}"
echo ""

if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}${BOLD} ✗ Permission Denied${NC}"
    echo -e "   ${DIM}This installer requires root privileges to configure the firewall.${NC}"
    echo -e "   ${BOLD}Usage:${NC} sudo bash install.sh"
    echo ""
    exit 1
fi

# Verify source files
for f in "$DAEMON_SRC" "$CLI_SRC" "$WEB_SRC" "$PLIST_SRC"; do
    if [[ ! -f "$f" ]]; then
        echo -e "${RED}${BOLD} ✗ Missing Source${NC}: ${f}"
        exit 1
    fi
done

# Check for Python 3
PYTHON_BIN=""
for candidate in /usr/local/bin/python3 /usr/bin/python3; do
    if "$candidate" --version &>/dev/null 2>&1; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [[ -z "$PYTHON_BIN" ]]; then
    echo -e "${RED}${BOLD} ✗ Runtime Not Found${NC}"
    echo "   Python 3 is required. Please install it first."
    exit 1
fi

PYTHON_VER=$($PYTHON_BIN --version 2>&1)
echo -e "  ${DIM}Runtime: ${PYTHON_VER}${NC}"
echo ""

# ── 1. Preparation ────────────────────────────────────────────────────────────
print_step "Synchronizing existing services"
if launchctl list 2>/dev/null | grep -q "$PLIST_LABEL"; then
    launchctl unload "$PLIST_DST" 2>/dev/null || true
    sleep 1
fi
print_success "Daemon state cleared"

print_step "Initializing secure directory structure"
mkdir -p "$CONFIG_DIR"
chmod 700 "$CONFIG_DIR"
chown root:wheel "$CONFIG_DIR"
REAL_USER="${SUDO_USER:-$USER}"
echo "$REAL_USER" > "$CONFIG_DIR/user"
chmod 644 "$CONFIG_DIR/user"
print_success "Created ${CONFIG_DIR}"

# ── 2. Component Installation ─────────────────────────────────────────────────
print_step "Deploying core components"

cp "$DAEMON_SRC" "$DAEMON_DST"
chmod 700 "$DAEMON_DST"
chown root:wheel "$DAEMON_DST"

cp "$CLI_SRC" "$CLI_DST"
chmod 755 "$CLI_DST"
chown root:wheel "$CLI_DST"

cp "$WEB_SRC" "$WEB_DST"
chmod 755 "$WEB_DST"
chown root:wheel "$WEB_DST"

mkdir -p "$WEB_DIR_DST"
cp -R "$WEB_DIR_SRC/"* "$WEB_DIR_DST/"
# Ensure shared directory is included if it hasn't been synced locally yet
if [[ -d "${SCRIPT_DIR}/shared" ]]; then
    cp -R "${SCRIPT_DIR}/shared" "$WEB_DIR_DST/"
fi
chmod -R 755 "$WEB_DIR_DST"

cp "$PLIST_SRC" "$PLIST_DST"
sed -i '' "s|/usr/local/bin/python3|${PYTHON_BIN}|g" "$PLIST_DST"
chmod 644 "$PLIST_DST"
chown root:wheel "$PLIST_DST"
print_success "Binary and service definitions installed"

print_step "Compiling and deploying Menu Bar Application"
if [[ -f "${SCRIPT_DIR}/build_menubar.sh" ]]; then
    # Build the menubar app
    (cd "${SCRIPT_DIR}" && bash build_menubar.sh) > /dev/null
    
    # Deploy to Applications
    APP_DST="/Applications/ForcedFocusBar.app"
    rm -rf "$APP_DST"
    cp -R "${SCRIPT_DIR}/ForcedFocusBar.app" "$APP_DST"
    
    # Set correct permissions
    chown -R "$REAL_USER":staff "$APP_DST"
    chmod -R 755 "$APP_DST"
    print_success "Menu Bar App installed to ${APP_DST}"
else
    echo -e "${YELLOW}  ⚠ build_menubar.sh not found, skipping menubar app deployment.${NC}"
fi

# ── 3. Validation ─────────────────────────────────────────────────────────────
print_step "Verifying system manifest"
if ! plutil -lint "$PLIST_DST" &>/dev/null; then
    echo -e "${RED}✗ Plist validation failed!${NC}"
    plutil -lint "$PLIST_DST"
    exit 1
fi
print_success "Integrity checks passed"

# ── 4. Security Configuration ──────────────────────────────────────────────────
KS_HASH_FILE="${CONFIG_DIR}/ks_hash"
if [[ ! -f "$KS_HASH_FILE" ]]; then
    echo ""
    echo -e "  ${WHITE}${BOLD}Set Security Key${NC}"
    echo -e "  ${DIM}Required to unlock blocking sessions.${NC}"
    echo ""
    $PYTHON_BIN "$DAEMON_DST" set-key || $PYTHON_BIN "$CLI_DST" set-key
    if [[ ! -f "$KS_HASH_FILE" ]]; then
        echo -e "${RED}✗ Key not set. Aborting.${NC}"
        exit 1
    fi
else
    print_success "Security key hash verified"
fi

print_step "Creating kernel-level backup"
BACKUP="${CONFIG_DIR}/hosts.backup.$(date +%Y%m%d_%H%M%S)"
cp /private/etc/hosts "$BACKUP"
chmod 600 "$BACKUP"
print_success "Snapshot saved to ${BACKUP}"

print_step "Configuring PF firewall engine"
PF_CONF="/etc/pf.conf"
if [[ -f "$PF_CONF" ]]; then
    if ! grep -q "anchor \"forcefocus\"" "$PF_CONF"; then
        echo "" >> "$PF_CONF"
        echo "# ForcedFocus transient rules" >> "$PF_CONF"
        echo "anchor \"forcefocus\"" >> "$PF_CONF"
        pfctl -f "$PF_CONF" 2>/dev/null || true
    fi
fi
print_success "Kernel anchor synchronized"

print_step "Installing log rotation configuration"
NEWSYSLOG_SRC="${SCRIPT_DIR}/forcefocus.newsyslog.conf"
NEWSYSLOG_DST="/etc/newsyslog.d/forcefocus.conf"
if [[ -f "$NEWSYSLOG_SRC" ]]; then
    cp "$NEWSYSLOG_SRC" "$NEWSYSLOG_DST"
    chmod 644 "$NEWSYSLOG_DST"
    print_success "Log rotation configured at ${NEWSYSLOG_DST}"
else
    echo -e "${YELLOW}  ⚠ newsyslog config not found in source tree, skipping.${NC}"
fi

# ── 5. Deployment ─────────────────────────────────────────────────────────────
print_step "Launching background sentinel"
launchctl load -w "$PLIST_DST" 2>/dev/null || true
sleep 1
if launchctl list 2>/dev/null | grep -q "$PLIST_LABEL"; then
    print_success "Daemon active and monitoring"
else
    echo -e "${RED}✗ Initialization failed.${NC}"
    exit 1
fi

# ── 6. Finalization ───────────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}┌─────────────────────────────────────────────────────────────┐${NC}"
echo -e "${GREEN}${BOLD}│${NC}  ${WHITE}${BOLD}✓ ForcedFocus Deployment Complete${NC}                        ${GREEN}${BOLD}│${NC}"
echo -e "${GREEN}${BOLD}└─────────────────────────────────────────────────────────────┘${NC}"
echo ""
echo -e "  ${BOLD}${WHITE}Quick Access:${NC}"
echo -e "    ${BLUE}Dashboard:${NC} http://localhost:7070"
echo -e "    ${BLUE}Log Feed:${NC}  tail -f /var/log/forcefocus.log"
echo ""
echo -e "  ${BOLD}${WHITE}Commands:${NC}"
echo -e "    ${CYAN}forcefocus start${NC}  ${DIM}--- Start session${NC}"
echo -e "    ${CYAN}forcefocus status${NC} ${DIM}--- Check progress${NC}"
echo -e "    ${CYAN}forcefocus stop${NC}   ${DIM}--- Request unlock${NC}"
echo ""
