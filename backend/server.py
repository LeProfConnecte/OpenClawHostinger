from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter, HTTPException, WebSocket, WebSocketDisconnect, Request, Response, Query
from fastapi.responses import HTMLResponse, JSONResponse
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocketState
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo.errors import DuplicateKeyError
import hashlib
import os
import re
import shutil
import logging
import json
import secrets
import subprocess
import asyncio
import httpx
import websockets
from websockets.exceptions import ConnectionClosed
from pathlib import Path
from pydantic import BaseModel, Field, ConfigDict, field_validator
from typing import List, Literal, Optional
import uuid
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import time

# WhatsApp monitoring
from whatsapp_monitor import get_whatsapp_status, fix_registered_flag
# Gateway management (supervisor-based)
from gateway_config import write_gateway_env, clear_gateway_env
from supervisor_client import SupervisorClient

ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / '.env')

# MongoDB connection
mongo_url = os.environ['MONGO_URL']
mongo_client = AsyncIOMotorClient(mongo_url)
db = mongo_client[os.environ.get('DB_NAME', 'moltbot_app')]

# Shared httpx client (H5: reuse across requests instead of creating per-request)
_http_client: Optional[httpx.AsyncClient] = None


def get_http_client() -> httpx.AsyncClient:
    """Get the shared httpx AsyncClient instance."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=30.0)
    return _http_client


# Moltbot Gateway Management
MOLTBOT_PORT = 18789
MOLTBOT_CONTROL_PORT = 18791
CONFIG_DIR = os.environ.get("CLAWDBOT_HOME") or os.path.expanduser("~/.clawdbot")
CONFIG_FILE = os.path.join(CONFIG_DIR, "clawdbot.json")
WORKSPACE_DIR = os.environ.get("OPENCLAW_WORKSPACE") or os.path.expanduser("~/clawd")

# Global state for gateway (per-user)
# Note: Process is managed by supervisor, we only track metadata here
gateway_state = {
    "token": None,
    "provider": None,
    "started_at": None,
    "owner_user_id": None  # Track which user owns this instance
}

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============== Rate Limiter (H3) ==============

class RateLimiter:
    """Simple in-memory rate limiter per IP address."""

    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        window_start = now - self.window_seconds
        # Clean old entries
        self._requests[key] = [t for t in self._requests[key] if t > window_start]
        if len(self._requests[key]) >= self.max_requests:
            return False
        self._requests[key].append(now)
        return True


auth_rate_limiter = RateLimiter(max_requests=10, window_seconds=60)
start_rate_limiter = RateLimiter(max_requests=5, window_seconds=60)


def _mask_email(email: str) -> str:
    """Mask email for safe logging (L8)."""
    if not email or '@' not in email:
        return '***'
    local, domain = email.rsplit('@', 1)
    masked_local = local[0] + '***' if local else '***'
    return f"{masked_local}@{domain}"


def _hash_token(token: str) -> str:
    """Hash a token for safe storage in database (C3)."""
    return hashlib.sha256(token.encode()).hexdigest()


# ============== Pydantic Models ==============

class StatusCheck(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_name: str = Field(max_length=255)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class StatusCheckCreate(BaseModel):
    client_name: str = Field(max_length=255, min_length=1)

    @field_validator('client_name')
    @classmethod
    def validate_client_name(cls, v: str) -> str:
        if not re.match(r'^[\w\s\-_.@]+$', v):
            raise ValueError('client_name contains invalid characters')
        return v.strip()


class OpenClawStartRequest(BaseModel):
    provider: Literal["emergent", "anthropic", "openai", "openrouter"] = "emergent"
    apiKey: Optional[str] = None
    model: Optional[str] = None  # Optional model override (mainly for openrouter)

    @field_validator('apiKey')
    @classmethod
    def validate_api_key(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v) < 10:
            raise ValueError('API key must be at least 10 characters')
        if not re.match(r'^[a-zA-Z0-9\-_.:+/=]+$', v):
            raise ValueError('API key contains invalid characters')
        return v

    @field_validator('model')
    @classmethod
    def validate_model(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if len(v) > 200:
            raise ValueError('Model name too long')
        if not re.match(r'^[\w\-./]+$', v):
            raise ValueError('Model name contains invalid characters')
        return v


class OpenClawStartResponse(BaseModel):
    ok: bool
    controlUrl: str
    token: str
    message: str


class OpenClawStatusResponse(BaseModel):
    running: bool
    pid: Optional[int] = None
    provider: Optional[str] = None
    started_at: Optional[str] = None
    controlUrl: Optional[str] = None
    owner_user_id: Optional[str] = None
    is_owner: Optional[bool] = None


class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    user_id: str
    email: str
    name: str
    picture: Optional[str] = None
    created_at: Optional[datetime] = None


class SessionRequest(BaseModel):
    session_id: str = Field(min_length=1, max_length=512)


# ============== Authentication Helpers ==============

EMERGENT_AUTH_URL = "https://demobackend.emergentagent.com/auth/v1/env/oauth/session-data"
SESSION_EXPIRY_DAYS = 7

# Cookie security configuration (configurable for dev/prod)
COOKIE_SECURE = os.environ.get('COOKIE_SECURE', 'true').lower() == 'true'
COOKIE_SAMESITE = os.environ.get('COOKIE_SAMESITE', 'lax')

# WebSocket limits (H8, H9)
WS_MAX_MESSAGE_SIZE = 1 * 1024 * 1024  # 1MB
WS_IDLE_TIMEOUT = 30 * 60  # 30 minutes


async def get_instance_owner() -> Optional[dict]:
    """Get the instance owner from database. Returns None if not locked yet."""
    doc = await db.instance_config.find_one({"_id": "instance_owner"})
    return doc


async def set_instance_owner(user: User) -> bool:
    """Lock the instance to a specific user. Only succeeds if not already locked.
    Returns True if this user is the owner (either newly set or already was)."""
    result = await db.instance_config.update_one(
        {"_id": "instance_owner"},
        {
            "$setOnInsert": {
                "user_id": user.user_id,
                "email": user.email,
                "name": user.name,
                "locked_at": datetime.now(timezone.utc)
            }
        },
        upsert=True
    )
    # H2: Re-verify ownership after upsert to handle race condition
    owner = await get_instance_owner()
    return owner and owner.get("user_id") == user.user_id


async def check_instance_access(user: User) -> bool:
    """Check if user is allowed to access this instance. Returns True if allowed."""
    owner = await get_instance_owner()
    if not owner:
        return True
    return owner.get("user_id") == user.user_id


async def get_current_user(request: Request) -> Optional[User]:
    """
    Get current user from session token.
    Checks cookie first, then Authorization header as fallback.
    Returns None if not authenticated.
    """
    session_token = request.cookies.get("session_token")

    if not session_token:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            session_token = auth_header.split(" ", 1)[1]

    if not session_token:
        return None

    session_doc = await db.user_sessions.find_one(
        {"session_token": session_token},
        {"_id": 0}
    )

    if not session_doc:
        return None

    expires_at = session_doc.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)

    if expires_at < datetime.now(timezone.utc):
        return None

    user_doc = await db.users.find_one(
        {"user_id": session_doc["user_id"]},
        {"_id": 0}
    )

    if not user_doc:
        return None

    return User(**user_doc)


async def require_auth(request: Request) -> User:
    """Dependency that requires authentication and instance access"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")

    if not await check_instance_access(user):
        raise HTTPException(
            status_code=403,
            detail="This instance is locked to another user. Access denied."
        )
    return user


