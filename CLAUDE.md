# CLAUDE.md - OpenClaw Hostinger

## Project Overview

OpenClaw is a full-stack web application that provides a hosting wrapper for the Moltbot (ClawdBot) gateway. It handles user authentication via Emergent Google OAuth, provides a setup wizard for configuring LLM providers (Emergent, OpenAI, Anthropic, OpenRouter), and reverse-proxies the Moltbot Control UI with WebSocket support. The application is a single-user private instance locked to the first authenticated user.

**Stack:** FastAPI (Python) + React (JavaScript) + MongoDB, deployed on Hostinger VPS with CloudPanel and Supervisor.

## Repository Structure

```
OpenClawHostinger/
├── backend/                    # FastAPI backend (Python)
│   ├── server.py               # Main application (~1400 lines) - all routes, models, middleware
│   ├── gateway_config.py       # Writes gateway.env for supervisor wrapper
│   ├── supervisor_client.py    # SupervisorClient class for process management
│   ├── whatsapp_monitor.py     # WhatsApp Baileys fix and status monitoring
│   ├── backend_test.py         # API integration test suite
│   ├── requirements.txt        # Python dependencies
│   ├── .env.example            # Environment variable template
│   └── install_moltbot_deps.sh # Clawdbot dependency installer
├── frontend/                   # React SPA (JavaScript)
│   ├── src/
│   │   ├── App.js              # Router with 3 routes: /, /login, auth callback
│   │   ├── pages/
│   │   │   ├── LoginPage.js    # Google OAuth login page
│   │   │   ├── SetupPage.js    # Provider selection and gateway control
│   │   │   └── AuthCallback.js # Session exchange after OAuth
│   │   ├── components/ui/      # ~47 shadcn/ui component files
│   │   ├── hooks/use-toast.js  # Toast notification hook
│   │   └── lib/utils.js        # Utility functions (cn helper)
│   ├── public/index.html       # HTML template with PostHog analytics
│   ├── package.json            # Node dependencies (yarn)
│   ├── tailwind.config.js      # TailwindCSS + dark theme config
│   └── craco.config.js         # Build config with @ path alias
├── deploy/                     # Deployment configs
│   ├── deploy.sh               # One-command VPS setup script
│   ├── cloudpanel-vhost.conf   # Nginx vhost for CloudPanel
│   └── supervisor-openclaw.conf # Supervisor process definitions
├── tests/                      # Additional test files
├── test_reports/               # Test iteration results (JSON)
├── memory/PRD.md               # Product requirements document
├── plan.md                     # Implementation plan (phases 1-4)
├── design_guidelines.md        # UI/brand design system
├── auth_testing.md             # Auth testing playbook
└── .gitignore                  # Excludes __pycache__/
```

## Tech Stack Details

### Backend
- **Framework:** FastAPI 0.110.1 with Uvicorn 0.25.0
- **Database:** MongoDB via Motor 3.3.1 (async) and PyMongo 4.5.0
- **Validation:** Pydantic 2.6.4+
- **Auth:** Emergent OAuth, session tokens in httpOnly cookies, python-jose for JWT
- **HTTP Client:** httpx 0.28.1 (async)
- **WebSockets:** websockets 15.0.1
- **Process Management:** Supervisor via subprocess calls
- **Monitoring:** psutil 7.2.2

