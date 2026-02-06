#!/usr/bin/env bash
# =============================================================================
# OpenClaw - Deployment Script (CloudPanel / Hostinger VPS)
# Idempotent: safe to re-run
# =============================================================================
set -euo pipefail

# ======================== CONFIGURATION ========================
# REQUIRED
DOMAIN="myopenclaw.leprofconnecte.com"

# OPTIONAL (leave empty to auto-detect from /home/*/htdocs/<domain>)
SITE_ROOT=""

# Versions
NODE_VERSION="22.22.0"
PYTHON_BIN="python3"

# ======================== COLORS ========================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
log()  { echo -e "${GREEN}[DEPLOY]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
die()  { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

require_root() { [ "$(id -u)" -eq 0 ] || die "Run as root: sudo bash deploy/deploy.sh"; }

# ======================== PATH RESOLUTION ========================
autodetect_site_root() {
  local d1="/home/clp/htdocs/${DOMAIN}"
  if [ -d "$d1" ]; then
    echo "$d1"
    return 0
  fi

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
log "Starting OpenClaw deployment..."

[ "${DOMAIN}" != "yourdomain.com" ] || die "Edit DOMAIN in deploy/deploy.sh before running."

if [ -z "${SITE_ROOT}" ]; then
  SITE_ROOT="$(autodetect_site_root)" || die "Cannot find site root. Ensure CloudPanel site exists for ${DOMAIN}."
fi

[ -d "${SITE_ROOT}" ] || die "Site root does not exist: ${SITE_ROOT}"

PROJECT_DIR="${SITE_ROOT}"
VENV_DIR="${SITE_ROOT}/venv"
BACKEND_DIR="${SITE_ROOT}/backend"
FRONTEND_DIR="${SITE_ROOT}/frontend"
FRONTEND_BUILD_DIR="${FRONTEND_DIR}/build"

[ -d "${BACKEND_DIR}" ] || die "Missing backend directory: ${BACKEND_DIR}"
[ -d "${FRONTEND_DIR}" ] || die "Missing frontend directory: ${FRONTEND_DIR}"
[ -f "${BACKEND_DIR}/requirements.txt" ] || die "Missing backend/requirements.txt"

# For convenience: detect CloudPanel site user (owner of SITE_ROOT)
SITE_USER="$(stat -c '%U' "${SITE_ROOT}" 2>/dev/null || echo "")"
if [ -z "${SITE_USER}" ] || [ "${SITE_USER}" = "root" ]; then
  warn "Could not detect a non-root SITE_USER from ${SITE_ROOT}. Continuing anyway."
fi

# ======================== SYSTEM PACKAGES ========================
log "Installing system dependencies (apt)..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# Tools used by the script
apt-get install -y -qq ca-certificates curl gnupg lsb-release

# Python
if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  apt-get install -y -qq python3 python3-venv python3-pip
fi
apt-get install -y -qq python3-venv python3-pip

# Supervisor
if ! command -v supervisord >/dev/null 2>&1; then
  apt-get install -y -qq supervisor
  systemctl enable supervisor >/dev/null 2>&1 || true
  systemctl start supervisor  >/dev/null 2>&1 || true
fi

# MongoDB (best effort)
if ! command -v mongod >/dev/null 2>&1; then
  log "Installing MongoDB (best effort)..."
  curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
    | gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg 2>/dev/null || true

  OS_CODENAME="$(lsb_release -cs 2>/dev/null || echo "jammy")"
  echo "deb [ signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] https://repo.mongodb.org/apt/ubuntu ${OS_CODENAME}/mongodb-org/7.0 multiverse" \
    > /etc/apt/sources.list.d/mongodb-org-7.0.list

  apt-get update -qq
  if ! apt-get install -y -qq mongodb-org; then
    warn "mongodb-org install failed, trying 'mongodb' package..."
    apt-get install -y -qq mongodb || true
  fi
fi
systemctl enable mongod >/dev/null 2>&1 || true
systemctl start mongod  >/dev/null 2>&1 || true

# ======================== NODE.JS (for frontend build + clawdbot deps) ========================
NODE_DIR="/root/nodejs"
if [ ! -x "${NODE_DIR}/bin/node" ]; then
  log "Installing Node.js v${NODE_VERSION} into ${NODE_DIR}..."
  mkdir -p "${NODE_DIR}"

  ARCH="$(uname -m)"
  case "${ARCH}" in
    x86_64) NODE_ARCH="x64" ;;
    aarch64) NODE_ARCH="arm64" ;;
    *) NODE_ARCH="x64" ;;
  esac

  cd /tmp
  curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.xz" -o node.tar.xz
  tar -xJf node.tar.xz
  cp -r "node-v${NODE_VERSION}-linux-${NODE_ARCH}/"* "${NODE_DIR}/"
  rm -rf node.tar.xz "node-v${NODE_VERSION}-linux-${NODE_ARCH}"