async def get_ws_user(websocket: WebSocket) -> Optional[User]:
    """
    Authenticate a WebSocket connection from cookies BEFORE accept().
    Used to gate WebSocket access to authenticated owners only.
    """
    session_token = websocket.cookies.get("session_token")
    if not session_token:
        return None

    session_doc = await db.user_sessions.find_one(
        {"session_token": session_token},
        {"_id": 0}
    )
    if not session_doc:
        return None

    expires_at = session_doc.get("expires_at")
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        return None

    user_doc = await db.users.find_one(
        {"user_id": session_doc["user_id"]},
        {"_id": 0}
    )
    if not user_doc:
        return None

    return User(**user_doc)


# ============== Lifespan (M1: replaces deprecated on_event) ==============

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown logic."""
    global _http_client
    # --- STARTUP ---
    logger.info("Server starting up...")

    # Create shared httpx client (H5)
    _http_client = httpx.AsyncClient(timeout=30.0)

    # Ensure MongoDB indexes exist for performance and session TTL cleanup
    try:
        await db.user_sessions.create_index("session_token", unique=True)
        await db.user_sessions.create_index("expires_at", expireAfterSeconds=0)
        await db.users.create_index("user_id", unique=True)
        await db.users.create_index("email", unique=True)
        logger.info("MongoDB indexes ensured")
    except Exception as e:
        logger.warning(f"Could not create MongoDB indexes: {e}")

    # Reload supervisor config to pick up any changes
    await asyncio.to_thread(SupervisorClient.reload_config)

    # Check and install Moltbot dependencies if needed
    clawdbot_cmd = get_clawdbot_command()
    if clawdbot_cmd:
        logger.info(f"Moltbot dependencies ready: {clawdbot_cmd}")
    else:
        logger.info("Moltbot dependencies not found, will install on first use")

    # Check database for persistent gateway config
    config_doc = None
    try:
        config_doc = await db.moltbot_configs.find_one({"_id": "gateway_config"})
    except Exception as e:
        logger.warning(f"Could not read gateway config from database: {e}")

    should_run = config_doc.get("should_run", False) if config_doc else False
    logger.info(f"Gateway should_run flag: {should_run}")

    # Check if gateway is already running via supervisor
    is_running = await asyncio.to_thread(SupervisorClient.status)
    if is_running:
        pid = await asyncio.to_thread(SupervisorClient.get_pid)
        logger.info(f"Gateway already running via supervisor (PID: {pid})")

        gateway_state["provider"] = config_doc.get("provider", "emergent") if config_doc else "emergent"

        # Recover token from config file (not from DB — DB only stores hash)
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            gateway_state["token"] = config.get("gateway", {}).get("auth", {}).get("token")
            logger.info("Recovered gateway token from config file")
        except Exception as e:
            logger.warning(f"Could not recover gateway token: {e}")

        if config_doc:
            gateway_state["owner_user_id"] = config_doc.get("owner_user_id")
            gateway_state["started_at"] = config_doc.get("started_at")
            logger.info("Recovered gateway owner from database")

    elif should_run and config_doc:
        logger.info("Gateway should_run=True but not running - auto-starting via supervisor...")

        # Recover token from config file
        token = None
        try:
            with open(CONFIG_FILE, 'r') as f:
                config = json.load(f)
            token = config.get("gateway", {}).get("auth", {}).get("token")
        except (OSError, json.JSONDecodeError, ValueError, AttributeError):
            token = generate_token()

        if not token:
            token = generate_token()

        write_gateway_env(token=token, provider=config_doc.get("provider", "emergent"))

        started = await asyncio.to_thread(SupervisorClient.start)
        if started:
            logger.info("Gateway auto-started successfully via supervisor")
            await asyncio.sleep(3)

            gateway_state["token"] = token
            gateway_state["provider"] = config_doc.get("provider", "emergent")
            gateway_state["owner_user_id"] = config_doc.get("owner_user_id")
            gateway_state["started_at"] = config_doc.get("started_at")
        else:
            logger.error("Failed to auto-start gateway via supervisor")

    # Start WhatsApp auto-fix background watcher
    watcher_task = asyncio.create_task(whatsapp_auto_fix_watcher())
    logger.info("[whatsapp-watcher] Background watcher task created (checks every 5s)")

    yield  # --- APP RUNNING ---

    # --- SHUTDOWN ---
    watcher_task.cancel()
    try:
        await watcher_task
    except asyncio.CancelledError:
        pass

    # Close shared httpx client
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()

    logger.info("Backend shutting down - gateway will continue running via supervisor")
    mongo_client.close()


# Create the main app with lifespan
app = FastAPI(lifespan=lifespan)

# Create a router with the /api prefix
api_router = APIRouter(prefix="/api")


# ============== Auth Endpoints ==============

@api_router.get("/auth/instance")
async def get_instance_status():
    """
    Check if the instance is locked.
    Public endpoint - only returns locked status, no owner details.
    """
    owner = await get_instance_owner()
    if owner:
        return {"locked": True}
    return {"locked": False}


@api_router.post("/auth/session")
async def create_session(request: SessionRequest, req: Request, response: Response):
    """
    Exchange session_id from Emergent Auth for a session token.
    Creates user if not exists, creates session, sets cookie.
    Blocks non-owners if instance is locked.
    """
    # H3: Rate limiting
    client_ip = req.headers.get("x-real-ip") or req.client.host if req.client else "unknown"
    if not auth_rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    try:
        # Call Emergent Auth to get user data
        http_client = get_http_client()
        auth_response = await http_client.get(
            EMERGENT_AUTH_URL,
            headers={"X-Session-ID": request.session_id},
            timeout=10.0
        )

        if auth_response.status_code != 200:
            logger.error(f"Emergent Auth error: {auth_response.status_code}")
            raise HTTPException(status_code=401, detail="Invalid session_id")

        auth_data = auth_response.json()
        email = auth_data.get("email")
        name = auth_data.get("name", email.split("@")[0] if email else "User")
        picture = auth_data.get("picture")

        if not email:
            raise HTTPException(status_code=400, detail="No email in auth response")

        # H1: Use upsert to atomically create or find user (avoids race condition)
        user_id = f"user_{uuid.uuid4().hex[:12]}"
        result = await db.users.update_one(
            {"email": email},
            {
                "$setOnInsert": {
                    "user_id": user_id,
                    "email": email,
                    "created_at": datetime.now(timezone.utc)
                },
                "$set": {"name": name, "picture": picture}
            },
            upsert=True
        )

        # Fetch the actual user (whether newly created or existing)
        user_doc = await db.users.find_one({"email": email}, {"_id": 0})
        user_id = user_doc["user_id"]

        # Check if instance is locked to another user
        owner = await get_instance_owner()
        if owner and owner.get("user_id") != user_id:
            if owner.get("email") != email:
                logger.warning(f"Blocked login attempt from {_mask_email(email)} - instance locked")
                raise HTTPException(
                    status_code=403,
                    detail="This instance is private and locked to the owner. Access denied."
                )

        # H4: Invalidate old sessions for this user before creating new one
        await db.user_sessions.delete_many({"user_id": user_id})

        # Create session
        session_token = secrets.token_hex(32)
        expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_EXPIRY_DAYS)

        await db.user_sessions.insert_one({
            "user_id": user_id,
            "session_token": session_token,
            "expires_at": expires_at,
            "created_at": datetime.now(timezone.utc)
        })

        # Set cookie
        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            secure=COOKIE_SECURE,
            samesite=COOKIE_SAMESITE,
            path="/",
            max_age=SESSION_EXPIRY_DAYS * 24 * 60 * 60
        )

        return {
            "ok": True,
            "user": user_doc
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Session creation error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error during authentication")


@api_router.get("/auth/me")
async def get_me(request: Request):
    """Get current authenticated user"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user.model_dump()


