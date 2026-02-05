# OpenClaw Security & Code Audit Report

**Date:** 2026-02-05
**Scope:** Full repository analysis — backend, frontend, deployment, dependencies
**Objective:** Identify existing and potential errors for robust, secure, regression-free correction

---

## Summary

| Severity | Count |
|----------|-------|
| **CRITICAL** | 5 |
| **HIGH** | 12 |
| **MEDIUM** | 16 |
| **LOW** | 10 |
| **Total** | **43** |

---

## CRITICAL Issues (Immediate Fix Required)

### C1. Shell Injection via API Key in `gateway_config.py`
**File:** `backend/gateway_config.py:41-45`
**Severity:** CRITICAL

The API key is interpolated directly into a shell `export` statement using f-strings. If a user supplies an API key containing shell metacharacters (e.g., `"; rm -rf / #` or `$(malicious_command)`), this results in **arbitrary command execution** when the `.env` file is sourced by the supervisor wrapper script.

```python
lines.append(f'export ANTHROPIC_API_KEY="{api_key}"')  # INJECTION!
```

**Impact:** Remote Code Execution (RCE) on the server.
**Fix:** Escape shell special characters or use a safe key=value format (not shell `export`). Validate API keys against a strict pattern (alphanumeric + dashes only).

---

### C2. CSRF Protection Bypass — Missing Origin Header
**File:** `backend/server.py:1257-1281`
**Severity:** CRITICAL

The CSRF middleware only checks the `Origin` header **when it is present**. If the `Origin` header is missing (which can happen with certain browser configurations, curl requests, or network-level manipulation), the request **bypasses CSRF protection entirely**.

```python
if origin:  # <-- If no Origin header, CSRF check is skipped!
    # ... validation ...
return await call_next(request)
```

**Impact:** All state-changing endpoints (POST/PUT/DELETE/PATCH) are vulnerable to CSRF attacks when Origin is not sent.
**Fix:** Also check the `Referer` header as a fallback. If neither `Origin` nor `Referer` is present on state-changing requests, block the request (or at minimum require authentication).

---

### C3. Gateway Token Stored in Plaintext in MongoDB
**File:** `backend/server.py:769-782, 826-839`
**Severity:** CRITICAL

The gateway token is stored as-is in the `moltbot_configs` collection:
```python
"$set": {
    "token": token,  # Plaintext token in database
    ...
}
```

**Impact:** If the database is compromised (MongoDB has no auth by default), an attacker gains full gateway control.
**Fix:** Hash the token before storing it (use `hashlib.sha256`). On recovery, read the token from the config file (which is already chmod 600), not from the database.

---

### C4. MongoDB Without Authentication
**File:** `backend/.env.example:11`, `deploy/deploy.sh`
**Severity:** CRITICAL

The default MongoDB connection string is `mongodb://127.0.0.1:27017` with **no authentication**. The deployment script installs MongoDB but never configures authentication. Any process on the server can read/write/delete all data.

**Impact:** Session hijacking, data theft, gateway token exfiltration.
**Fix:** Configure MongoDB with authentication (`--auth`), create a dedicated database user, and update the connection string to include credentials.

---

### C5. API Key Written to JSON Config File in Plaintext
**File:** `backend/server.py:536-545, 602-648, 660-677`
**Severity:** CRITICAL

For the "emergent" and direct providers, the user's API key is written directly into `clawdbot.json`:
```python
"apiKey": api_key,  # Plaintext API key in JSON file
```

While the file is chmod 600, this key persists on disk indefinitely. If the server is compromised, all user API keys are exposed.

**Impact:** API key theft for all configured LLM providers.
**Fix:** Store API keys only in the `gateway.env` file (which is cleared on stop) and use environment variable references in the JSON config.

---

## HIGH Issues

### H1. Race Condition in User Creation
**File:** `backend/server.py:300-334`
**Severity:** HIGH

Two simultaneous login requests for the same email can both pass the `find_one({"email": email})` check and try to insert, causing a `DuplicateKeyError`. The generic exception handler at line 368 catches this as a 500 error instead of handling it gracefully.

**Fix:** Use `update_one` with `upsert=True` and `$setOnInsert`, or catch `DuplicateKeyError` explicitly and retry the find.

---

### H2. Race Condition in Instance Lock
**File:** `backend/server.py:133-146`
**Severity:** HIGH

`set_instance_owner` uses `$setOnInsert` with upsert, but `check_instance_access` at line 149 and the lock check at line 304 don't use atomic operations. Two users authenticating simultaneously could both see `owner=None` and both proceed. While `$setOnInsert` prevents overwriting, the second user gets a successful auth response even though they're not the owner.

**Fix:** Make the instance lock check and auth response atomic, or re-check ownership after `set_instance_owner()`.

