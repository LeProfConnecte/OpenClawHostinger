"""WhatsApp Fix - Handles Baileys registered=false bug"""

import fcntl
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CREDS_FILE = Path.home() / ".clawdbot/credentials/whatsapp/default/creds.json"


def _read_creds_locked() -> dict | None:
    """Read credentials file with a shared (read) lock."""
    if not CREDS_FILE.exists():
        return None
    try:
        with open(CREDS_FILE, 'r') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_SH)
            try:
                return json.load(f)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except (json.JSONDecodeError, OSError) as e:
        logger.error("[WhatsApp Monitor] Error reading credentials: %s", e)
        return None


def fix_registered_flag() -> bool:
    """Fix Baileys registered=false bug. Returns True if fix applied."""
    logger.debug("[WhatsApp Monitor] Checking credentials file: %s", CREDS_FILE)

    if not CREDS_FILE.exists():
        logger.debug("[WhatsApp Monitor] Credentials file does not exist - no WhatsApp linked yet")
        return False

    try:
        # Use exclusive lock for read-modify-write to prevent race conditions
        with open(CREDS_FILE, 'r+') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                creds = json.load(f)

                has_account = bool(creds.get("account"))
                has_me = bool(creds.get("me", {}).get("id"))
                registered = creds.get("registered", False)

                if has_account and has_me and not registered:
                    phone_id = creds.get("me", {}).get("id", "unknown")
                    logger.info("[WhatsApp Monitor] DETECTED registered=false bug for %s, fixing...", phone_id)
                    creds["registered"] = True
                    f.seek(0)
                    json.dump(creds, f)
                    f.truncate()
                    logger.info("[WhatsApp Monitor] Fixed registered=false for %s", phone_id)
                    return True
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    except Exception as e:
        logger.error("[WhatsApp Monitor] Error reading/fixing credentials: %s", e)

    return False


def get_whatsapp_status() -> dict:
    """Get basic WhatsApp status."""
    creds = _read_creds_locked()
    if creds is None:
        return {"linked": False, "phone": None, "registered": False}

    try:
        jid = creds.get("me", {}).get("id", "")
        phone = "+" + jid.split(":")[0] if ":" in jid else None
        linked = bool(creds.get("account"))
        registered = creds.get("registered", False)

        return {
            "linked": linked,
            "phone": phone,
            "registered": registered
        }
    except Exception as e:
        logger.error("[WhatsApp Monitor] Error getting status: %s", e)
        return {"linked": False, "phone": None, "registered": False}