@api_router.post("/auth/logout")
async def logout(request: Request, response: Response):
    """Logout - delete session and clear cookie"""
    session_token = request.cookies.get("session_token")

    if session_token:
        await db.user_sessions.delete_one({"session_token": session_token})

    response.delete_cookie(
        key="session_token",
        path="/",
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE
    )

    return {"ok": True, "message": "Logged out"}


# ============== Moltbot Helpers ==============

# Persistent paths for Node.js and clawdbot (M11: top-level import for shutil)
_home = os.environ.get("HOME", "/root")
NODE_DIR = os.environ.get("NODE_DIR") or os.path.join(_home, "nodejs")
CLAWDBOT_DIR = os.environ.get("CLAWDBOT_BIN_DIR") or os.path.join(_home, ".clawdbot-bin")
CLAWDBOT_WRAPPER = os.environ.get("CLAWDBOT_WRAPPER") or os.path.join(_home, "run_clawdbot.sh")


def get_clawdbot_command():
    """Get the path to clawdbot executable"""
    if os.path.exists(CLAWDBOT_WRAPPER):
        return CLAWDBOT_WRAPPER
    if os.path.exists(f"{CLAWDBOT_DIR}/clawdbot"):
        return f"{CLAWDBOT_DIR}/clawdbot"
    if os.path.exists(f"{NODE_DIR}/bin/clawdbot"):
        return f"{NODE_DIR}/bin/clawdbot"
    clawdbot_path = shutil.which("clawdbot")
    if clawdbot_path:
        return clawdbot_path
    return None


