# app.py
import subprocess
import time
import sys

print("🚀 Starting Security Policy Server...")
policy_process = subprocess.Popen([sys.executable, "policy_server.py"])

# Give the policy server 2 seconds to bind to port 8000
time.sleep(2)

print("🖥️ Starting Web Console Application...")
web_process = subprocess.Popen([sys.executable, "web_server.py"])

# Keep the main script alive while sub-processes run
try:
    web_process.wait()
    policy_process.wait()
except KeyboardInterrupt:
    print("Stopping all services...")
    web_process.terminate()
    policy_process.terminate()
