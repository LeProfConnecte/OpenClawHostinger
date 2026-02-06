#!/usr/bin/env bash
# =============================================================================
# OpenClaw - Full Deployment Script for CloudPanel / Hostinger VPS
#
# IDEMPOTENT: safe to re-run at any time without side effects.
# Run as root:  sudo bash deploy/deploy.sh
#
# What this script does:
#   1. Installs system deps (Python, Supervisor)
#   2. Installs Node.js (for frontend build + clawdbot)
#   3. Creates Python venv & installs backend deps
#   4. Generates backend .env from template (first run only)
#   5. Builds React frontend
#   6. Installs clawdbot (gateway binary)
#   7. Configures Supervisor for backend + gateway
#   8. Grants site user passwordless supervisorctl access (sudoers)
#   9. Sets correct file permissions for CloudPanel
#  10. Generates a ready-to-paste nginx vhost
#  11. Starts the backend & runs a health check
# =============================================================================
set -euo pipefail

# ======================== CONFIGURATION ========================
# Your CloudPanel domain (MUST match the site created in CloudPanel)
DOMAIN="${OPENCLAW_DOMAIN:-myopenclaw.leprofconnecte.com}"

# Leave empty to auto-detect from /home/*/htdocs/<domain>
SITE_ROOT="${OPENCLAW_SITE_ROOT:-}"

# Versions
NODE_VERSION="22.22.0"
PYTHON_BIN="python3"

# Set to "atlas" to skip local MongoDB installation (default: auto-detect)
# If your MONGO_URL in .env starts with mongodb+srv:// this is set automatically
MONGODB_MODE="${OPENCLAW_MONGODB_MODE:-auto}"

# ======================== HELPERS ========================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'
log()  { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC}  $1"; }
info() { echo -e "${CYAN}[INFO]${NC}  $1"; }
die()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

step_count=0
step() { step_count=$((step_count + 1)); echo -e "\n${BOLD}=== Step ${step_count}: $1 ===${NC}"; }

require_root() { [ "$(id -u)" -eq 0 ] || die "Run as root: sudo bash deploy/deploy.sh"; }