def ensure_moltbot_installed():
    """Ensure Moltbot dependencies are installed"""
    # M5: Use relative path from ROOT_DIR instead of hardcoded /app/backend/
    install_script = str(ROOT_DIR / "install_moltbot_deps.sh")

    clawdbot_cmd = get_clawdbot_command()
    if clawdbot_cmd:
        logger.info(f"Clawdbot found at: {clawdbot_cmd}")
        return True

    if os.path.exists(install_script):
        logger.info("Clawdbot not found, running installation script...")
        try:
            result = subprocess.run(
                ["bash", install_script],
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                logger.info("Moltbot dependencies installed successfully")
                return True
            else:
                logger.error(f"Installation failed: {result.stderr}")
                return False
        except Exception as e:
            logger.error(f"Installation script error: {e}")
            return False

    logger.error("Clawdbot not found and no installation script available")
    return False


def generate_token():
    """Generate a random gateway token"""
    return secrets.token_hex(32)


def create_moltbot_config(token: str = None, api_key: str = None, provider: str = "emergent", force_new_token: bool = False, model: str = None):
    """Update clawdbot.json with gateway config and provider settings.

    C5: API keys for non-emergent providers are stored ONLY in gateway.env,
    not in the JSON config file. The JSON uses env var references.
    """
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(WORKSPACE_DIR, exist_ok=True)

    existing_config = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                existing_config = json.load(f)
        except (OSError, json.JSONDecodeError, ValueError):
            pass

    existing_token = None
    if not force_new_token:
        try:
            existing_token = existing_config.get("gateway", {}).get("auth", {}).get("token")
        except (AttributeError, TypeError):
            pass

    final_token = existing_token or token or generate_token()

    logger.info(f"Config token: {'reusing existing' if existing_token else 'new token'}, provider: {provider}")

    gateway_config = {
        "mode": "local",
        "port": MOLTBOT_PORT,
        "bind": "lan",
        "auth": {
            "mode": "token",
            "token": final_token
        },
        "controlUi": {
            "enabled": True,
            "allowInsecureAuth": True
        }
    }

    existing_config["gateway"] = gateway_config

    if "models" not in existing_config:
        existing_config["models"] = {"mode": "merge", "providers": {}}
    existing_config["models"]["mode"] = "merge"
    if "providers" not in existing_config["models"]:
        existing_config["models"]["providers"] = {}

    if "agents" not in existing_config:
        existing_config["agents"] = {"defaults": {}}
    if "defaults" not in existing_config["agents"]:
        existing_config["agents"]["defaults"] = {}
    existing_config["agents"]["defaults"]["workspace"] = WORKSPACE_DIR

    # C5: Use env var references for API keys in JSON config (not plaintext)
    _env_api_key_ref = "${PROVIDER_API_KEY}"

    if provider == "emergent":
        emergent_key = api_key or os.environ.get('EMERGENT_API_KEY', 'sk-emergent-1234')
        emergent_base_url = os.environ.get('EMERGENT_BASE_URL', 'https://integrations.emergentagent.com/llm')

        emergent_gpt_provider = {
            "baseUrl": f"{emergent_base_url}/",
            "apiKey": emergent_key,
            "api": "openai-completions",
            "models": [
                {
                    "id": "gpt-5.2",
                    "name": "GPT-5.2",
                    "reasoning": True,
                    "input": ["text"],
                    "cost": {
                        "input": 0.00000175,
                        "output": 0.000014,
                        "cacheRead": 0.000000175,
                        "cacheWrite": 0.00000175
                    },
                    "contextWindow": 400000,
                    "maxTokens": 128000
                }
            ]
        }

        emergent_claude_provider = {
            "baseUrl": emergent_base_url,
            "apiKey": emergent_key,
            "api": "anthropic-messages",
            "authHeader": True,
            "models": [
                {
                    "id": "claude-sonnet-4-5",
                    "name": "Claude Sonnet 4.5",
                    "input": ["text"],
                    "cost": {"input": 0.000003, "output": 0.000015, "cacheRead": 0.0000003, "cacheWrite": 0.00000375},
                    "contextWindow": 200000,
                    "maxTokens": 64000
                },
                {
                    "id": "claude-opus-4-5",
                    "name": "Claude Opus 4.5",
                    "input": ["text"],
                    "cost": {"input": 0.000005, "output": 0.000025, "cacheRead": 0.0000005, "cacheWrite": 0.00000625},
                    "contextWindow": 200000,
                    "maxTokens": 64000
                }
            ]
        }

        existing_config["models"]["providers"]["emergent-gpt"] = emergent_gpt_provider
        existing_config["models"]["providers"]["emergent-claude"] = emergent_claude_provider

        existing_config["agents"]["defaults"]["models"] = {
            "emergent-gpt/gpt-5.2": {"alias": "gpt-5.2"},
            "emergent-claude/claude-sonnet-4-5": {"alias": "sonnet"}
        }
        existing_config["agents"]["defaults"]["model"] = {
            "primary": "emergent-claude/claude-sonnet-4-5"
        }

    elif provider == "openai":
        # C5: Don't store API key in JSON — use env var reference
        openai_provider = {
            "baseUrl": "https://api.openai.com/v1/",
            "apiKey": _env_api_key_ref,
            "api": "openai-completions",
            "models": [
                {
                    "id": "gpt-5.2",
                    "name": "GPT-5.2",
                    "reasoning": True,
                    "input": ["text", "image"],
                    "cost": {
                        "input": 0.00000175,
                        "output": 0.000014,
                        "cacheRead": 0.000000175,
                        "cacheWrite": 0.00000175
                    },
                    "contextWindow": 400000,
                    "maxTokens": 128000
                },
                {
                    "id": "o4-mini-2025-04-16",
                    "name": "o4-mini",
                    "reasoning": True,
                    "input": ["text", "image"],
                    "cost": {
                        "input": 0.0000011,
                        "output": 0.0000044
                    },
                    "contextWindow": 200000,
                    "maxTokens": 100000
                },
                {
                    "id": "gpt-4o",
                    "name": "GPT-4o",
                    "reasoning": False,
                    "input": ["text", "image"],
                    "cost": {
                        "input": 0.0000025,
                        "output": 0.00001
                    },
                    "contextWindow": 128000,
                    "maxTokens": 16384
                }
            ]
        }

        existing_config["models"]["providers"]["openai"] = openai_provider
        existing_config["agents"]["defaults"]["models"] = {
            "openai/gpt-5.2": {"alias": "gpt-5.2"}
        }
        existing_config["agents"]["defaults"]["model"] = {
            "primary": "openai/gpt-5.2"
        }

    elif provider == "anthropic":
        anthropic_provider = {
            "baseUrl": "https://api.anthropic.com",
            "apiKey": _env_api_key_ref,
            "api": "anthropic-messages",
            "models": [
                {
                    "id": "claude-opus-4-5-20251101",
                    "name": "Claude Opus 4.5",
                    "input": ["text", "image"],
                    "cost": {"input": 0.000015, "output": 0.000075, "cacheRead": 0.0000015, "cacheWrite": 0.00001875},
                    "contextWindow": 200000,
                    "maxTokens": 64000
                }
            ]
        }

        existing_config["models"]["providers"]["anthropic"] = anthropic_provider
        existing_config["agents"]["defaults"]["models"] = {
            "anthropic/claude-opus-4-5-20251101": {"alias": "opus"}
        }
        existing_config["agents"]["defaults"]["model"] = {
            "primary": "anthropic/claude-opus-4-5-20251101"
        }

    elif provider == "openrouter":
        model_slug = model if model else "openrouter/auto"

        if model_slug.startswith("openrouter/"):
            model_id = model_slug[len("openrouter/"):]
        else:
            model_id = model_slug
            model_slug = f"openrouter/{model_id}"

        openrouter_provider = {
            "baseUrl": "https://openrouter.ai/api/v1/",
            "apiKey": _env_api_key_ref,
            "api": "openai-completions",
            "models": [
                {
                    "id": model_id,
                    "name": model_id,
                    "input": ["text"],
                    "contextWindow": 128000,
                    "maxTokens": 16000
                }
            ]
        }

        existing_config["models"]["providers"]["openrouter"] = openrouter_provider

        existing_config["agents"]["defaults"]["models"] = {
            model_slug: {}
        }
        existing_config["agents"]["defaults"]["model"] = {
            "primary": model_slug
        }

    with open(CONFIG_FILE, "w") as f:
        json.dump(existing_config, f, indent=2)

    os.chmod(CONFIG_FILE, 0o600)

    logger.info(f"Updated Moltbot config at {CONFIG_FILE} for provider: {provider}")
    return final_token


async def start_gateway_process(api_key: str, provider: str, owner_user_id: str, model: str = None):
    """Start the Moltbot gateway process via supervisor (persistent, survives backend restarts)"""
    global gateway_state

    # Check if already running via supervisor (M7: run blocking call in thread)
    is_running = await asyncio.to_thread(SupervisorClient.status)
    if is_running:
        logger.info("Gateway already running via supervisor, applying new config and restarting...")

        token = create_moltbot_config(api_key=api_key, provider=provider, force_new_token=True, model=model)
        write_gateway_env(token=token, api_key=api_key, provider=provider)

        restarted = await asyncio.to_thread(SupervisorClient.restart)
        if not restarted:
            logger.warning("Failed to restart gateway via supervisor, trying stop+start...")
            await asyncio.to_thread(SupervisorClient.stop)
            await asyncio.sleep(2)
            started = await asyncio.to_thread(SupervisorClient.start)
            if not started:
                raise HTTPException(status_code=500, detail="Failed to restart gateway with new configuration")

        gateway_state["token"] = token
        gateway_state["provider"] = provider
        gateway_state["started_at"] = datetime.now(timezone.utc).isoformat()
        gateway_state["owner_user_id"] = owner_user_id

        # C3: Store hashed token in database
        await db.moltbot_configs.update_one(
            {"_id": "gateway_config"},
            {
                "$set": {
                    "should_run": True,
                    "owner_user_id": owner_user_id,
                    "provider": provider,
                    "token_hash": _hash_token(token),
                    "started_at": gateway_state["started_at"],
                    "updated_at": datetime.now(timezone.utc)
                }
            },
            upsert=True
        )

        return token

    clawdbot_cmd = get_clawdbot_command()
    if not clawdbot_cmd:
        if not ensure_moltbot_installed():
            raise HTTPException(status_code=500, detail="OpenClaw (clawdbot) is not installed. Please contact support.")
        clawdbot_cmd = get_clawdbot_command()
        if not clawdbot_cmd:
            raise HTTPException(status_code=500, detail="Failed to find clawdbot after installation")

    token = create_moltbot_config(api_key=api_key, provider=provider, model=model)
    write_gateway_env(token=token, api_key=api_key, provider=provider)

    logger.info(f"Starting Moltbot gateway via supervisor on port {MOLTBOT_PORT}...")

    started = await asyncio.to_thread(SupervisorClient.start)
    if not started:
        raise HTTPException(status_code=500, detail="Failed to start gateway via supervisor")

    gateway_state["token"] = token
    gateway_state["provider"] = provider
    gateway_state["started_at"] = datetime.now(timezone.utc).isoformat()
    gateway_state["owner_user_id"] = owner_user_id

    # Wait for gateway to be ready
    max_wait = 60
    loop = asyncio.get_running_loop()
    start_time = loop.time()

    http_client = get_http_client()
    while loop.time() - start_time < max_wait:
        try:
            resp = await http_client.get(f"http://127.0.0.1:{MOLTBOT_PORT}/", timeout=2.0)
            if resp.status_code == 200:
                logger.info("Moltbot gateway is ready!")

                # C3: Store hashed token in database
                await db.moltbot_configs.update_one(
                    {"_id": "gateway_config"},
                    {
                        "$set": {
                            "should_run": True,
                            "owner_user_id": owner_user_id,
                            "provider": provider,
                            "token_hash": _hash_token(token),
                            "started_at": gateway_state["started_at"],
                            "updated_at": datetime.now(timezone.utc)
                        }
                    },
                    upsert=True
                )

                return token
        except Exception:
            pass
        await asyncio.sleep(1)

    sv_running = await asyncio.to_thread(SupervisorClient.status)
    if not sv_running:
        raise HTTPException(status_code=500, detail="Gateway failed to start via supervisor")

    raise HTTPException(status_code=500, detail="Gateway did not become ready in time")


async def check_gateway_running():
    """Check if the gateway process is still running via supervisor (M7: async)"""
    return await asyncio.to_thread(SupervisorClient.status)


# ============== Moltbot API Endpoints (Protected) ==============

@api_router.get("/")
async def root():
    return {"message": "OpenClaw Hosting API"}


@api_router.post("/openclaw/start", response_model=OpenClawStartResponse)
async def start_moltbot(request: OpenClawStartRequest, req: Request):
    """Start the Moltbot gateway with chosen provider (requires auth)"""
    # H3: Rate limiting
    client_ip = req.headers.get("x-real-ip") or req.client.host if req.client else "unknown"
    if not start_rate_limiter.is_allowed(client_ip):
        raise HTTPException(status_code=429, detail="Too many requests. Please try again later.")

    user = await require_auth(req)

    # For non-emergent providers, API key is required (validation done by Pydantic M2)
    if request.provider in ["anthropic", "openai", "openrouter"] and not request.apiKey:
        raise HTTPException(status_code=400, detail="API key required for anthropic/openai/openrouter providers")

    # Check if Moltbot is already running by another user
    running = await check_gateway_running()
    if running and gateway_state["owner_user_id"] != user.user_id:
        raise HTTPException(
            status_code=403,
            detail="OpenClaw is already running by another user. Please wait for them to stop it."
        )

    try:
        token = await start_gateway_process(request.apiKey, request.provider, user.user_id, request.model)

        # H2: Verify ownership was actually set correctly
        is_owner = await set_instance_owner(user)
        if not is_owner:
            logger.warning(f"Instance lock race: user {_mask_email(user.email)} was not set as owner")

        logger.info(f"Instance locked to user: {_mask_email(user.email)}")

        return OpenClawStartResponse(
            ok=True,
            controlUrl="/api/openclaw/ui/",
            token=token,
            message=f"OpenClaw started successfully with {request.provider} provider"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to start Moltbot: {e}")
        raise HTTPException(status_code=500, detail="Failed to start OpenClaw. Check server logs for details.")


@api_router.get("/openclaw/status", response_model=OpenClawStatusResponse)
async def get_moltbot_status(request: Request):
    """Get the current status of the Moltbot gateway."""
    user = await get_current_user(request)
    running = await check_gateway_running()

    if running:
        is_owner = bool(user and gateway_state["owner_user_id"] == user.user_id)
        if is_owner:
            pid = await asyncio.to_thread(SupervisorClient.get_pid)
            return OpenClawStatusResponse(
                running=True,
                pid=pid,
                provider=gateway_state["provider"],
                started_at=gateway_state["started_at"],
                controlUrl="/api/openclaw/ui/",
                owner_user_id=gateway_state["owner_user_id"],
                is_owner=True
            )
        else:
            return OpenClawStatusResponse(
                running=True,
                is_owner=False if user else None
            )
    else:
        return OpenClawStatusResponse(running=False)


@api_router.get("/openclaw/whatsapp/status")
async def get_whatsapp_connection_status(request: Request):
    """Get basic WhatsApp connection status. Requires authentication."""
    await require_auth(request)
    # M3: Run blocking I/O in thread
    return await asyncio.to_thread(get_whatsapp_status)


@api_router.post("/openclaw/stop")
async def stop_moltbot(request: Request):
    """Stop the Moltbot gateway (only owner can stop)"""
    user = await require_auth(request)

    global gateway_state

    running = await check_gateway_running()
    if not running:
        await db.moltbot_configs.update_one(
            {"_id": "gateway_config"},
            {"$set": {"should_run": False, "updated_at": datetime.now(timezone.utc)}}
        )
        return {"ok": True, "message": "OpenClaw is not running"}

    if gateway_state["owner_user_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Only the owner can stop OpenClaw")

    await asyncio.to_thread(SupervisorClient.stop)

    clear_gateway_env()

    await db.moltbot_configs.update_one(
        {"_id": "gateway_config"},
        {"$set": {"should_run": False, "updated_at": datetime.now(timezone.utc)}}
    )

    gateway_state["token"] = None
    gateway_state["provider"] = None
    gateway_state["started_at"] = None
    gateway_state["owner_user_id"] = None

    return {"ok": True, "message": "OpenClaw stopped"}


@api_router.get("/openclaw/token")
async def get_moltbot_token(request: Request):
    """Get the current gateway token for authentication (only owner)"""
    user = await require_auth(request)

    running = await check_gateway_running()
    if not running:
        raise HTTPException(status_code=404, detail="OpenClaw not running")

    if gateway_state["owner_user_id"] != user.user_id:
        raise HTTPException(status_code=403, detail="Only the owner can access the token")

    return {"token": gateway_state.get("token")}


# ============== Moltbot Proxy (Protected) ==============

@api_router.api_route("/openclaw/ui/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def proxy_moltbot_ui(request: Request, path: str = ""):
    """Proxy requests to the Moltbot Control UI (only owner can access)"""
    user = await get_current_user(request)

    running = await check_gateway_running()
    if not running:
        return HTMLResponse(
            content="<html><body><h1>OpenClaw not running</h1><p>Please start OpenClaw first.</p><a href='/'>Go to setup</a></body></html>",
            status_code=503
        )

    if not user or gateway_state["owner_user_id"] != user.user_id:
        return HTMLResponse(
            content="<html><body><h1>Access Denied</h1><p>This OpenClaw instance is owned by another user.</p><a href='/'>Go back</a></body></html>",
            status_code=403
        )

    target_url = f"http://127.0.0.1:{MOLTBOT_PORT}/{path}"

    if request.query_params:
        target_url += f"?{request.query_params}"

    # H5: Use shared httpx client
    http_client = get_http_client()
    try:
        headers = dict(request.headers)
        headers.pop("host", None)
        headers.pop("content-length", None)
        headers.pop("cookie", None)
        headers.pop("authorization", None)

        body = await request.body()

        response = await http_client.request(
            method=request.method,
            url=target_url,
            headers=headers,
            content=body,
            timeout=30.0
        )

        exclude_headers = {"content-encoding", "content-length", "transfer-encoding", "connection", "www-authenticate"}
        response_headers = {
            k: v for k, v in response.headers.items()
            if k.lower() not in exclude_headers
        }

        content = response.content
        content_type = response.headers.get("content-type", "")

        if "text/html" in content_type:
            content_str = content.decode('utf-8', errors='ignore')
            ws_override = '''
<script>
// OpenClaw Proxy Configuration
window.__MOLTBOT_PROXY_WS_URL__ = (window.location.protocol === 'https:' ? 'wss:' : 'ws:') + '//' + window.location.host + '/api/openclaw/ws';

// Override WebSocket to use proxy path
(function() {
    const originalWS = window.WebSocket;
    const proxyWsUrl = window.__MOLTBOT_PROXY_WS_URL__;

    window.WebSocket = function(url, protocols) {
        let finalUrl = url;

        // Rewrite any OpenClaw gateway URLs to use our proxy
        if (url.includes('127.0.0.1:18789') ||
            url.includes('localhost:18789') ||
            url.includes('0.0.0.0:18789') ||
            (url.includes(':18789') && !url.includes('/api/openclaw/'))) {
            finalUrl = proxyWsUrl;
        }

        // If it's a relative URL or same-origin, redirect to proxy
        try {
            const urlObj = new URL(url, window.location.origin);
            if (urlObj.port === '18789' || urlObj.pathname === '/' && !url.startsWith(proxyWsUrl)) {
                finalUrl = proxyWsUrl;
            }
        } catch (e) {}

        console.log('[OpenClaw Proxy] WebSocket:', url, '->', finalUrl);
        return new originalWS(finalUrl, protocols);
    };

    // Copy static properties
    window.WebSocket.prototype = originalWS.prototype;
    window.WebSocket.CONNECTING = originalWS.CONNECTING;
    window.WebSocket.OPEN = originalWS.OPEN;
    window.WebSocket.CLOSING = originalWS.CLOSING;
    window.WebSocket.CLOSED = originalWS.CLOSED;
})();
</script>
'''
            if '</head>' in content_str:
                content_str = content_str.replace('</head>', ws_override + '</head>')
            elif '<body>' in content_str:
                content_str = content_str.replace('<body>', '<body>' + ws_override)
            else:
                content_str = ws_override + content_str
            content = content_str.encode('utf-8')

        return Response(
            content=content,
            status_code=response.status_code,
            headers=response_headers,
            media_type=response.headers.get("content-type")
        )
    except httpx.RequestError as e:
        logger.error(f"Proxy error: {e}")
        raise HTTPException(status_code=502, detail="Failed to connect to OpenClaw")


# Root proxy for Moltbot UI
@api_router.get("/openclaw/ui")
async def proxy_moltbot_ui_root(request: Request):
    """Redirect to Moltbot UI with trailing slash"""
    return Response(
        status_code=307,
        headers={"Location": "/api/openclaw/ui/"}
    )


# WebSocket proxy for Moltbot (Protected - requires auth + owner)
@api_router.websocket("/openclaw/ws")
async def websocket_proxy(websocket: WebSocket):
    """WebSocket proxy for Moltbot Control UI (authenticated, owner-only)"""
    # Authenticate BEFORE accepting the WebSocket connection
    user = await get_ws_user(websocket)
    if not user:
        # M13: Accept then close for compatibility with all ASGI servers
        await websocket.accept()
        await websocket.close(code=4001, reason="Authentication required")
        return

    if gateway_state.get("owner_user_id") != user.user_id:
        await websocket.accept()
        await websocket.close(code=4003, reason="Access denied: not the instance owner")
        return

    running = await check_gateway_running()
    if not running:
        await websocket.accept()
        await websocket.close(code=1013, reason="OpenClaw not running")
        return

    await websocket.accept()

    token = gateway_state.get("token")
    moltbot_ws_url = f"ws://127.0.0.1:{MOLTBOT_PORT}/"

    logger.info("WebSocket proxy connecting to Moltbot gateway")

    try:
        extra_headers = {}
        if token:
            extra_headers["X-Auth-Token"] = token

        async with websockets.connect(
            moltbot_ws_url,
            ping_interval=20,
            ping_timeout=20,
            close_timeout=10,
            max_size=WS_MAX_MESSAGE_SIZE,  # H8: Message size limit
            additional_headers=extra_headers if extra_headers else None
        ) as moltbot_ws:

            async def client_to_moltbot():
                last_activity = time.monotonic()
                try:
                    while True:
                        try:
                            # H9: Idle timeout check
                            remaining = WS_IDLE_TIMEOUT - (time.monotonic() - last_activity)
                            if remaining <= 0:
                                logger.info("WebSocket idle timeout reached")
                                break

                            data = await asyncio.wait_for(
                                websocket.receive(),
                                timeout=min(remaining, 60)
                            )
                            last_activity = time.monotonic()

                            if data["type"] == "websocket.receive":
                                # H8: Check message size
                                msg = data.get("text") or data.get("bytes", b"")
                                if len(msg) > WS_MAX_MESSAGE_SIZE:
                                    logger.warning("WebSocket message too large, dropping")
                                    continue
                                if "text" in data:
                                    await moltbot_ws.send(data["text"])
                                elif "bytes" in data:
                                    await moltbot_ws.send(data["bytes"])
                            elif data["type"] == "websocket.disconnect":
                                break
                        except asyncio.TimeoutError:
                            continue
                        except WebSocketDisconnect:
                            break
                except Exception as e:
                    logger.error(f"Client to Moltbot error: {e}")

            async def moltbot_to_client():
                try:
                    async for message in moltbot_ws:
                        if websocket.client_state == WebSocketState.CONNECTED:
                            if isinstance(message, str):
                                await websocket.send_text(message)
                            else:
                                await websocket.send_bytes(message)
                except ConnectionClosed as e:
                    logger.info(f"Moltbot WebSocket closed: {e}")
                except Exception as e:
                    logger.error(f"Moltbot to client error: {e}")

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_moltbot()),
                    asyncio.create_task(moltbot_to_client())
                ],
                return_when=asyncio.FIRST_COMPLETED
            )

            # H10: Properly await cancelled tasks
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

    except Exception as e:
        logger.error(f"WebSocket proxy error: {e}")
    finally:
        try:
            if websocket.client_state == WebSocketState.CONNECTED:
                await websocket.close(code=1011, reason="Proxy connection ended")
        except Exception:
            pass