---

### H3. No Rate Limiting on Authentication Endpoint
**File:** `backend/server.py:272`
**Severity:** HIGH

The `/api/auth/session` endpoint has no rate limiting. An attacker can brute-force session IDs or flood the endpoint to cause denial of service (each request creates an outbound HTTP call to Emergent Auth + a DB write).

**Fix:** Add rate limiting (e.g., `slowapi`) — max 10 requests/minute per IP on auth endpoints.

---

### H4. Session Tokens Not Invalidated on Password/Account Change
**File:** `backend/server.py:340-345`
**Severity:** HIGH

When a user logs in, old sessions are never invalidated. There is no mechanism to revoke all sessions. A stolen session token remains valid for the full 7-day TTL.

**Fix:** Invalidate old sessions on new login, or provide a "revoke all sessions" endpoint.

---

### H5. httpx Client Created Per-Request in Proxy
**File:** `backend/server.py:1024, 281, 818`
**Severity:** HIGH

A new `httpx.AsyncClient()` is created for every proxied request and every auth session exchange. This causes connection pool exhaustion under load and leaks file descriptors.

```python
async with httpx.AsyncClient() as http_client:  # New client per request!
```

**Fix:** Create a single shared `httpx.AsyncClient` at module level or in the app lifecycle, and reuse it across requests.

---

### H6. Token Exposed in URL Query Parameter
**File:** `frontend/src/pages/SetupPage.js:100, 195`
**Severity:** HIGH

The gateway token is passed as a URL query parameter:
```javascript
window.location.href = `${API}/openclaw/ui/?gatewayUrl=...&token=${encodeURIComponent(data.token)}`;
```

**Impact:** The token appears in browser history, server access logs, Referer headers, and potentially analytics/monitoring tools.
**Fix:** Pass the token via a POST form submission, or set it in a cookie/localStorage before redirecting.

---

### H7. `python-jose` Dependency is Unmaintained and Vulnerable
**File:** `backend/requirements.txt:20`
**Severity:** HIGH

`python-jose>=3.3.0` is unmaintained since 2022 and has known vulnerabilities (CVE-2024-33663, CVE-2024-33664 — JWT algorithm confusion attacks). It's listed in requirements but doesn't appear to be used in the code.

**Fix:** Remove `python-jose` from requirements. If JWT is needed, use `PyJWT` (already listed as `pyjwt>=2.10.1`).

---

### H8. WebSocket Has No Message Size Limit
**File:** `backend/server.py:1173-1197`
**Severity:** HIGH

The WebSocket proxy forwards messages of any size between client and Moltbot with no limit. A malicious client could send arbitrarily large messages to exhaust server memory.

**Fix:** Add a maximum message size check (e.g., 1MB) before forwarding.

---

### H9. WebSocket Has No Idle Timeout
**File:** `backend/server.py:1131-1223`
**Severity:** HIGH

WebSocket connections have no idle timeout. A client can hold a connection open indefinitely without sending data, consuming server resources.

**Fix:** Implement an idle timeout (e.g., 30 minutes) that closes connections with no activity.

---

### H10. Cancelled Async Tasks Not Awaited
**File:** `backend/server.py:1212-1214`
**Severity:** HIGH

After cancelling pending WebSocket tasks, they are never awaited:
```python
for task in pending:
    task.cancel()
# Missing: await asyncio.gather(*pending, return_exceptions=True)
```

**Impact:** This can cause `RuntimeWarning: coroutine was never awaited` and resource leaks.
**Fix:** Await the cancelled tasks with `return_exceptions=True`.

---

### H11. Supervisor Processes Run as Root
**File:** `deploy/deploy.sh:204`, `deploy/supervisor-openclaw.conf:25,46`
**Severity:** HIGH

Both the backend and gateway run as `user=root`. If either process is compromised, the attacker has full root access.

**Fix:** Create a dedicated service user (e.g., `openclaw`) and run processes under that user.

---

### H12. `client_name` Field Has No Validation
**File:** `backend/server.py:76`
**Severity:** HIGH

The `StatusCheckCreate` model accepts `client_name` with no length constraint or format validation. This could be exploited for NoSQL injection (e.g., `{"$gt": ""}`) or storage abuse (very long strings).

```python
class StatusCheckCreate(BaseModel):
    client_name: str  # No max_length, no pattern validation
```

**Fix:** Add `max_length=255` and a regex pattern constraint.

---

## MEDIUM Issues

### M1. Deprecated `@app.on_event` Usage
**File:** `backend/server.py:1333, 1428`
**Severity:** MEDIUM

`@app.on_event("startup")` and `@app.on_event("shutdown")` are deprecated in FastAPI. They should use the `lifespan` context manager pattern.

---

