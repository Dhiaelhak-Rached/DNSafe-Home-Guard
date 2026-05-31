"""HomeGuard diagnostic tool."""

import os
import socket
import subprocess
import sys

print("=" * 60)
print("HomeGuard Diagnostic Report")
print("=" * 60)

# 1. Check if HomeGuard service exists
print("\n[1] Windows Service Status")
result = subprocess.run(["sc", "query", "HomeGuardDNS"], capture_output=True, text=True)
if "RUNNING" in result.stdout:
    print("   Service: RUNNING")
elif "STOPPED" in result.stdout:
    print("   Service: STOPPED")
elif "service does not exist" in result.stdout.lower() or result.returncode != 0:
    print("   Service: NOT INSTALLED")
else:
    print("   Service output:", result.stdout.strip())

# 2. Check DNS settings
print("\n[2] Current DNS Settings")
result = subprocess.run(
    ["powershell", "-Command", "Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object {$_.ServerAddresses} | Select-Object InterfaceAlias,ServerAddresses | Format-Table -AutoSize"],
    capture_output=True, text=True, check=False,
)
for line in result.stdout.splitlines():
    if line.strip():
        print("  ", line)

# 3. Test local DNS port 53
print("\n[3] Local DNS Port 53")
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s.settimeout(2)
try:
    s.sendto(b"test", ("127.0.0.1", 53))
    s.recvfrom(1024)
    print("   Port 53: RESPONDING (something is listening)")
except socket.timeout:
    print("   Port 53: TIMEOUT (nothing is listening on 127.0.0.1:53)")
except Exception as e:
    print(f"   Port 53: ERROR ({e})")
s.close()

# 4. Test local DNS with a real query
print("\n[4] DNS Query Test (pornhub.com via 127.0.0.1:53)")
try:
    import dnslib
    q = dnslib.DNSRecord.question("pornhub.com")
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(3)
    s.sendto(q.pack(), ("127.0.0.1", 53))
    data, _ = s.recvfrom(1024)
    r = dnslib.DNSRecord.parse(data)
    if r.header.rcode == dnslib.RCODE.NXDOMAIN:
        print("   Result: BLOCKED (NXDOMAIN) — HomeGuard is working!")
    else:
        print(f"   Result: ALLOWED (rcode={r.header.rcode}) — HomeGuard is NOT blocking")
    s.close()
except Exception as e:
    print(f"   Result: FAILED ({e})")

# 5. Check installed files
print("\n[5] Installation Files")
install_dir = os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "HomeGuard")
files = ["HomeGuard.exe", "HomeGuardService.exe", "config.ini"]
for f in files:
    path = os.path.join(install_dir, f)
    exists = "OK" if os.path.exists(path) else "MISSING"
    print(f"   {f}: {exists}")

# 6. Check if browser secure DNS might be bypassing
print("\n[6] Browser Secure DNS Check")
print("   If you use Chrome/Edge/Firefox with 'Secure DNS' enabled,")
print("   the browser may bypass Windows DNS and go directly to Cloudflare/Google.")
print("   Disable it in: Settings > Privacy > Security > Use your current DNS provider")

print("\n" + "=" * 60)
print("End of report")
print("=" * 60)