# ============== Legacy Status Endpoints ==============

@api_router.post("/status", response_model=StatusCheck)
async def create_status_check(input: StatusCheckCreate):
    status_dict = input.model_dump()
    status_obj = StatusCheck(**status_dict)

    doc = status_obj.model_dump()
    doc['timestamp'] = doc['timestamp'].isoformat()

    _ = await db.status_checks.insert_one(doc)
    return status_obj


# M8: Add pagination
@api_router.get("/status", response_model=List[StatusCheck])
async def get_status_checks(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0)
):
    status_checks = await db.status_checks.find(
        {}, {"_id": 0}
    ).skip(offset).limit(limit).to_list(limit)

    for check in status_checks:
        if isinstance(check['timestamp'], str):
            check['timestamp'] = datetime.fromisoformat(check['timestamp'])

    return status_checks


# Include the router in the main app
app.include_router(api_router)

# C2: CSRF protection middleware - validates Origin AND Referer headers
@app.middleware("http")
async def csrf_protection(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")

        # Build expected same-origin from request headers
        host = request.headers.get("host", "")
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        expected_origin = f"{forwarded_proto}://{host}"

        # Collect allowed origins: same-origin + configured CORS origins
        allowed = {expected_origin}
        cors_env = os.environ.get('CORS_ORIGINS', '')
        if cors_env and cors_env.strip() != '*':
            for o in cors_env.split(','):
                o = o.strip()
                if o:
                    allowed.add(o)

        if origin:
            # Check Origin header
            if origin not in allowed:
                logger.warning(f"CSRF: blocked request from origin={origin}")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed: origin not allowed"}
                )
        elif referer:
            # Fallback: check Referer header
            referer_origin = referer.split('/', 3)
            if len(referer_origin) >= 3:
                referer_origin = '/'.join(referer_origin[:3])
            else:
                referer_origin = referer
            if referer_origin not in allowed:
                logger.warning(f"CSRF: blocked request with referer={referer_origin}")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed: referer not allowed"}
                )
        else:
            # C2: Neither Origin nor Referer present — block state-changing requests
            # Exception: allow requests that use Bearer token auth (API clients)
            auth_header = request.headers.get("authorization", "")
            if not auth_header.startswith("Bearer "):
                logger.warning("CSRF: blocked request with no Origin or Referer header")
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed: Origin or Referer header required"}
                )

    return await call_next(request)


