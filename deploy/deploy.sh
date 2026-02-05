#!/bin/bash
# =============================================================================
# OpenClaw Deployment Script for Hostinger VPS with CloudPanel
# =============================================================================
#
# PREREQUISITES:
#   - Hostinger VPS with CloudPanel installed
#   - A domain pointing to your VPS IP
#   - SSH root access
#
# USAGE:
#   1. Upload the project to your VPS
#   2. Edit the variables below to match your setup
#   3. Run: sudo bash deploy/deploy.sh
#
# WHAT THIS SCRIPT DOES:
#   - Installs system dependencies (Python, MongoDB, Node.js, supervisor)
#   - Creates a Python virtual environment
#   - Installs backend dependencies
#   - Builds the React frontend
#   - Configures supervisor for the backend and gateway
#   - Creates the .env file from .env.example
#
# AFTER RUNNING THIS SCRIPT:
#   1. Go to CloudPanel -> Sites -> your domain -> Vhost
#   2. Paste the content of deploy/cloudpanel-vhost.conf
#   3. Replace "yourdomain.com" with your actual domain
#   4. Enable SSL via CloudPanel's Let's Encrypt integration
#   5. Edit backend/.env with your actual MONGO_URL and other settings
#   6. Run: sudo supervisorctl restart openclaw-backend
# =============================================================================

set -e

# ======================== CONFIGURATION ========================
# EDIT THESE VARIABLES before running the script

DOMAIN="yourdomain.com"
# CloudPanel typically uses /home/clp/htdocs/<domain>/ as the site root
SITE_ROOT="/home/clp/htdocs/${DOMAIN}"
PROJECT_DIR="${SITE_ROOT}"
VENV_DIR="${SITE_ROOT}/venv"
BACKEND_DIR="${SITE_ROOT}/backend"
FRONTEND_DIR="${SITE_ROOT}/frontend"
NODE_VERSION="22.22.0"
PYTHON_VERSION="3"

# ======================== COLORS ========================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ======================== CHECKS ========================
log "Starting OpenClaw deployment..."

if [ "$(id -u)" -ne 0 ]; then
    error "This script must be run as root (sudo)"
fi

if [ ! -d "${SITE_ROOT}" ]; then
    error "Site root ${SITE_ROOT} does not exist. Create the site in CloudPanel first."
fi

# ======================== SYSTEM DEPENDENCIES ========================
log "Installing system dependencies..."

apt-get update -qq

# Python
if ! command -v python3 &> /dev/null; then
    apt-get install -y python${PYTHON_VERSION} python${PYTHON_VERSION}-venv python${PYTHON_VERSION}-pip
fi

# pip and venv
apt-get install -y python3-venv python3-pip -qq

# MongoDB
if ! command -v mongod &> /dev/null; then
    log "Installing MongoDB..."
    # Import MongoDB public GPG key
    curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
        gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg 2>/dev/null || true

    # Detect OS version
    OS_CODENAME=$(lsb_release -cs 2>/dev/null || echo "jammy")

    echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu ${OS_CODENAME}/mongodb-org/7.0 multiverse" | \
        tee /etc/apt/sources.list.d/mongodb-org-7.0.list

    apt-get update -qq
    apt-get install -y mongodb-org || {
        warn "MongoDB package install failed. Trying mongosh + mongod standalone..."
        apt-get install -y mongodb || true
    }

    systemctl enable mongod 2>/dev/null || true
    systemctl start mongod 2>/dev/null || true
    log "MongoDB installed and started"
else
    log "MongoDB already installed"
    systemctl enable mongod 2>/dev/null || true
    systemctl start mongod 2>/dev/null || true
fi

# Supervisor
if ! command -v supervisord &> /dev/null; then
    apt-get install -y supervisor
    systemctl enable supervisor
    systemctl start supervisor
fi