### M2. API Key Minimum Length Check Too Weak
**File:** `backend/server.py:874`
**Severity:** MEDIUM

API keys are only validated by `len(request.apiKey) < 10`. This is too permissive — a 10-character garbage string passes validation.

**Fix:** Validate against expected patterns per provider (e.g., `sk-` prefix for OpenAI, `sk-ant-` for Anthropic).

---

### M3. `get_whatsapp_status()` Blocks the Event Loop
**File:** `backend/server.py:939`, `backend/whatsapp_monitor.py:41-62`
**Severity:** MEDIUM

`get_whatsapp_status()` performs synchronous file I/O (`open()`, `json.load()`) in an async context, blocking the event loop.

**Fix:** Use `aiofiles` or run in a thread executor via `asyncio.to_thread()`.

---

### M4. WhatsApp Credential File Race Condition
**File:** `backend/whatsapp_monitor.py:19-33`
**Severity:** MEDIUM

`fix_registered_flag()` reads and writes the credentials file without locking. If the gateway also accesses it simultaneously, data corruption is possible.

**Fix:** Use file locking (`fcntl.flock`) during read-modify-write.

---

### M5. `ensure_moltbot_installed()` Hardcoded Path
**File:** `backend/server.py:428`
**Severity:** MEDIUM

```python
install_script = "/app/backend/install_moltbot_deps.sh"
```

This path is hardcoded to `/app/backend/` but the deployment installs to `/home/clp/htdocs/<domain>/backend/`. The installation will never work in production.

**Fix:** Use `ROOT_DIR / 'install_moltbot_deps.sh'` instead of the hardcoded path.

---

### M6. Missing `Content-Security-Policy` Header
**File:** `deploy/cloudpanel-vhost.conf:39-43`
**Severity:** MEDIUM

Security headers are present but `Content-Security-Policy` is missing. Without CSP, the application is more vulnerable to XSS attacks.

**Fix:** Add a strict CSP header (e.g., `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'`).

---

### M7. WhatsApp Watcher Calls Synchronous `SupervisorClient.restart()`
**File:** `backend/server.py:1325`
**Severity:** MEDIUM

Inside the async `whatsapp_auto_fix_watcher()`, `SupervisorClient.restart()` uses `subprocess.run()` which blocks the event loop for up to 30 seconds.

**Fix:** Use `asyncio.to_thread(SupervisorClient.restart)` or rewrite with `asyncio.create_subprocess_exec`.

---

### M8. No Pagination on Status Checks
**File:** `backend/server.py:1242`
**Severity:** MEDIUM

```python
await db.status_checks.find({}, {"_id": 0}).to_list(1000)
```

Returns up to 1000 documents with no pagination. As data grows, this becomes a performance issue and potential DoS vector.

---

### M9. Unnecessary Dependencies in `requirements.txt`
**File:** `backend/requirements.txt`
**Severity:** MEDIUM

Several dependencies are unused and increase attack surface:
- `boto3` — no AWS usage found
- `requests-oauthlib` — not used (auth is via httpx)
- `pandas`, `numpy` — not used anywhere
- `jq` — not used
- `typer` — not used
- `bcrypt`, `passlib` — not used (no password hashing in the codebase)
- `requests` — httpx is used instead

**Fix:** Remove unused dependencies to reduce attack surface and build size.

---

### M10. CORS Middleware Registered After Routes
**File:** `backend/server.py:1302-1308`
**Severity:** MEDIUM

The CORS middleware is added after the router is included. In Starlette/FastAPI, middleware order matters — this should work but can cause subtle issues with error responses not having CORS headers.

---

### M11. `shutil` Imported Inside Function
**File:** `backend/server.py:419`
**Severity:** MEDIUM (code quality)

`import shutil` is done inside `get_clawdbot_command()`. While functional, this is unexpected and should be a top-level import.

---

### M12. `SUPERVISOR_GATEWAY_PROGRAM` from Environment Variable
**File:** `backend/supervisor_client.py:18`
**Severity:** MEDIUM

```python
PROGRAM = os.environ.get("SUPERVISOR_GATEWAY_PROGRAM", "clawdbot-gateway")
```

This value is used in `subprocess.run(['supervisorctl', 'start', cls.PROGRAM])`. While passed as a list argument (safe from shell injection), a malicious value could target a different supervisor program.

**Fix:** Validate the program name against `^[a-zA-Z0-9_-]+$`.

---

### M13. WebSocket Authentication Before Accept — Error Handling
**File:** `backend/server.py:1136-1143`
**Severity:** MEDIUM

Calling `await websocket.close()` before `await websocket.accept()` may not work correctly in all ASGI server implementations. Some require accepting before closing.

**Fix:** Accept the WebSocket, then immediately close with the error code.

---