else
  log "Node.js already installed at ${NODE_DIR}"
fi

export PATH="${NODE_DIR}/bin:${PATH}"

if ! command -v yarn >/dev/null 2>&1; then
  log "Installing Yarn..."
  npm install -g yarn >/dev/null 2>&1 || npm install -g yarn
fi

# ======================== PYTHON VENV + BACKEND DEPS ========================
log "Setting up Python virtual environment..."
if [ ! -d "${VENV_DIR}" ]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

# shellcheck disable=SC1091
source "${VENV_DIR}/bin/activate"
pip install --upgrade pip -q
pip install -r "${BACKEND_DIR}/requirements.txt" -q

# ======================== BACKEND .ENV ========================
if [ ! -f "${BACKEND_DIR}/.env" ]; then
  if [ -f "${BACKEND_DIR}/.env.example" ]; then
    cp "${BACKEND_DIR}/.env.example" "${BACKEND_DIR}/.env"
    sed -i "s/yourdomain.com/${DOMAIN}/g" "${BACKEND_DIR}/.env" || true
    warn "Created ${BACKEND_DIR}/.env from .env.example - you must edit EMERGENT_API_KEY + CORS_ORIGINS."
  else
    warn "No .env.example found. Create ${BACKEND_DIR}/.env manually."
  fi
else
  log "backend/.env already exists (kept as-is)"
fi

# ======================== FRONTEND BUILD ========================
log "Building React frontend..."
cd "${FRONTEND_DIR}"
export REACT_APP_BACKEND_URL=""
yarn install --frozen-lockfile 2>/dev/null || yarn install
yarn build

if [ ! -f "${FRONTEND_BUILD_DIR}/index.html" ]; then
  die "Frontend build failed: ${FRONTEND_BUILD_DIR}/index.html not found"
fi

# ======================== CLAWDBOT / MOLT deps ========================
log "Installing clawdbot dependencies (best effort)..."
cd "${BACKEND_DIR}"
bash install_moltbot_deps.sh || warn "Clawdbot deps had issues - check /tmp/moltbot_deps.log"

# ======================== SUPERVISOR CONFIG ========================
log "Configuring Supervisor..."
SUPERVISOR_CONF="/etc/supervisor/conf.d/openclaw.conf"

# Dedicated service user for backend
if ! id -u openclaw >/dev/null 2>&1; then
  useradd -r -s /usr/sbin/nologin -d "${SITE_ROOT}" openclaw
  log "Created service user: openclaw"
fi

cat > "${SUPERVISOR_CONF}" <<EOF
[program:openclaw-backend]
command=${VENV_DIR}/bin/uvicorn server:app --host 127.0.0.1 --port 8000 --workers 1 --log-level info
directory=${BACKEND_DIR}
user=${SITE_USER:-openclaw}
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
environment=NODE_DIR="/root/nodejs",CLAWDBOT_DIR="/root/.clawdbot-bin",CLAWDBOT_HOME="/root/.clawdbot",PATH="/root/nodejs/bin:/root/.clawdbot-bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
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
EOF

mkdir -p /var/log/supervisor
supervisorctl reread >/dev/null
supervisorctl update  >/dev/null

# ======================== PERMISSIONS ========================
log "Setting file permissions..."
chown -R openclaw:openclaw "${BACKEND_DIR}" "${VENV_DIR}"

# Keep frontend editable by CloudPanel site user if possible
if [ -n "${SITE_USER}" ] && id -u "${SITE_USER}" >/dev/null 2>&1; then
  chown -R "${SITE_USER}:${SITE_USER}" "${FRONTEND_DIR}" || true
fi

if [ -f "${BACKEND_DIR}/.env" ]; then
  chown openclaw:openclaw "${BACKEND_DIR}/.env"
  chmod 600 "${BACKEND_DIR}/.env"
fi

mkdir -p /root/.clawdbot
chmod 700 /root/.clawdbot

# ======================== START BACKEND ========================
log "Starting backend..."
supervisorctl restart openclaw-backend >/dev/null 2>&1 || supervisorctl start openclaw-backend

echo ""
echo "============================================="
echo " OpenClaw Deployment Complete"
echo "============================================="
echo ""
echo "Next steps:"
echo "1) CloudPanel > Sites > ${DOMAIN} > Vhost: paste the corrected vhost (below)."
echo "2) CloudPanel > SSL/TLS: issue Let's Encrypt."
echo "3) Edit: ${BACKEND_DIR}/.env (CORS_ORIGINS + EMERGENT_API_KEY)."
echo "4) Restart: sudo supervisorctl restart openclaw-backend"
echo "5) Local check: curl -s http://127.0.0.1:8000/api/"
echo ""
