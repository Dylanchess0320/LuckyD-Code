import os, subprocess

p = os.path.join(os.getcwd(), "nul")
full = "\\\\?\\" + p
print("Full path:", full)
print("File exists:", os.path.exists(p))

# Method 1: os.remove with \\?\ prefix
try:
    os.remove(full)
    print("Method 1 (os.remove): SUCCESS")
except Exception as e:
    print(f"Method 1 failed: {e}")

# Method 2: cmd /c del
if os.path.exists(p):
    r = subprocess.run(["cmd", "/c", "del", "/f", full], capture_output=True, text=True)
    print(f"Method 2 (cmd del): rc={r.returncode} err={r.stderr.strip()}")

# Method 3: PowerShell
if os.path.exists(p):
    ps_cmd = f"Remove-Item -Path '{full}' -Force"
    r = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True)
    print(f"Method 3 (powershell): rc={r.returncode} err={r.stderr.strip()}")

print("Still exists:", os.path.exists(p))