# Node.js (for building frontend and running clawdbot)
NODE_DIR="/root/nodejs"
if [ ! -f "${NODE_DIR}/bin/node" ]; then
    log "Installing Node.js v${NODE_VERSION}..."
    mkdir -p "${NODE_DIR}"

    ARCH=$(uname -m)
    if [ "$ARCH" = "x86_64" ]; then
        NODE_ARCH="x64"
    elif [ "$ARCH" = "aarch64" ]; then
        NODE_ARCH="arm64"
    else
        NODE_ARCH="x64"
    fi

    cd /tmp
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" -o "node.tar.xz"
    tar -xJf "node.tar.xz"
    cp -r "node-v${NODE_VERSION}-linux-${NODE_ARCH}"/* "${NODE_DIR}/"
    rm -rf "node.tar.xz" "node-v${NODE_VERSION}-linux-${NODE_ARCH}"
    log "Node.js v${NODE_VERSION} installed"
else
    log "Node.js already installed at ${NODE_DIR}"
fi

export PATH="${NODE_DIR}/bin:$PATH"

# Yarn (used by the frontend)
if ! command -v yarn &> /dev/null; then
    npm install -g yarn
fi

# ======================== PYTHON VIRTUAL ENVIRONMENT ========================
log "Setting up Python virtual environment..."

if [ ! -d "${VENV_DIR}" ]; then
    python3 -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"
pip install --upgrade pip -q
pip install -r "${BACKEND_DIR}/requirements.txt" -q
log "Python dependencies installed"

# ======================== BACKEND .ENV ========================
if [ ! -f "${BACKEND_DIR}/.env" ]; then
    if [ -f "${BACKEND_DIR}/.env.example" ]; then
        cp "${BACKEND_DIR}/.env.example" "${BACKEND_DIR}/.env"
        # Substitute domain
        sed -i "s/yourdomain.com/${DOMAIN}/g" "${BACKEND_DIR}/.env"
        warn "Created ${BACKEND_DIR}/.env from .env.example - EDIT IT with your actual values!"
    else
        warn "No .env.example found. Create ${BACKEND_DIR}/.env manually."
    fi
else
    log ".env file already exists"
fi

# ======================== FRONTEND BUILD ========================
log "Building React frontend..."

cd "${FRONTEND_DIR}"

# Set the backend URL for the build (same origin, no prefix needed)
export REACT_APP_BACKEND_URL=""

yarn install --frozen-lockfile 2>/dev/null || yarn install
yarn build

log "Frontend built successfully"

# ======================== CLAWDBOT INSTALLATION ========================
log "Installing clawdbot..."

cd "${BACKEND_DIR}"
bash install_moltbot_deps.sh || warn "Clawdbot installation had issues - check logs"

# ======================== SUPERVISOR CONFIGURATION ========================
log "Configuring supervisor..."

# Generate the supervisor config with correct paths
SUPERVISOR_CONF="/etc/supervisor/conf.d/openclaw.conf"

cat > "${SUPERVISOR_CONF}" << SUPERVISOREOF
[program:openclaw-backend]
command=${VENV_DIR}/bin/uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1 --log-level info
directory=${BACKEND_DIR}
user=root
autostart=true
autorestart=true
startretries=5
startsecs=5
stopwaitsecs=30
redirect_stderr=true
stdout_logfile=/var/log/supervisor/openclaw-backend.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=3

[program:clawdbot-gateway]
command=/root/run_clawdbot.sh gateway --config /root/.clawdbot/clawdbot.json
directory=/root
environment=NODE_DIR="/root/nodejs",CLAWDBOT_DIR="/root/.clawdbot-bin",PATH="/root/nodejs/bin:/root/.clawdbot-bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
user=root
autostart=false
autorestart=unexpected
startretries=3
startsecs=5
stopwaitsecs=15
redirect_stderr=true
stdout_logfile=/var/log/supervisor/clawdbot-gateway.log
stdout_logfile_maxbytes=10MB
stdout_logfile_backups=3
SUPERVISOREOF

# Create log directory
mkdir -p /var/log/supervisor

supervisorctl reread
supervisorctl update

log "Supervisor configured"

# ======================== PERMISSIONS ========================
log "Setting file permissions..."

# Secure the backend .env file
if [ -f "${BACKEND_DIR}/.env" ]; then
    chmod 600 "${BACKEND_DIR}/.env"
fi

# Secure clawdbot config directory
mkdir -p /root/.clawdbot
chmod 700 /root/.clawdbot

# ======================== START BACKEND ========================
log "Starting OpenClaw backend..."
supervisorctl start openclaw-backend 2>/dev/null || supervisorctl restart openclaw-backend

# ======================== DONE ========================
echo ""
echo "============================================="
echo -e "${GREEN}  OpenClaw Deployment Complete!${NC}"
echo "============================================="
echo ""
echo "NEXT STEPS:"
echo ""
echo "  1. CONFIGURE CloudPanel Vhost:"
echo "     - Go to CloudPanel -> Sites -> ${DOMAIN} -> Vhost"
echo "     - Paste the content of deploy/cloudpanel-vhost.conf"
echo "     - Replace 'yourdomain.com' with '${DOMAIN}'"
echo "     - Save and restart Nginx"
echo ""
echo "  2. ENABLE SSL:"
echo "     - Go to CloudPanel -> Sites -> ${DOMAIN} -> SSL/TLS"
echo "     - Click 'Create Let's Encrypt Certificate'"
echo ""
echo "  3. EDIT backend/.env:"
echo "     - Set MONGO_URL, CORS_ORIGINS, EMERGENT_API_KEY"
echo "     - File: ${BACKEND_DIR}/.env"
echo ""
echo "  4. RESTART backend after .env changes:"
echo "     sudo supervisorctl restart openclaw-backend"
echo ""
echo "  5. CHECK STATUS:"
echo "     sudo supervisorctl status"
echo "     curl -s http://127.0.0.1:8000/api/ | python3 -m json.tool"
echo ""
echo "  LOGS:"
echo "     tail -f /var/log/supervisor/openclaw-backend.log"
echo "     tail -f /var/log/supervisor/clawdbot-gateway.log"
echo ""