### M14. No HSTS Header
**File:** `deploy/cloudpanel-vhost.conf`
**Severity:** MEDIUM

Missing `Strict-Transport-Security` header. Without HSTS, users can be downgraded from HTTPS to HTTP.

**Fix:** Add `add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;`

---

### M15. Token Passed to Gateway Without Authentication Binding
**File:** `backend/server.py:1162-1163`
**Severity:** MEDIUM

The gateway token is sent via `X-Auth-Token` header to the local Moltbot, but there's no mechanism to verify that the token is still valid or hasn't been rotated. If the token changes while a WebSocket is connected, the old connection remains authorized.

---

### M16. `react-scripts` Outdated
**File:** `frontend/package.json:51`
**Severity:** MEDIUM

`react-scripts: 5.0.1` is the last CRA version and is no longer maintained. It bundles Webpack 5 but has known security advisories in transitive dependencies.

**Fix:** Migrate to Vite or maintain with CRACO overrides. At minimum, run `yarn audit` regularly.

---

## LOW Issues

### L1. `@app.on_event("shutdown")` Doesn't Close MongoDB Properly
**File:** `backend/server.py:1446`
**Severity:** LOW

`client.close()` is synchronous. Motor's `AsyncIOMotorClient.close()` should be awaited, though in practice the sync version works at shutdown.

---

### L2. Inconsistent Error Response Formats
**File:** Multiple endpoints
**Severity:** LOW

Some endpoints return `{"ok": True, "message": ...}`, others return Pydantic models, and errors use `{"detail": ...}`. This inconsistency complicates frontend error handling.

---

### L3. Missing `__all__` in Backend Modules
**File:** `backend/gateway_config.py`, `backend/supervisor_client.py`, `backend/whatsapp_monitor.py`
**Severity:** LOW

No `__all__` export declarations, making it unclear what the public API of each module is.

---

### L4. Frontend Missing Error Boundary
**File:** `frontend/src/App.js`
**Severity:** LOW

No React Error Boundary component. Unhandled errors in rendering will crash the entire app with a white screen.

---

### L5. `useEffect` Missing Cleanup on Interval
**File:** `frontend/src/pages/SetupPage.js:158-163`
**Severity:** LOW

The `progressInterval` created in `start()` could leak if the component unmounts during loading. While `clearInterval` is called on success/error, there's no cleanup on unmount.

---

### L6. `next-themes` Dependency Unused
**File:** `frontend/package.json:44`
**Severity:** LOW

`next-themes` is for Next.js. The app uses CRA/CRACO. This dependency is likely unused.

---

### L7. `location.state` Not Cleared After Use
**File:** `frontend/src/pages/SetupPage.js:21`
**Severity:** LOW

`location.state?.user` persists in browser history. Navigating back/forward can cause stale user data to be used.

---

### L8. Log Messages Expose Sensitive Information
**File:** `backend/server.py:289, 312, 501, 737`
**Severity:** LOW

Log messages include user emails and token metadata. In a shared logging system, this could be a privacy concern.

**Fix:** Mask emails and avoid logging token information.

---

### L9. `*.env` in `.gitignore` May Be Too Broad
**File:** `.gitignore:11`
**Severity:** LOW

The pattern `*.env` blocks all files ending with `.env`, which could accidentally exclude legitimate files like `test.env.example`. The `!.env.example` exception mitigates this partially.

---

### L10. Deployment Script Uses `set -e` but Has Fallible Commands
**File:** `deploy/deploy.sh:33, 87, 96-98`
**Severity:** LOW

`set -e` is used but several commands use `|| true` or `2>/dev/null` to suppress failures. This inconsistency can mask real errors during deployment.

---

## Recommendations by Priority

### Immediate (Before Next Deploy)
1. Fix shell injection in `gateway_config.py` (C1)
2. Fix CSRF bypass with missing Origin (C2)
3. Enable MongoDB authentication (C4)
4. Remove `python-jose` from requirements (H7)
5. Fix the hardcoded install script path (M5)

### Short-Term (Within 1 Week)
6. Add rate limiting on auth endpoints (H3)
7. Hash gateway tokens in database (C3)
8. Create a shared httpx client (H5)
9. Stop passing token in URL params (H6)
10. Await cancelled WebSocket tasks (H10)
11. Add WebSocket message size limits (H8)
12. Run services as non-root user (H11)

### Medium-Term (Within 1 Month)
13. Add CSP and HSTS headers (M6, M14)
14. Remove unused dependencies (M9)
15. Fix async blocking calls (M3, M7)
16. Add pagination to status checks (M8)
17. Migrate from deprecated `on_event` (M1)
18. Add React Error Boundary (L4)
19. Validate input fields more strictly (H12, M2)
20. Handle race conditions in user creation and instance lock (H1, H2)