### Frontend
- **Framework:** React 19.0.0 with Create React App (via craco)
- **Routing:** React Router 7.5.1
- **UI Components:** shadcn/ui (Radix UI primitives)
- **Styling:** TailwindCSS 3.4.17, dark theme, orange accent (#FF4500)
- **Animations:** Framer Motion 12.29.2
- **HTTP:** Axios with credentials
- **Package Manager:** Yarn 1.22.22

### Infrastructure
- **Server:** Hostinger VPS with CloudPanel
- **Web Server:** Nginx (CloudPanel-managed) reverse proxy to uvicorn:8000
- **Process Manager:** Supervisor (backend + gateway)
- **Database:** MongoDB 7.0 (local)
- **SSL:** Let's Encrypt via CloudPanel

## Key Architecture Decisions

- **Single monolith `server.py`:** All backend routes, models, and middleware live in one file. No blueprint/module splitting.
- **Supervisor for gateway persistence:** The Moltbot gateway runs as a supervisor-managed process, surviving backend restarts. The backend only controls it via `supervisorctl` commands.
- **Token reuse:** When gateway config changes only non-critical fields, the existing token is reused to avoid restarting the gateway.
- **Instance locking:** The first user to authenticate locks the entire instance. Other users get a 403. Stored in `instance_config` MongoDB collection.
- **Reverse proxy pattern:** The backend proxies all Moltbot UI requests (`/api/openclaw/ui/*`) and WebSocket connections (`/api/openclaw/ws`) to the gateway running on localhost ports 18789/18791.

## Development Commands

### Backend
```bash
# Install dependencies (in venv)
cd backend
pip install -r requirements.txt

# Run development server
uvicorn server:app --host 127.0.0.1 --port 8000 --reload

# Run tests
python backend_test.py
```

### Frontend
```bash
cd frontend

# Install dependencies
yarn install

# Start dev server
yarn start

# Production build
yarn build

# Run tests
yarn test
```

### Deployment
```bash
# Full deployment (run as root on VPS)
sudo bash deploy/deploy.sh

# Check service status
sudo supervisorctl status

# Restart backend after changes
sudo supervisorctl restart openclaw-backend

# View logs
tail -f /var/log/supervisor/openclaw-backend.log
tail -f /var/log/supervisor/clawdbot-gateway.log
```

## API Endpoints

All endpoints are prefixed with `/api`.

### Authentication
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/auth/session` | No | Exchange Emergent session_id for session cookie |
| GET | `/api/auth/me` | Yes | Get current user profile |
| POST | `/api/auth/logout` | Yes | Clear session and cookie |
| GET | `/api/auth/instance` | No | Check if instance is locked and by whom |

### Gateway Control
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/openclaw/start` | Yes | Start gateway with provider + API key |
| GET | `/api/openclaw/status` | No* | Get gateway running status (limited info if not authed) |
| POST | `/api/openclaw/stop` | Yes (owner) | Stop gateway |
| GET | `/api/openclaw/token` | Yes | Get current gateway token |

### Reverse Proxy
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET/POST | `/api/openclaw/ui/{path}` | Yes (owner) | Proxy to Moltbot Control UI |
| WS | `/api/openclaw/ws` | Yes (owner) | WebSocket proxy to gateway |

### WhatsApp
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/openclaw/whatsapp/status` | Yes | WhatsApp connection status |

### Legacy
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/status` | No | Create status check |
| GET | `/api/status` | No | List status checks |

## Database Collections (MongoDB)

- **`users`** - User profiles (user_id, email, name, picture, created_at)
- **`user_sessions`** - Session tokens with 7-day TTL (user_id, session_token, expires_at)
- **`moltbot_configs`** - Gateway config persistence (singleton doc `_id: "gateway_config"`)
- **`instance_config`** - Instance owner lock (singleton doc `_id: "instance_owner"`)
- **`status_checks`** - Legacy status monitoring entries

## Environment Variables

Defined in `backend/.env` (see `backend/.env.example`):

| Variable | Required | Description |
|----------|----------|-------------|
| `MONGO_URL` | Yes | MongoDB connection string (default: `mongodb://127.0.0.1:27017`) |
| `DB_NAME` | Yes | Database name (default: `openclaw_app`) |
| `CORS_ORIGINS` | Yes | Comma-separated allowed origins (never use `*` in prod) |
| `COOKIE_SECURE` | Yes | `true` for production (HTTPS), `false` for local dev |
| `COOKIE_SAMESITE` | Yes | `lax` recommended, `none` for cross-origin dev |
| `EMERGENT_API_KEY` | Yes | Emergent provider API key |
| `EMERGENT_BASE_URL` | Yes | Emergent LLM integration URL |

Optional overrides: `CLAWDBOT_HOME`, `OPENCLAW_WORKSPACE`, `NODE_DIR`, `CLAWDBOT_BIN_DIR`, `SUPERVISOR_GATEWAY_PROGRAM`.

## Security Model

- **Authentication:** Emergent Google OAuth -> session_id exchange -> httpOnly secure cookie
- **Authorization:** Instance locked to first authenticated user; owner-only for gateway operations
- **CSRF:** Middleware validates `Origin` header on state-changing requests (POST, PUT, DELETE, PATCH)
- **CORS:** Explicit origins only, credentials allowed
- **Secrets:** API keys passed via env vars to gateway, config files chmod 600, `.env` never exposed
- **Network:** Nginx blocks access to `.env`, `.git`, `.bak`, `.sql`, `.log` files; HTTPS enforced

## Conventions and Patterns

### Code Style
- **Backend:** Python with type hints, Pydantic models for request/response validation, async/await throughout
- **Frontend:** Functional React components, React Router for navigation, Axios for API calls with `withCredentials`
- **Formatting tools listed in requirements.txt:** black, isort, flake8, mypy (available but no enforced CI)

### Auth Pattern (Important)
- Auth callback uses URL **fragment** (`#session_id=...`), not query params
- The `App.js` router checks `location.hash` synchronously before route matching to prevent race conditions
- Never hardcode redirect URLs or add fallback URLs in auth flow (see comment in `App.js:9`)
- Session cookies are httpOnly - frontend cannot read them; use `/api/auth/me` to check auth status

### Gateway Management Pattern
1. Backend writes config to `~/.clawdbot/clawdbot.json`
2. Backend writes secrets to `~/.clawdbot/gateway.env` (via `gateway_config.py`)
3. Backend calls `supervisorctl start/stop/restart clawdbot-gateway`
4. Gateway reads config + env on startup
5. Backend proxies UI and WebSocket traffic to gateway ports (18789/18791)

### Frontend Path Alias
- `@` maps to `src/` (configured in `craco.config.js`)
- Import as: `import Foo from "@/components/ui/foo"`

### Provider Configuration
Each LLM provider has specific model defaults in `create_moltbot_config()` in `server.py`:
- **Emergent:** Dual-provider (GPT-5.2 + Claude Sonnet 4.5), uses Emergent API key from env
- **OpenAI:** Direct API, user provides key
- **Anthropic:** Claude Opus 4.5, user provides key
- **OpenRouter:** Flexible model, user provides key and optional model override

## Common Tasks for AI Assistants

### Adding a new API endpoint
1. Add Pydantic model(s) in the models section of `backend/server.py` (~line 66)
2. Add the route function with `@api_router.get/post/...` decorator
3. Use `current_user = await require_auth(request)` for protected endpoints
4. Use `await check_instance_access(current_user)` for owner-only endpoints

### Adding a new frontend page
1. Create page component in `frontend/src/pages/`
2. Add route in `frontend/src/App.js` inside `<Routes>`
3. Use shadcn/ui components from `@/components/ui/`
4. API calls: `axios.post/get("endpoint", data, { withCredentials: true })`

### Modifying the gateway configuration
- Config generation logic is in `create_moltbot_config()` in `server.py`
- Environment secrets are in `gateway_config.py` (`write_gateway_env`)
- Supervisor interaction is in `supervisor_client.py` (`SupervisorClient`)

### Debugging
- Backend logs: `tail -f /var/log/supervisor/openclaw-backend.log`
- Gateway logs: `tail -f /var/log/supervisor/clawdbot-gateway.log`
- MongoDB: `mongosh openclaw_app` then query collections directly
- Auth testing: see `auth_testing.md` for curl-based testing procedures

## Important Caveats

1. **No CI/CD pipeline** - Deployment is manual via `deploy.sh` and `supervisorctl`
2. **Single-file backend** - All routes are in `server.py`; keep this in mind for merge conflicts
3. **Gateway ports are hardcoded** - 18789 (main) and 18791 (control) in `server.py`
4. **Node.js installed manually** - At `/root/nodejs`, not via system package manager
5. **The `.gitignore` is minimal** - Only excludes `__pycache__/`; be careful not to commit `node_modules/`, `.env`, or build artifacts
6. **WhatsApp monitor runs in background** - Auto-fixes Baileys `registered=false` bug every 5 seconds
7. **Instance locking is permanent** - Once set in `instance_config`, only a DB reset clears it
