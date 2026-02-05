# Auth-Gated App Testing Playbook

## Step 1: Create Test User & Session
```bash
# NOTE: Check DB_NAME in /app/backend/.env - usually 'test_database'
mongosh "mongodb://localhost:27017" --eval "
use('test_database');
var userId = 'test-user-' + Date.now();
var sessionToken = 'test_session_' + Date.now();
db.users.insertOne({
  user_id: userId,
  email: 'test.user.' + Date.now() + '@example.com',
  name: 'Test User',
  picture: 'https://via.placeholder.com/150',
  created_at: new Date()
});
db.user_sessions.insertOne({
  user_id: userId,
  session_token: sessionToken,
  expires_at: new Date(Date.now() + 7*24*60*60*1000),
  created_at: new Date()
});
print('Session token: ' + sessionToken);
print('User ID: ' + userId);
"
```

## Step 2: Test Backend API
```bash
# Test auth endpoint
curl -X GET "https://hungry-kapitsa.preview.emergent.test/api/auth/me" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"

# Test protected endpoints
curl -X GET "https://hungry-kapitsa.preview.emergent.test/api/moltbot/status" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

## Step 3: Browser Testing
```python
# Set cookie and navigate
await page.context.add_cookies([{
    "name": "session_token",
    "value": "YOUR_SESSION_TOKEN",
    "domain": "hungry-kapitsa.preview.emergent.test",
    "path": "/",
    "httpOnly": true,
    "secure": true,
    "sameSite": "None"
}]);
await page.goto("https://hungry-kapitsa.preview.emergent.test");
```

## Quick Debug
```bash
# Check data format
mongosh --eval "
use('moltbot_app');
db.users.find().limit(2).pretty();
db.user_sessions.find().limit(2).pretty();
db.moltbot_configs.find().limit(2).pretty();
"

# Clean test data
mongosh --eval "
use('moltbot_app');
db.users.deleteMany({email: /test\.user\./});
db.user_sessions.deleteMany({session_token: /test_session/});
"
```

## Checklist
- [ ] User document has user_id field (custom UUID)
- [ ] Session user_id matches user's user_id exactly
- [ ] All queries use `{"_id": 0}` projection
- [ ] API returns user data with user_id field
- [ ] Browser loads dashboard (not login page)

## Success Indicators
- ✅ /api/auth/me returns user data
- ✅ Dashboard loads without redirect for authenticated user
- ✅ Unauthenticated users see login page
- ✅ Moltbot config is tied to the user who configured it

## Failure Indicators
- ❌ "User not found" errors
- ❌ 401 Unauthorized responses
- ❌ Redirect to login page when already authenticated
