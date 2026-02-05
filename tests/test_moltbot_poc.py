#!/usr/bin/env python3
"""
POC Test Script for Moltbot Gateway
Tests that we can:
1. Create Moltbot config
2. Start the gateway process
3. Access the Control UI on port 18789
"""

import os
import json
import subprocess
import time
import secrets
import requests
import signal
import sys

# Configuration
MOLTBOT_PORT = 18789
CONFIG_DIR = os.path.expanduser("~/.clawdbot")
CONFIG_FILE = os.path.join(CONFIG_DIR, "moltbot.json")
WORKSPACE_DIR = os.path.expanduser("~/clawd")

def generate_token():
    """Generate a random gateway token"""
    return secrets.token_hex(32)

def create_config(token: str, api_provider: str = "anthropic", api_key: str = None):
    """Create a minimal Moltbot configuration"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    os.makedirs(WORKSPACE_DIR, exist_ok=True)
    
    config = {
        "gateway": {
            "mode": "local",
            "port": MOLTBOT_PORT,
            "bind": "loopback",
            "auth": {
                "mode": "token",
                "token": token
            },
            "controlUi": {
                "enabled": True,
                "allowInsecureAuth": True
            }
        },
        "agents": {
            "defaults": {
                "workspace": WORKSPACE_DIR
            }
        }
    }
    
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    
    print(f"✅ Created config at {CONFIG_FILE}")
    return config

def start_gateway(api_key: str = None, api_provider: str = "anthropic"):
    """Start the Moltbot gateway process"""
    env = os.environ.copy()
    
    # Set API key if provided
    if api_key:
        if api_provider == "anthropic":
            env["ANTHROPIC_API_KEY"] = api_key
        elif api_provider == "openai":
            env["OPENAI_API_KEY"] = api_key
    
    # Use a test key for POC
    if not api_key:
        env["ANTHROPIC_API_KEY"] = "sk-test-poc-key"
    
    print(f"🚀 Starting Moltbot gateway on port {MOLTBOT_PORT}...")
    
    process = subprocess.Popen(
        ["clawdbot", "gateway", "--port", str(MOLTBOT_PORT), "--bind", "loopback", "--verbose"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    
    return process

def wait_for_gateway(timeout: int = 30):
    """Wait for the gateway to be ready"""
    url = f"http://127.0.0.1:{MOLTBOT_PORT}/"
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                print(f"✅ Gateway is ready! Status: {response.status_code}")
                return True
        except requests.exceptions.RequestException:
            pass
        time.sleep(1)
        print("⏳ Waiting for gateway...")
    
    print("❌ Gateway did not start within timeout")
    return False

def test_control_ui():
    """Test that the Control UI is accessible"""
    url = f"http://127.0.0.1:{MOLTBOT_PORT}/"
    
    try:
        response = requests.get(url, timeout=5)
        print(f"📊 Control UI Response:")
        print(f"   Status: {response.status_code}")
        print(f"   Content-Type: {response.headers.get('content-type', 'N/A')}")
        print(f"   Content Length: {len(response.text)} chars")
        
        # Check if it looks like the Control UI
        if "<!DOCTYPE html>" in response.text or "<html" in response.text.lower():
            print("✅ Control UI HTML received!")
            return True
        else:
            print(f"⚠️ Unexpected response content: {response.text[:200]}...")
            return False
    except requests.exceptions.RequestException as e:
        print(f"❌ Failed to access Control UI: {e}")
        return False

def cleanup(process):
    """Clean up the gateway process"""
    if process:
        print("🧹 Stopping gateway...")
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        print("✅ Gateway stopped")

def main():
    process = None
    token = generate_token()
    
    try:
        # Step 1: Create config
        print("\n" + "="*50)
        print("Step 1: Creating Moltbot configuration")
        print("="*50)
        create_config(token)
        
        # Step 2: Start gateway
        print("\n" + "="*50)
        print("Step 2: Starting Moltbot gateway")
        print("="*50)
        process = start_gateway()
        
        # Step 3: Wait for gateway to be ready
        print("\n" + "="*50)
        print("Step 3: Waiting for gateway to be ready")
        print("="*50)
        if not wait_for_gateway(timeout=60):
            # Print stderr for debugging
            if process.stderr:
                stderr = process.stderr.read()
                if stderr:
                    print(f"Gateway stderr:\n{stderr}")
            return False
        
        # Step 4: Test Control UI
        print("\n" + "="*50)
        print("Step 4: Testing Control UI access")
        print("="*50)
        if not test_control_ui():
            return False
        
        print("\n" + "="*50)
        print("✅ POC TEST PASSED!")
        print("="*50)
        print(f"Gateway Token: {token}")
        print(f"Control UI URL: http://127.0.0.1:{MOLTBOT_PORT}/")
        
        return True
        
    except Exception as e:
        print(f"❌ POC test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        cleanup(process)

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
