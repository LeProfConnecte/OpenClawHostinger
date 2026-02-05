"""WhatsApp Fix - Handles Baileys registered=false bug"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CREDS_FILE = Path.home() / ".clawdbot/credentials/whatsapp/default/creds.json"

def fix_registered_flag() -> bool:
    """Fix Baileys registered=false bug. Returns True if fix applied."""
    logger.debug("[WhatsApp Monitor] Checking credentials file: %s", CREDS_FILE)

    if not CREDS_FILE.exists():
        logger.debug("[WhatsApp Monitor] Credentials file does not exist - no WhatsApp linked yet")
        return False

    try:
        with open(CREDS_FILE, 'r') as f:
            creds = json.load(f)

        has_account = bool(creds.get("account"))
        has_me = bool(creds.get("me", {}).get("id"))
        registered = creds.get("registered", False)

        if has_account and has_me and not registered:
            phone_id = creds.get("me", {}).get("id", "unknown")
            logger.info("[WhatsApp Monitor] DETECTED registered=false bug for %s, fixing...", phone_id)
            creds["registered"] = True
            with open(CREDS_FILE, 'w') as f:
                json.dump(creds, f)
            logger.info("[WhatsApp Monitor] Fixed registered=false for %s", phone_id)
            return True

    except Exception as e:
        logger.error("[WhatsApp Monitor] Error reading/fixing credentials: %s", e)

    return False

def get_whatsapp_status() -> dict:
    """Get basic WhatsApp status."""
    if not CREDS_FILE.exists():
        return {"linked": False, "phone": None, "registered": False}

    try:
        with open(CREDS_FILE, 'r') as f:
            creds = json.load(f)

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