# CORS configuration
_cors_origins_raw = os.environ.get('CORS_ORIGINS', '').strip()
_cors_allow_credentials = True

if _cors_origins_raw == '*':
    logger.error(
        "CORS_ORIGINS='*' is not allowed with credentials. "
        "Set explicit origins (e.g. CORS_ORIGINS=https://yourdomain.com). "
        "Falling back to same-origin only."
    )
    _cors_origins = []
elif _cors_origins_raw:
    _cors_origins = [o.strip() for o in _cors_origins_raw.split(',') if o.strip()]
else:
    _cors_origins = []

app.add_middleware(
    CORSMiddleware,
    allow_credentials=_cors_allow_credentials,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Background task for auto-fixing WhatsApp
async def whatsapp_auto_fix_watcher():
    """Auto-fix Baileys registered=false bug every 5 seconds."""
    logger.info("[whatsapp-watcher] Background watcher started")
    while True:
        await asyncio.sleep(5)
        try:
            # M3: Run blocking I/O in thread
            status = await asyncio.to_thread(get_whatsapp_status)
            if status["linked"] and not status["registered"]:
                logger.info("[whatsapp-watcher] DETECTED registered=false, applying fix...")
                fixed = await asyncio.to_thread(fix_registered_flag)
                if fixed:
                    logger.info("[whatsapp-watcher] Fix applied, restarting gateway via supervisor...")
                    # M7: Run blocking subprocess in thread
                    restarted = await asyncio.to_thread(SupervisorClient.restart)
                    if restarted:
                        logger.info("[whatsapp-watcher] Gateway restarted successfully")
                    else:
                        logger.error("[whatsapp-watcher] Failed to restart gateway")
        except Exception as e:
            logger.warning("[whatsapp-watcher] Error: %s", e)