# ======================== PATH RESOLUTION ========================
autodetect_site_root() {
  # CloudPanel typically uses /home/<site_user>/htdocs/<domain>
  local found
  found="$(find /home -maxdepth 3 -type d -path "/home/*/htdocs/${DOMAIN}" -print 2>/dev/null | head -n 1 || true)"
  if [ -n "${found}" ] && [ -d "${found}" ]; then
    echo "${found}"
    return 0
  fi
  return 1
}

# ======================== START ========================
require_root
echo ""
echo -e "${BOLD}=============================================${NC}"
echo -e "${BOLD} OpenClaw Deployment - CloudPanel / Hostinger${NC}"
echo -e "${BOLD}=============================================${NC}"
echo ""

[ "${DOMAIN}" != "yourdomain.com" ] || die "Set DOMAIN in deploy.sh or export OPENCLAW_DOMAIN before running."

# Resolve site root
if [ -z "${SITE_ROOT}" ]; then
  SITE_ROOT="$(autodetect_site_root)" || die "Cannot find site root for ${DOMAIN}. Create the site in CloudPanel first."
fi
[ -d "${SITE_ROOT}" ] || die "Site root does not exist: ${SITE_ROOT}"

# Derive paths
VENV_DIR="${SITE_ROOT}/venv"
BACKEND_DIR="${SITE_ROOT}/backend"
FRONTEND_DIR="${SITE_ROOT}/frontend"
FRONTEND_BUILD_DIR="${FRONTEND_DIR}/build"
NODE_DIR="/root/nodejs"
CLAWDBOT_HOME="/root/.clawdbot"

# Validate source code exists
[ -d "${BACKEND_DIR}" ] || die "Missing ${BACKEND_DIR} - did you clone the repo into the site root?"
[ -d "${FRONTEND_DIR}" ] || die "Missing ${FRONTEND_DIR}"
[ -f "${BACKEND_DIR}/requirements.txt" ] || die "Missing backend/requirements.txt"

# Detect CloudPanel site user (owner of SITE_ROOT)
SITE_USER="$(stat -c '%U' "${SITE_ROOT}" 2>/dev/null || echo "")"
if [ -z "${SITE_USER}" ] || [ "${SITE_USER}" = "root" ]; then
  die "Could not detect CloudPanel site user from ${SITE_ROOT}. The site must be created in CloudPanel first (owner should not be root)."
fi
SITE_GROUP="$(stat -c '%G' "${SITE_ROOT}" 2>/dev/null || echo "${SITE_USER}")"

info "Domain:    ${DOMAIN}"
info "Site root: ${SITE_ROOT}"
info "Site user: ${SITE_USER}:${SITE_GROUP}"

# ======================== 1. SYSTEM PACKAGES ========================
step "Installing system dependencies"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# Essential tools
apt-get install -y -qq ca-certificates curl gnupg lsb-release sudo

# Python
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  apt-get install -y -qq python3 python3-venv python3-pip
fi
apt-get install -y -qq python3-venv python3-pip

# Supervisor
if ! command -v supervisord >/dev/null 2>&1; then
  apt-get install -y -qq supervisor
fi
systemctl enable supervisor >/dev/null 2>&1 || true
systemctl start supervisor  >/dev/null 2>&1 || true

# ======================== 2. MONGODB (optional local) ========================
# Auto-detect Atlas if .env exists and contains mongodb+srv://
if [ "${MONGODB_MODE}" = "auto" ] && [ -f "${BACKEND_DIR}/.env" ]; then
  if grep -q 'mongodb+srv://' "${BACKEND_DIR}/.env" 2>/dev/null; then
    MONGODB_MODE="atlas"
  fi
fi

if [ "${MONGODB_MODE}" = "atlas" ]; then
  info "MongoDB mode: Atlas (remote) - skipping local installation"
else
  step "Installing MongoDB (local, best effort)"
  if ! command -v mongod >/dev/null 2>&1; then
    curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
      | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg 2>/dev/null || true
    OS_CODENAME="$(lsb_release -cs 2>/dev/null || echo "jammy")"
    echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu ${OS_CODENAME}/mongodb-org/7.0 multiverse" \
      > /etc/apt/sources.list.d/mongodb-org-7.0.list
    apt-get update -qq
    apt-get install -y -qq mongodb-org 2>/dev/null || apt-get install -y -qq mongodb 2>/dev/null || warn "MongoDB install failed - ensure MONGO_URL in .env points to an accessible instance"
  fi
  systemctl enable mongod >/dev/null 2>&1 || true
  systemctl start mongod  >/dev/null 2>&1 || true
fi

# ======================== 3. NODE.JS ========================
step "Setting up Node.js v${NODE_VERSION}"
if [ ! -x "${NODE_DIR}/bin/node" ]; then
  log "Installing Node.js into ${NODE_DIR}..."
  mkdir -p "${NODE_DIR}"

  ARCH="$(uname -m)"
  case "${ARCH}" in
    x86_64)  NODE_ARCH="x64" ;;
    aarch64) NODE_ARCH="arm64" ;;
    *)       NODE_ARCH="x64" ;;
  esac

  cd /tmp
  curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" -o node.tar.xz
  tar -xJf node.tar.xz
  cp -r "node-v${NODE_VERSION}-linux-${NODE_ARCH}/"* "${NODE_DIR}/"
  rm -rf node.tar.xz "node-v${NODE_VERSION}-linux-${NODE_ARCH}"
  log "Node.js installed: $(${NODE_DIR}/bin/node -v)"
else
  log "Node.js already installed: $(${NODE_DIR}/bin/node -v)"
fi

export PATH="${NODE_DIR}/bin:${PATH}"

if ! command -v yarn >/dev/null 2>&1; then
  log "Installing Yarn..."
  npm install -g yarn >/dev/null 2>&1 || npm install -g yarn
fi

# ======================== 4. PYTHON VENV + BACKEND DEPS ========================
step "Setting up Python virtual environment"
if [ ! -d "${VENV_DIR}" ]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
  log "Created venv at ${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
pip install --upgrade pip -q
pip install -r "${BACKEND_DIR}/requirements.txt" -q
log "Python dependencies installed"

# ======================== 5. BACKEND .ENV ========================
step "Configuring backend environment"
if [ ! -f "${BACKEND_DIR}/.env" ]; then
  if [ -f "${BACKEND_DIR}/.env.example" ]; then
    cp "${BACKEND_DIR}/.env.example" "${BACKEND_DIR}/.env"
    warn "Created ${BACKEND_DIR}/.env from template."
    warn ">>> YOU MUST EDIT THIS FILE before the app will work <<<"
    warn "    Required: MONGO_URL, EMERGENT_API_KEY, CORS_ORIGINS"
  else
    die "No .env.example found. Create ${BACKEND_DIR}/.env manually."
  fi
else
  log "backend/.env already exists (kept as-is)"
fi

# ======================== 6. FRONTEND BUILD ========================
step "Building React frontend"
cd "${FRONTEND_DIR}"
export REACT_APP_BACKEND_URL=""
yarn install --frozen-lockfile 2>/dev/null || yarn install
yarn build

if [ ! -f "${FRONTEND_BUILD_DIR}/index.html" ]; then
  die "Frontend build failed: ${FRONTEND_BUILD_DIR}/index.html not found"
fi
log "Frontend built successfully"

# ======================== 7. CLAWDBOT / MOLTBOT DEPS ========================
step "Installing clawdbot dependencies"
cd "${BACKEND_DIR}"
bash install_moltbot_deps.sh || warn "Clawdbot deps had issues - check /tmp/moltbot_deps.log"

# ======================== 8. SUPERVISOR CONFIG ========================
step "Configuring Supervisor"
SUPERVISOR_CONF="/etc/supervisor/conf.d/openclaw.conf"

cat > "${SUPERVISOR_CONF}" <<SUPEOF
; Auto-generated by deploy.sh - do not edit manually
; Re-run deploy.sh to regenerate

[program:openclaw-backend]
command=${VENV_DIR}/bin/uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1 --log-level info
directory=${BACKEND_DIR}
user=${SITE_USER}
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
command=/root/run_clawdbot.sh gateway --config ${CLAWDBOT_HOME}/clawdbot.json
directory=/root
environment=NODE_DIR="${NODE_DIR}",CLAWDBOT_DIR="/root/.clawdbot-bin",CLAWDBOT_HOME="${CLAWDBOT_HOME}",PATH="${NODE_DIR}/bin:/root/.clawdbot-bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
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
SUPEOF

mkdir -p /var/log/supervisor
supervisorctl reread >/dev/null 2>&1 || true
supervisorctl update  >/dev/null 2>&1 || true
log "Supervisor config written to ${SUPERVISOR_CONF}"

# ======================== 9. SUDOERS (site user -> supervisorctl) ========================
step "Configuring sudo access for ${SITE_USER}"
SUDOERS_FILE="/etc/sudoers.d/openclaw"

# Allow site user to run supervisorctl commands without password (for gateway management)
cat > "${SUDOERS_FILE}" <<SUDEOF
# OpenClaw: allow site user to manage gateway via supervisorctl
# Auto-generated by deploy.sh
${SITE_USER} ALL=(root) NOPASSWD: /usr/bin/supervisorctl start clawdbot-gateway
${SITE_USER} ALL=(root) NOPASSWD: /usr/bin/supervisorctl stop clawdbot-gateway
${SITE_USER} ALL=(root) NOPASSWD: /usr/bin/supervisorctl restart clawdbot-gateway
${SITE_USER} ALL=(root) NOPASSWD: /usr/bin/supervisorctl status clawdbot-gateway
${SITE_USER} ALL=(root) NOPASSWD: /usr/bin/supervisorctl reread
${SITE_USER} ALL=(root) NOPASSWD: /usr/bin/supervisorctl update
SUDEOF
chmod 440 "${SUDOERS_FILE}"

# Validate sudoers syntax
if visudo -cf "${SUDOERS_FILE}" >/dev/null 2>&1; then
  log "Sudoers configured: ${SITE_USER} can manage gateway via supervisorctl"
else
  rm -f "${SUDOERS_FILE}"
  die "Sudoers syntax check failed! Removed ${SUDOERS_FILE}."
fi

# ======================== 10. PERMISSIONS ========================
step "Setting file permissions"

# Backend + venv owned by site user (backend runs as site user)
chown -R "${SITE_USER}:${SITE_GROUP}" "${BACKEND_DIR}" "${VENV_DIR}"

# Frontend owned by site user (CloudPanel serves it via nginx)
chown -R "${SITE_USER}:${SITE_GROUP}" "${FRONTEND_DIR}"

# .env restricted to site user only
if [ -f "${BACKEND_DIR}/.env" ]; then
  chown "${SITE_USER}:${SITE_GROUP}" "${BACKEND_DIR}/.env"
  chmod 600 "${BACKEND_DIR}/.env"
fi

# Clawdbot home dir (root-owned, gateway runs as root)
mkdir -p "${CLAWDBOT_HOME}"
chmod 700 "${CLAWDBOT_HOME}"

# Log directory writable by supervisor
touch /var/log/supervisor/openclaw-backend.log /var/log/supervisor/clawdbot-gateway.log
chmod 644 /var/log/supervisor/openclaw-backend.log /var/log/supervisor/clawdbot-gateway.log

log "Permissions set for CloudPanel site user: ${SITE_USER}"

# ======================== 11. GENERATE VHOST ========================
step "Generating nginx vhost configuration"
VHOST_OUTPUT="${SITE_ROOT}/deploy/generated-vhost.conf"

# Read the template and replace placeholders with actual values
if [ -f "${SITE_ROOT}/deploy/cloudpanel-vhost.conf" ]; then
  sed -e "s|{{DOMAIN}}|${DOMAIN}|g" \
      -e "s|{{SITE_ROOT}}|${SITE_ROOT}|g" \
      "${SITE_ROOT}/deploy/cloudpanel-vhost.conf" > "${VHOST_OUTPUT}"
  log "Generated vhost at: ${VHOST_OUTPUT}"
else
  warn "Template deploy/cloudpanel-vhost.conf not found - skipping vhost generation"
fi

# ======================== 12. START & VERIFY ========================
step "Starting backend"
supervisorctl restart openclaw-backend >/dev/null 2>&1 || supervisorctl start openclaw-backend >/dev/null 2>&1 || true

# Wait for backend to come up
log "Waiting for backend to start..."
RETRIES=0
MAX_RETRIES=15
while [ ${RETRIES} -lt ${MAX_RETRIES} ]; do
  if curl -sf http://127.0.0.1:8000/api/ >/dev/null 2>&1; then
    break
  fi
  RETRIES=$((RETRIES + 1))
  sleep 2
done

if curl -sf http://127.0.0.1:8000/api/ >/dev/null 2>&1; then
  log "Backend is running and responding!"
  HEALTH_RESPONSE="$(curl -sf http://127.0.0.1:8000/api/ 2>/dev/null || echo 'no response')"
  info "Health check: ${HEALTH_RESPONSE}"
else
  warn "Backend did not respond after ${MAX_RETRIES} attempts."
  warn "Check logs: tail -f /var/log/supervisor/openclaw-backend.log"
fi

# Verify sudoers works for the site user
if sudo -u "${SITE_USER}" sudo -n supervisorctl status clawdbot-gateway >/dev/null 2>&1; then
  log "Verified: ${SITE_USER} can run supervisorctl via sudo"
else
  warn "Site user cannot run supervisorctl - gateway management may fail"
  warn "Check: /etc/sudoers.d/openclaw"
fi

# ======================== SUMMARY ========================
echo ""
echo -e "${BOLD}=============================================${NC}"
echo -e "${BOLD} OpenClaw Deployment Complete${NC}"
echo -e "${BOLD}=============================================${NC}"
echo ""
echo -e "  Domain:    ${CYAN}${DOMAIN}${NC}"
echo -e "  Site root: ${CYAN}${SITE_ROOT}${NC}"
echo -e "  Site user: ${CYAN}${SITE_USER}${NC}"
echo -e "  Backend:   ${CYAN}http://127.0.0.1:8000/api/${NC}"
echo ""

# Check what still needs manual setup
NEEDS_ACTION=false

if [ -f "${BACKEND_DIR}/.env" ]; then
  if grep -q 'sk-emergent-your-key-here' "${BACKEND_DIR}/.env" 2>/dev/null; then
    echo -e "  ${YELLOW}[ACTION NEEDED]${NC} Edit ${BACKEND_DIR}/.env"
    echo -e "      Set: EMERGENT_API_KEY, MONGO_URL, CORS_ORIGINS"
    NEEDS_ACTION=true
  fi
fi

if [ -f "${VHOST_OUTPUT}" ]; then
  echo ""
  echo -e "  ${YELLOW}[ACTION NEEDED]${NC} Configure nginx vhost in CloudPanel:"
  echo -e "      1. CloudPanel > Sites > ${DOMAIN} > Vhost"
  echo -e "      2. Replace the server block with contents of:"
  echo -e "         ${CYAN}${VHOST_OUTPUT}${NC}"
  echo -e "      3. CloudPanel > SSL/TLS > Issue Let's Encrypt certificate"
  NEEDS_ACTION=true
fi

if [ "${NEEDS_ACTION}" = true ]; then
  echo ""
  echo -e "  After making changes, restart the backend:"
  echo -e "      ${CYAN}sudo supervisorctl restart openclaw-backend${NC}"
fi

echo ""
echo -e "  ${GREEN}Useful commands:${NC}"
echo -e "      Status:  sudo supervisorctl status"
echo -e "      Logs:    tail -f /var/log/supervisor/openclaw-backend.log"
echo -e "      Restart: sudo supervisorctl restart openclaw-backend"
echo -e "      Re-deploy: sudo bash ${SITE_ROOT}/deploy/deploy.sh"
echo ""
